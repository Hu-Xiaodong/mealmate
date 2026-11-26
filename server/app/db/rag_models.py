"""知识库（检索增强生成，Retrieval-Augmented Generation）数据模型。

四张表的关系：
1. kb_index_versions：一批“嵌入”产物的版本号；
2. kb_documents：上传的原始文档；
3. kb_draft_chunks：上传后切好、但还没生成向量的“待索引切片”，
   对应后台“切片列表”里的内容；
4. kb_chunks：已经生成向量、可以被检索的切片。

为什么把“待索引切片”单独放一张表：
上传时只做解析和切片，运营可以先人工检查切片质量，再主动点“建立索引”
才调用嵌入模型。如果直接把未索引的切片塞进 kb_chunks，
检索查询必须反复判断“向量是否为空”，而且切片列表和检索数据混在一起，
清理、重建、统计都容易出错。拆成两张表后，职责非常清楚：
kb_draft_chunks 是“加工中的半成品”，kb_chunks 是“可用的成品”。

为什么向量列只在 PostgreSQL 上是 vector 类型：
- 生产与开发使用 PostgreSQL + pgvector 扩展，vector(1024) 可以建 HNSW 索引，
  检索时用 `<=>` 运算符按余弦距离排序；
- 单元测试使用 SQLite（无需安装数据库），SQLite 没有向量类型，
  因此同一列在 SQLite 上退化成文本，保存 JSON 数组字符串，
  检索时在 Python 里计算余弦相似度。

为什么 embedding 列设置为“延迟加载”（deferred）：
asyncpg 默认不认识 vector 类型，如果查询时把向量列一起读出来会报错。
延迟加载后，常规查询不会带上这一列；写入与检索统一走原生 SQL 并显式
CAST 成 vector，完全绕开驱动层的类型编解码。
"""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow

# 首版嵌入模型固定输出 1024 维。
# 换模型必须新建索引版本并整体重建，不能直接改列维度：
# 不同模型的向量不在同一个语义空间，混用会让检索结果失去意义。
KB_EMBEDDING_DIMENSIONS = 1024

# PostgreSQL 使用 vector(1024)，其他数据库（测试用的 SQLite）使用 Text。
EMBEDDING_TYPE = Text().with_variant(Vector(KB_EMBEDDING_DIMENSIONS), "postgresql")


class KbIndexVersion(Base):
    """索引版本。

    为什么要单独做版本：切片大小、重叠长度、嵌入模型任一变化，
    都会产生一批全新的向量。版本化后可以整批重建、对比效果、随时回退，
    而不需要修改文档本身。
    """

    __tablename__ = "kb_index_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # 实际调用的嵌入供应商标识与模型名，在首次索引成功后写入，
    # 便于回答“这批向量是用哪个模型生成的”。
    embed_provider: Mapped[str] = mapped_column(String(40), default="")
    embed_model: Mapped[str] = mapped_column(String(60), default="")
    dimensions: Mapped[int] = mapped_column(Integer, default=KB_EMBEDDING_DIMENSIONS)
    # 切片目标长度与相邻重叠长度，单位是字符数。
    chunk_size: Mapped[int] = mapped_column(Integer, default=400)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=80)
    # building 构建中、active 当前使用、archived 已归档。
    status: Mapped[str] = mapped_column(String(20), default="building")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KbDocument(Base):
    """知识库文档。

    文件本体放在存储后端（本地磁盘或对象存储），数据库只保存对象键。
    这样迁移存储位置时不需要改数据库，也不会把大文件塞进数据库。
    """

    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    # 来源类型：upload 后台上传、batch_upload 批量导入、system 系统内置（预留）。
    source_type: Mapped[str] = mapped_column(String(20), default="upload", index=True)
    # 批量导入所属批次。单篇上传为空。
    # 为什么不把文档编号写进批次统计：统计会随失败重试变化，
    # 文档与批次的关系是稳定的，落成外键才能按批次反查、审计和以后做整批回滚。
    # 批次被清理时文档保留，因此不做级联删除。
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(80))
    bytes: Mapped[int] = mapped_column(Integer)
    # 文件内容的 SHA-256。重复上传同一份文件时直接拒绝，避免同一知识被检索两次。
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    # uploaded 已上传、parsing 解析中、chunking 切片中、
    # indexing 生成向量中、ready 可用、failed 失败。
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    index_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("kb_index_versions.id"), nullable=True, index=True
    )
    uploaded_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class KbChunk(Base):
    """文档切片。

    一条切片就是检索的最小单位：回答问题时，把用户问题也转成向量，
    找出最相似的若干条切片，再交给对话模型组织答案。
    """

    __tablename__ = "kb_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("kb_documents.id"), index=True)
    index_version_id: Mapped[str] = mapped_column(
        ForeignKey("kb_index_versions.id"), index=True
    )
    # 在文档中的顺序，从 0 开始，便于还原上下文和定位来源。
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # 严格来说数据库里是 vector(1024)，这里标注 Any 是因为
    # Python 侧从不明文读取它（延迟加载 + 原生 SQL 检索）。
    embedding: Mapped[Any | None] = mapped_column(
        EMBEDDING_TYPE, nullable=True, deferred=True
    )
    # 章节标题、标题路径、章节序号等定位信息。
    # 不能命名为 metadata：Declarative Base 已有同名属性，
    # 因此 Python 属性叫 chunk_metadata，数据库列名仍是 metadata。
    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KbDraftChunk(Base):
    """待索引切片：已经切好、还没有生成向量的半成品。

    生命周期：
    1. 上传文档时，按当前启用索引版本的参数切片，结果写进这张表；
    2. 运营在“切片列表”里检查无误后点“建立索引”；
    3. 建立成功后，切片连同向量写入 kb_chunks，本表的对应行删除。

    为什么切片参数（chunk_size、chunk_overlap）存在每一行上：
    kb_documents 是已经上线过的表，直接加列需要额外执行迁移；
    而且切片参数描述的是“这批切片怎么来的”，跟着切片走语义更直接。
    同一份切片的每一行参数相同，少量重复换取查询简单，是刻意取舍。
    """

    __tablename__ = "kb_draft_chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("kb_documents.id"), index=True)
    # 在文档中的顺序，从 0 开始；建立索引后原样写入 kb_chunks.ordinal。
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # 切片时使用的目标长度与重叠长度，用于在切片列表中展示。
    chunk_size: Mapped[int] = mapped_column(Integer, default=400)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=80)
    # 章节标题、标题路径等定位信息；列名与 kb_chunks 保持一致，减少转换代码。
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
