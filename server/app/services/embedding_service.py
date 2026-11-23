"""文本嵌入服务：把文字转换成向量。

什么是嵌入（embedding）：
模型把一段文字映射成一串固定长度的浮点数（本项目是 1024 个），
语义越接近的文字，向量在空间里的方向越接近。
检索时把用户问题也转成向量，比较向量之间的余弦相似度，
就能找出“意思最接近”的知识片段，而不依赖关键词完全一致。

为什么使用 HTTP 直接调用，而不是复用 LangChain：
LangChain 的强项是聊天对话的提示词编排；嵌入接口结构非常简单
（请求只有 model 和 input，返回只有 data 和 usage），
直接用 HTTP 客户端调用更透明、更容易控制重试与批量大小，
也少一层依赖。

同类方案与取舍：
- 云端嵌入接口（OpenAI、通义千问、智谱、DeepSeek 等）：接入快、效果稳定，
  按调用量付费，数据会离开自己的服务器；本项目首版采用这种方式。
- 本地开源模型（BGE、M3E、Sentence-Transformers）：数据不出内网、无调用费，
  但需要 GPU 或较强的 CPU、要自己部署和维护，向量维度也与云端不同。
- 数据库内置的全文检索（PostgreSQL 的 tsvector）：不需要模型和费用，
  但只能匹配关键词，无法理解“番茄炒蛋”和“西红柿炒鸡蛋”是同一道菜。

公司里的常见做法是：先用云端接口快速上线，量大了或数据敏感时
再换成本地模型；因为切片与嵌入都被“索引版本”隔离，
换模型时重建索引即可，不影响业务代码。
"""

import asyncio
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_secret
from app.db.models import AIProvider
from app.db.rag_models import KB_EMBEDDING_DIMENSIONS
from app.services.ai_service import record_call

# 每次请求最多送多少段文本。
# 为什么不是一次把整篇文档都送过去：请求体过大容易超时、失败后重试成本高；
# 32 是常见起点，既能减少请求次数，也便于定位“哪一批失败”。
BATCH_SIZE = 32
# 单个批次最多尝试次数（含首次）。
MAX_ATTEMPTS = 3
# 重试等待基数，单位秒。第 1 次失败等 0.5 秒，第 2 次等 1 秒。
RETRY_BASE_SECONDS = 0.5


class EmbeddingError(Exception):
    """嵌入调用失败。

    code 是稳定的错误码，便于日志检索与前端提示；
    message 是可直接展示给运营的中文说明。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EmbeddingResult:
    """一次嵌入调用的结果。

    除了向量，还带上供应商与模型信息：
    索引版本需要记录“这批向量是用哪个模型生成的”，
    以后排查检索效果时，模型信息比向量本身更重要。
    """

    vectors: list[list[float]]
    provider_name: str
    model: str
    dimensions: int


def _endpoint(base_url: str) -> str:
    """拼接嵌入接口地址。

    后台填写的是“根地址”（例如 https://api.deepseek.com/v1），
    这里补 /embeddings；如果运营直接填了完整地址，则不重复拼接。
    """
    url = base_url.strip().rstrip("/")
    return url if url.endswith("/embeddings") else f"{url}/embeddings"


async def _embedding_provider(db: AsyncSession) -> AIProvider:
    """找出当前可用的嵌入供应商。

    规则与聊天模型一致：只选启用的，按优先级升序取第一个。
    为什么要求单独的 kind=embedding 配置：
    聊天模型和嵌入模型的接口路径、返回结构完全不同，
    把两者混在一张配置里，调用时无法判断该走哪个协议。
    """
    provider = await db.scalar(
        select(AIProvider)
        .where(AIProvider.kind == "embedding", AIProvider.enabled.is_(True))
        .order_by(AIProvider.priority, AIProvider.created_at, AIProvider.id)
    )
    if provider is None:
        raise EmbeddingError(
            "EMBEDDING_PROVIDER_MISSING",
            "尚未配置可用的嵌入模型，请先在「模型配置」中新增用途为 embedding 的供应商",
        )
    return provider


async def _request_embeddings(
    provider: AIProvider, texts: list[str]
) -> tuple[list[list[float]], int]:
    """向供应商发起一次嵌入请求。

    Args:
        provider: 嵌入模型配置（地址、密钥密文、模型名、超时）。
        texts: 本批要转换的文本。
    Returns:
        (向量列表, 消耗的 token 数)。
    Raises:
        EmbeddingError: 网络错误、超时、供应商返回错误或结构不符合预期。
    Why:
        单独抽成一个函数，测试时可以替换掉真实网络请求，
        不用为了跑单元测试去申请密钥或花钱调用云端接口。
    """
    payload = {"model": provider.model, "input": texts}
    headers = {
        "Authorization": f"Bearer {decrypt_secret(provider.api_key_encrypted)}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=provider.timeout_seconds) as client:
            response = await client.post(
                _endpoint(provider.base_url), json=payload, headers=headers
            )
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        raise EmbeddingError("EMBEDDING_TIMEOUT", "嵌入模型请求超时") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise EmbeddingError(
            f"EMBEDDING_HTTP_{status}",
            f"嵌入模型返回错误（HTTP {status}），请检查密钥、模型名与额度",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise EmbeddingError(
            "EMBEDDING_REQUEST_FAILED", "嵌入模型请求失败，请检查网络与接口地址"
        ) from exc

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or len(data) != len(texts):
        raise EmbeddingError(
            "EMBEDDING_RESPONSE_INVALID", "嵌入模型返回的数据数量与请求不一致"
        )
    # 部分兼容服务不保证返回顺序，按 index 排序后再取向量。
    ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
    vectors: list[list[float]] = []
    for item in ordered:
        vector = item.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise EmbeddingError(
                "EMBEDDING_RESPONSE_INVALID", "嵌入模型返回的向量格式不正确"
            )
        vectors.append([float(value) for value in vector])

    usage = body.get("usage") or {}
    tokens = int(usage.get("total_tokens") or usage.get("prompt_tokens") or 0)
    return vectors, tokens


def _check_dimensions(vectors: list[list[float]]) -> None:
    """校验向量维度。

    维度必须与数据库向量列一致（1024）。维度不一致时，
    写入数据库会直接失败，而且错误信息通常很不直观，
    所以在这里提前给出明确提示。
    """
    for vector in vectors:
        if len(vector) != KB_EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                "EMBEDDING_DIMENSION_MISMATCH",
                f"嵌入模型输出 {len(vector)} 维向量，"
                f"与知识库要求的 {KB_EMBEDDING_DIMENSIONS} 维不一致",
            )


async def embed_texts(
    db: AsyncSession,
    texts: list[str],
    *,
    subject_ref: str = "system:kb",
) -> EmbeddingResult:
    """把一批文本转换成向量。

    Args:
        db: 数据库会话。用于读取供应商配置与写入调用日志；
            调用方负责最终提交事务。
        texts: 待转换文本，可以是文档切片，也可以是用户检索问题。
        subject_ref: 调用者标识，写入 AI 调用日志，便于成本核算。
    Returns:
        EmbeddingResult：向量列表与供应商信息。
    Raises:
        EmbeddingError: 未配置供应商、请求失败、重试耗尽或维度不符。
    Why:
        批量、重试、维度校验、调用日志都收敛在这一个入口，
        文档索引与检索测试共用同一套逻辑，行为不会出现两套。
    """
    if not texts:
        return EmbeddingResult([], "", "", KB_EMBEDDING_DIMENSIONS)

    provider = await _embedding_provider(db)
    if provider.dimensions not in (None, KB_EMBEDDING_DIMENSIONS):
        raise EmbeddingError(
            "EMBEDDING_DIMENSION_MISMATCH",
            f"供应商配置的维度是 {provider.dimensions}，"
            f"知识库要求 {KB_EMBEDDING_DIMENSIONS}",
        )

    all_vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        started = time.perf_counter()
        last_error: EmbeddingError | None = None
        vectors: list[list[float]] = []
        tokens = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                vectors, tokens = await _request_embeddings(provider, batch)
                last_error = None
                break
            except EmbeddingError as exc:
                last_error = exc
                record_call(
                    db,
                    subject_ref=subject_ref,
                    context_type="kb_embedding",
                    provider=provider,
                    status="failed",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error_code=exc.code,
                    error_message=exc.message,
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))

        if last_error is not None:
            # 最后一次失败也已经写入调用日志；调用方提交事务时日志会一起落库。
            raise last_error

        _check_dimensions(vectors)
        record_call(
            db,
            subject_ref=subject_ref,
            context_type="kb_embedding",
            provider=provider,
            status="success",
            latency_ms=int((time.perf_counter() - started) * 1000),
            total_tokens=tokens,
            prompt_tokens=tokens,
        )
        all_vectors.extend(vectors)

    return EmbeddingResult(
        vectors=all_vectors,
        provider_name=provider.name,
        model=provider.model,
        dimensions=KB_EMBEDDING_DIMENSIONS,
    )
