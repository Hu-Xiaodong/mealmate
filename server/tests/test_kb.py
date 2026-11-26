"""知识库：切片、上传、嵌入、检索与索引版本测试。

2026-11-24 起上传只做切片，切片进入“切片列表”，
再由“建立索引”接口调用嵌入模型。用例按这两步分开验证。

嵌入模型在用例中替换成确定性的假实现：
不访问网络、不消耗额度，同时能精确验证排序与阈值。
真实调用云端接口的路径由「建立索引失败、修好配置后重试」用例覆盖。
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.services import embedding_service
from app.services.storage import get_storage
from app.services.text_chunker import split_document, strip_media_markup
from tests.conftest import API, auth_headers, data_of
from tests.test_admin import ADMIN_PASSWORD, create_admin, login_as_admin

TOMATO_DOC = """# 番茄选购指南

番茄要选颜色均匀、手感偏重的。青色果蒂说明新鲜，表皮发皱说明放久了。

## 存放方法

常温阴凉处存放，避免阳光直射；切开后需要冷藏并尽快食用。
"""

POTATO_DOC = """# 土豆选购指南

土豆要选表皮光滑、没有发芽的。发芽或变绿的土豆含有龙葵素，不能食用。

## 存放方法

放在干燥通风处，不要和洋葱放在一起，否则容易发芽。
"""


def _fake_vector(text: str) -> list[float]:
    """按关键词生成确定性向量：番茄命中第 0 维，土豆命中第 1 维。"""
    vector = [0.0] * 1024
    if "番茄" in text:
        vector[0] = 1.0
    if "土豆" in text:
        vector[1] = 1.0
    if not any(vector):
        vector[2] = 1.0
    return vector


@pytest.fixture
def fake_embedding(monkeypatch):
    """把真实 HTTP 嵌入调用替换成本地确定性向量。"""

    async def _embed(db, texts, *, subject_ref="system:kb"):
        return embedding_service.EmbeddingResult(
            vectors=[_fake_vector(text) for text in texts],
            provider_name="测试嵌入模型",
            model="fake-embedding-1024",
            dimensions=1024,
        )

    monkeypatch.setattr(embedding_service, "embed_texts", _embed)


async def _upload(client, headers, filename: str, content: str, title: str | None = None):
    form = {"title": title} if title else {}
    return await client.post(
        f"{API}/admin/kb/documents",
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
        data=form,
        headers=headers,
    )


async def _build_index(client, headers, document_id: str):
    """在切片列表中点“建立索引”：把切片交给嵌入模型并写入 kb_chunks。"""
    return await client.post(
        f"{API}/admin/kb/documents/{document_id}/index", headers=headers
    )


def _png_bytes() -> bytes:
    """生成一张最小 PNG，避免测试依赖外部图片文件。"""
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_strip_media_markup_removes_images():
    """生成向量前应去掉 Markdown 与 HTML 图片，只保留可读文字。"""
    text = "步骤一\n\n![白灼虾](./白灼虾.webp)\n\n<img src=\"step.png\" />\n\n完成"
    cleaned = strip_media_markup(text)
    assert "![" not in cleaned
    assert "<img" not in cleaned
    assert "步骤一" in cleaned
    assert "完成" in cleaned


async def test_upload_with_images_rewrites_urls_and_cleans_up(client):
    """随文档上传的图片要保存、改写地址，删除文档时一起清理。"""
    headers = auth_headers(await login_as_admin(client))
    content = (
        "# 白灼虾\n\n## 操作\n\n1. 虾出锅，用干净的盘子装好。\n\n"
        "![白灼虾](./白灼虾.png)\n"
    )
    uploaded = await client.post(
        f"{API}/admin/kb/documents",
        files=[
            ("file", ("白灼虾.md", content.encode("utf-8"), "text/markdown")),
            ("images", ("白灼虾.png", _png_bytes(), "image/png")),
        ],
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert document["status"] == "chunked"
    assert document["imageCount"] == 1
    assert document["unmatchedImageCount"] == 0

    chunks = data_of(
        await client.get(
            f"{API}/admin/kb/documents/{document['id']}/chunks", headers=headers
        )
    )
    joined = "\n".join(item["content"] for item in chunks["items"])
    assert f"/media/kb/{document['id']}/images/白灼虾.png" in joined

    stored = Path(settings.media_root) / "kb" / document["id"] / "images" / "白灼虾.png"
    assert stored.is_file()

    deleted = await client.delete(
        f"{API}/admin/kb/documents/{document['id']}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
    assert not (Path(settings.media_root) / "kb" / document["id"]).exists()


async def test_upload_reports_unmatched_image_reference(client):
    """正文引用了图片但没上传对应文件时，保留原地址并返回未匹配数量。"""
    headers = auth_headers(await login_as_admin(client))
    content = "# 白灼虾\n\n![白灼虾](./missing.png)\n"
    document = data_of(await _upload(client, headers, "白灼虾.md", content))
    assert document["imageCount"] == 0
    assert document["unmatchedImageCount"] == 1

    chunks = data_of(
        await client.get(
            f"{API}/admin/kb/documents/{document['id']}/chunks", headers=headers
        )
    )
    assert any("./missing.png" in item["content"] for item in chunks["items"])


async def test_upload_rejects_invalid_image(client):
    """把非图片文件改名后上传，应在写入存储前被拒绝。"""
    headers = auth_headers(await login_as_admin(client))
    resp = await client.post(
        f"{API}/admin/kb/documents",
        files=[
            ("file", ("白灼虾.md", "# 白灼虾\n".encode(), "text/markdown")),
            ("images", ("fake.png", b"not an image", "image/png")),
        ],
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "KB_IMAGE_INVALID"


def test_text_chunker_splits_by_heading_and_keeps_context():
    paragraph = "番茄要选颜色均匀、手感偏重的，青色果蒂说明新鲜。" * 12
    text = f"# 选购\n\n{paragraph}\n\n# 存放\n\n常温阴凉处存放，避免阳光直射。"
    chunks = split_document(text, title="番茄指南")

    assert chunks, "应当至少产生一个切片"
    assert all(chunk.content.startswith("【番茄指南") for chunk in chunks)
    assert chunks[-1].metadata["heading"] == "存放"
    assert chunks[-1].metadata["headingPath"] == "存放"
    assert all(chunk.token_count > 0 for chunk in chunks)


def test_text_chunker_keeps_overlap_between_neighbours():
    first = "甲" * 500
    second = "乙" * 500
    chunks = split_document(
        f"# 正文\n\n{first}\n\n{second}",
        title="重叠测试",
        target_chars=400,
        max_chars=800,
        overlap_chars=80,
    )
    assert len(chunks) == 2
    assert chunks[0].content[-80:] in chunks[1].content


async def test_upload_chunks_then_build_index_and_search(client, fake_embedding):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    # 第一步：上传只做解析与切片，不调用嵌入模型。
    uploaded = await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南")
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert document["status"] == "chunked"
    assert document["chunkCount"] >= 1
    assert document["indexVersionId"] is None
    assert document["title"] == "番茄指南"

    # 文档列表本身就带“待索引”信息：待索引切片数量与切片参数都要返回，
    # 前端合并成一个列表后不需要再请求“切片列表”。
    listed = data_of(await client.get(f"{API}/admin/kb/documents", headers=headers))
    row = next(item for item in listed["items"] if item["id"] == document["id"])
    assert row["draftChunkCount"] >= 1
    assert row["chunkSize"] and row["chunkOverlap"]
    assert row["chunkedAt"]

    chunks = await client.get(
        f"{API}/admin/kb/documents/{document['id']}/chunks", headers=headers
    )
    assert chunks.status_code == 200
    chunk_data = data_of(chunks)
    assert chunk_data["source"] == "draft"
    assert chunk_data["total"] >= 1
    assert chunk_data["items"][0]["metadata"]["heading"] == "番茄选购指南"

    # 还没建立索引时检索不到这篇文档。
    before = await client.post(
        f"{API}/admin/kb/search-test",
        json={"query": "番茄怎么挑", "topK": 5, "threshold": 0.3},
        headers=headers,
    )
    assert before.status_code == 200, before.text
    assert data_of(before)["items"] == []

    # 第二步：建立索引，状态变为可用并写入索引版本。
    indexed = await _build_index(client, headers, document["id"])
    assert indexed.status_code == 200, indexed.text
    indexed_document = data_of(indexed)
    assert indexed_document["status"] == "ready"
    assert indexed_document["indexVersionId"]
    assert indexed_document["chunkCount"] >= 1

    # 建好索引后待索引切片被删除，文档列表里不再提示“去新建索引”。
    listed_after = data_of(await client.get(f"{API}/admin/kb/documents", headers=headers))
    row_after = next(
        item for item in listed_after["items"] if item["id"] == document["id"]
    )
    assert row_after["draftChunkCount"] == 0
    assert row_after["chunkSize"] is None

    potato = await _upload(client, headers, "potato.md", POTATO_DOC, "土豆指南")
    assert data_of(potato)["status"] == "chunked"
    potato_indexed = data_of(await _build_index(client, headers, data_of(potato)["id"]))
    assert potato_indexed["status"] == "ready"

    # 相同内容再次上传会被拒绝，避免同一知识被检索两次。
    duplicate = await _upload(client, headers, "tomato-copy.md", TOMATO_DOC)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "KB_DOCUMENT_DUPLICATE"

    listed = await client.get(f"{API}/admin/kb/documents", headers=headers)
    assert listed.status_code == 200
    assert len(data_of(listed)["items"]) == 2

    searched = await client.post(
        f"{API}/admin/kb/search-test",
        json={"query": "番茄怎么挑", "topK": 5, "threshold": 0.3},
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    result = data_of(searched)
    assert result["items"], "阈值过滤后应当仍有番茄相关片段"
    assert result["items"][0]["documentTitle"] == "番茄指南"
    assert result["items"][0]["score"] == pytest.approx(1.0, abs=0.001)
    # 土豆片段与番茄问题不相似，低于阈值被过滤。
    assert all(item["documentTitle"] != "土豆指南" for item in result["items"])


async def test_build_index_without_draft_chunks_returns_409(client, fake_embedding):
    """已经建立过索引、切片列表为空时，再次建立索引应明确拒绝。"""
    headers = auth_headers(await login_as_admin(client))
    document = data_of(await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南"))
    assert data_of(await _build_index(client, headers, document["id"]))["status"] == "ready"

    again = await _build_index(client, headers, document["id"])
    assert again.status_code == 409
    assert again.json()["code"] == "KB_DRAFT_CHUNKS_MISSING"


async def test_search_falls_back_to_keyword_when_embedding_unavailable(
    client, fake_embedding, monkeypatch
):
    """嵌入模型临时不可用时，检索测试降级为关键词检索而不是 500。"""
    headers = auth_headers(await login_as_admin(client))
    uploaded = await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南")
    tomato_id = data_of(uploaded)["id"]
    assert data_of(await _build_index(client, headers, tomato_id))["status"] == "ready"

    potato = await _upload(client, headers, "potato.md", POTATO_DOC, "土豆指南")
    potato_id = data_of(potato)["id"]
    assert data_of(await _build_index(client, headers, potato_id))["status"] == "ready"

    async def _broken(db, texts, *, subject_ref="system:kb"):
        raise embedding_service.EmbeddingError(
            "EMBEDDING_REQUEST_FAILED", "嵌入模型连接失败"
        )

    # 只让检索阶段失败，建立索引阶段仍然正常写入切片。
    monkeypatch.setattr(embedding_service, "embed_texts", _broken)

    searched = await client.post(
        f"{API}/admin/kb/search-test",
        json={"query": "番茄怎么挑", "topK": 5, "threshold": 0.3},
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    result = data_of(searched)
    assert result["mode"] == "keyword"
    assert "降级" in (result["warning"] or "")
    assert result["items"]
    assert result["items"][0]["documentTitle"] == "番茄指南"
    assert all(item["documentTitle"] != "土豆指南" for item in result["items"])



async def test_rechunk_then_build_uses_new_active_version(client, fake_embedding):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    uploaded = await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南")
    document = data_of(uploaded)
    indexed = data_of(await _build_index(client, headers, document["id"]))
    assert indexed["status"] == "ready"
    old_version_id = indexed["indexVersionId"]
    assert old_version_id

    created = await client.post(
        f"{API}/admin/kb/index-versions",
        json={"name": "短切片试验", "chunkSize": 200, "chunkOverlap": 20},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    version = data_of(created)
    assert version["status"] == "building"

    activated = await client.post(
        f"{API}/admin/kb/index-versions/{version['id']}/activate", headers=headers
    )
    assert activated.status_code == 200, activated.text
    assert data_of(activated)["status"] == "active"

    # 重新切片：只产生新的待索引切片，旧索引仍然可用。
    rechunked = await client.post(
        f"{API}/admin/kb/documents/{document['id']}/rechunk", headers=headers
    )
    assert rechunked.status_code == 200, rechunked.text
    rechunked_document = data_of(rechunked)
    assert rechunked_document["status"] == "chunked"
    assert rechunked_document["chunkCount"] >= 1
    # 旧索引没有被删除，文档仍指向旧版本，检索不会突然变空。
    assert rechunked_document["indexVersionId"] == old_version_id

    rebuilt = await _build_index(client, headers, document["id"])
    assert rebuilt.status_code == 200, rebuilt.text
    rebuilt_document = data_of(rebuilt)
    assert rebuilt_document["status"] == "ready"
    assert rebuilt_document["indexVersionId"] == version["id"]

    versions = await client.get(f"{API}/admin/kb/index-versions", headers=headers)
    statuses = {item["id"]: item["status"] for item in data_of(versions)["items"]}
    assert statuses[version["id"]] == "active"
    assert statuses[old_version_id] == "archived"


async def test_upload_without_embedding_provider_chunks_then_build_fails(client):
    """没有配置嵌入模型时，切片仍会生成；建立索引才失败，且切片保留可重试。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)

    uploaded = await _upload(client, headers, "guide.md", TOMATO_DOC, "番茄指南")
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert document["status"] == "chunked"
    assert document["chunkCount"] >= 1
    assert document["indexVersionId"] is None

    failed = data_of(await _build_index(client, headers, document["id"]))
    assert failed["status"] == "failed"
    assert "嵌入模型" in (failed["errorMessage"] or "")

    # 失败后切片不丢，文档列表里仍然显示待索引，可以直接重试。
    listed = data_of(await client.get(f"{API}/admin/kb/documents", headers=headers))
    row = next(item for item in listed["items"] if item["id"] == document["id"])
    assert row["draftChunkCount"] >= 1


async def test_failed_build_can_retry_after_embedding_available(
    client, monkeypatch
):
    """建立索引失败后，补好嵌入模型配置可以直接重试，不需要重新上传。"""
    headers = auth_headers(await login_as_admin(client))
    document = data_of(await _upload(client, headers, "guide.md", TOMATO_DOC, "番茄指南"))
    failed = data_of(await _build_index(client, headers, document["id"]))
    assert failed["status"] == "failed"

    async def _fake(db, texts, *, subject_ref="system:kb"):
        return embedding_service.EmbeddingResult(
            vectors=[_fake_vector(text) for text in texts],
            provider_name="测试嵌入模型",
            model="fake-embedding-1024",
            dimensions=1024,
        )

    monkeypatch.setattr(embedding_service, "embed_texts", _fake)
    retried = data_of(await _build_index(client, headers, document["id"]))
    assert retried["status"] == "ready"
    assert retried["indexVersionId"]


async def test_kb_requires_permission_and_valid_file_type(client, fake_embedding):
    await create_admin("content01", ADMIN_PASSWORD, "content_operator")
    login = await client.post(
        f"{API}/admin/auth/login",
        json={"username": "content01", "password": ADMIN_PASSWORD},
    )
    denied_token = data_of(login)["token"]
    denied = await client.get(
        f"{API}/admin/kb/documents", headers=auth_headers(denied_token)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "ADMIN_PERMISSION_DENIED"

    # AI 运营角色同时拥有文档管理与检索测试权限。
    await create_admin("ai01", ADMIN_PASSWORD, "ai_operator")
    ai_login = await client.post(
        f"{API}/admin/auth/login",
        json={"username": "ai01", "password": ADMIN_PASSWORD},
    )
    ai_headers = auth_headers(data_of(ai_login)["token"])
    allowed = await client.get(f"{API}/admin/kb/documents", headers=ai_headers)
    assert allowed.status_code == 200

    unsupported = await _upload(client, ai_headers, "menu.pdf", "不是文本")
    assert unsupported.status_code == 400
    assert unsupported.json()["code"] == "KB_FILE_TYPE_UNSUPPORTED"


async def test_provider_kind_and_dimensions(client):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    chat = await client.post(
        f"{API}/admin/ai-providers",
        json={
            "name": "聊天模型",
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-chat-123456",
            "model": "chat-model",
        },
        headers=headers,
    )
    assert chat.status_code == 200, chat.text
    assert data_of(chat)["kind"] == "chat"
    assert data_of(chat)["dimensions"] is None

    embedding = await client.post(
        f"{API}/admin/ai-providers",
        json={
            "name": "嵌入模型",
            "kind": "embedding",
            "dimensions": 1024,
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-embed-123456",
            "model": "embedding-model",
        },
        headers=headers,
    )
    assert embedding.status_code == 200, embedding.text
    assert data_of(embedding)["kind"] == "embedding"
    assert data_of(embedding)["dimensions"] == 1024

    invalid = await client.post(
        f"{API}/admin/ai-providers",
        json={
            "name": "维度错误模型",
            "kind": "embedding",
            "dimensions": 512,
            "baseUrl": "https://api.example.com/v1",
            "apiKey": "sk-embed-123456",
            "model": "embedding-model",
        },
        headers=headers,
    )
    assert invalid.status_code == 422


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    """在内存里生成 ZIP，避免测试依赖外部压缩包文件。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


async def _create_batch(client, headers, *, files, paths=None, archive=None, label=None):
    data = {"label": label} if label else {}
    if paths is not None:
        data["paths"] = json.dumps(paths, ensure_ascii=False)
    return await client.post(
        f"{API}/admin/kb/import-batches",
        files=files,
        data=data,
        headers=headers,
    )


async def test_batch_import_folder_matches_images_and_ignores_other_files(client):
    """文件夹上传：两篇文档、一张同目录图片、一个不支持的文件。"""
    headers = auth_headers(await login_as_admin(client))
    content = (
        "# 白灼虾\n\n## 操作\n\n水开后下锅，变色立刻捞出。\n\n"
        "![白灼虾](./白灼虾.png)\n"
    )
    paths = [
        "资料/菜谱/白灼虾.md",
        "资料/菜谱/白灼虾.png",
        "资料/其他/番茄.txt",
        "资料/说明.pdf",
        "资料/素材/封面.png",
    ]
    response = await _create_batch(
        client,
        headers,
        files=[
            ("files", ("白灼虾.md", content.encode("utf-8"), "text/markdown")),
            ("files", ("白灼虾.png", _png_bytes(), "image/png")),
            ("files", ("番茄.txt", TOMATO_DOC.encode("utf-8"), "text/plain")),
            ("files", ("说明.pdf", b"%PDF-1.4", "application/pdf")),
            ("files", ("封面.png", _png_bytes(), "image/png")),
        ],
        paths=paths,
        label="文件夹导入",
    )
    assert response.status_code == 200, response.text
    batch = data_of(response)
    # 创建接口返回的是“刚建好”的快照，后台任务此时还没开始执行。
    assert batch["label"] == "文件夹导入"
    assert batch["status"] == "pending"
    assert batch["stats"]["total"] == 2
    # PDF 不在白名单内，只计入忽略数量，不影响其他文件。
    assert batch["stats"]["ignored"] == 1
    # 封面.png 没有被任何文档引用：除了数量，还要能指出具体是哪个文件。
    assert batch["stats"]["unusedImages"] == 1
    assert batch["stats"]["unusedImagePaths"] == ["资料/素材/封面.png"]
    assert len(batch["items"]) == 2

    # 后台任务在响应返回后执行，测试里通过详情接口读取最终状态。
    detail = data_of(
        await client.get(f"{API}/admin/kb/import-batches/{batch['id']}", headers=headers)
    )
    assert detail["status"] == "succeeded"
    assert detail["stats"]["succeeded"] == 2
    assert detail["stats"]["failed"] == 0
    # 汇总阶段必须保留明细，否则批次结束后界面就看不到是哪几张图片未被引用。
    assert detail["stats"]["unusedImagePaths"] == ["资料/素材/封面.png"]
    assert detail["finishedAt"]
    assert {item["status"] for item in detail["items"]} == {"succeeded"}

    listed = data_of(await client.get(f"{API}/admin/kb/documents", headers=headers))
    assert len(listed["items"]) == 2
    assert {item["sourceType"] for item in listed["items"]} == {"batch_upload"}

    shrimp = next(item for item in listed["items"] if item["title"] == "白灼虾")
    chunks = data_of(
        await client.get(
            f"{API}/admin/kb/documents/{shrimp['id']}/chunks", headers=headers
        )
    )
    joined = "\n".join(item["content"] for item in chunks["items"])
    assert f"/media/kb/{shrimp['id']}/images/白灼虾.png" in joined

    # 整批成功后，暂存目录会被清理，避免对象存储里留下重复副本。
    assert not (Path(settings.media_root) / "kb" / "imports" / batch["id"]).exists()


async def test_batch_import_zip_partial_failure_retries_only_failed_file(client):
    """ZIP 中有非法编码文件时整批部分失败，修好暂存文件后可单独重试。"""
    headers = auth_headers(await login_as_admin(client))
    archive = _zip_bytes(
        {
            "资料/正常.md": TOMATO_DOC.encode("utf-8"),
            "资料/乱码.txt": b"\xff\xfe\x00bad",
            "资料/图片/步骤.png": _png_bytes(),
        }
    )
    response = await _create_batch(
        client,
        headers,
        files=[("archive", ("资料包.zip", archive, "application/zip"))],
        label="压缩包导入",
    )
    assert response.status_code == 200, response.text
    created = data_of(response)
    batch = data_of(
        await client.get(
            f"{API}/admin/kb/import-batches/{created['id']}", headers=headers
        )
    )
    assert batch["status"] == "partial"
    assert batch["stats"]["total"] == 2
    assert batch["stats"]["succeeded"] == 1
    assert batch["stats"]["failed"] == 1
    # 图片没有被正文引用，只计入未使用数量，不生成任务。
    assert batch["stats"]["unusedImages"] == 1

    failed_item = next(item for item in batch["items"] if item["status"] == "failed")
    assert failed_item["filename"] == "乱码.txt"
    assert "UTF-8" in (failed_item["errorMessage"] or "")

    # 模拟运营把有问题的文件替换成正确内容：
    # 暂存键按文件顺序生成，这里直接改写第二个文档的暂存对象。
    staged_key = f"kb/imports/{batch['id']}/docs/0001_乱码.txt"
    get_storage().put(staged_key, POTATO_DOC.encode("utf-8"))

    retried = await client.post(
        f"{API}/admin/kb/import-batches/{batch['id']}/retry", headers=headers
    )
    assert retried.status_code == 200, retried.text
    assert data_of(retried)["stats"]["failed"] == 1  # 返回的是重试前快照

    detail = data_of(
        await client.get(f"{API}/admin/kb/import-batches/{batch['id']}", headers=headers)
    )
    assert detail["status"] == "succeeded"
    assert detail["stats"]["succeeded"] == 2
    retried_item = next(item for item in detail["items"] if item["filename"] == "乱码.txt")
    assert retried_item["status"] == "succeeded"
    assert retried_item["attempts"] == 2


async def test_batch_import_rejects_zip_path_traversal(client):
    """压缩包内出现 ../ 时必须整批拒绝，不能写到目标目录之外。"""
    headers = auth_headers(await login_as_admin(client))
    archive = _zip_bytes({"../逃逸.md": "# 不该写入".encode()})
    response = await _create_batch(
        client,
        headers,
        files=[("archive", ("危险.zip", archive, "application/zip"))],
    )
    assert response.status_code == 400
    assert response.json()["code"] == "KB_IMPORT_PATH_INVALID"


async def test_batch_import_skips_duplicate_content(client):
    """批次内出现已存在的内容时记为跳过，不算失败。"""
    headers = auth_headers(await login_as_admin(client))
    first = await _upload(client, headers, "番茄.md", TOMATO_DOC, "番茄指南")
    assert data_of(first)["status"] == "chunked"

    archive = _zip_bytes({"另一份/番茄副本.md": TOMATO_DOC.encode("utf-8")})
    response = await _create_batch(
        client,
        headers,
        files=[("archive", ("重复内容.zip", archive, "application/zip"))],
    )
    assert response.status_code == 200, response.text
    created = data_of(response)
    batch = data_of(
        await client.get(
            f"{API}/admin/kb/import-batches/{created['id']}", headers=headers
        )
    )
    assert batch["status"] == "succeeded"
    assert batch["stats"]["skipped"] == 1
    assert batch["stats"]["failed"] == 0
    assert "相同内容" in (batch["items"][0]["errorMessage"] or "")


async def test_batch_delete_documents_reports_per_item_result(client):
    """批量删除：有效编号被删除，不存在的编号单独失败，不影响其他项。"""
    headers = auth_headers(await login_as_admin(client))
    first = data_of(await _upload(client, headers, "批量删除一.md", "# 一\n\n内容一。\n"))
    second = data_of(await _upload(client, headers, "批量删除二.md", "# 二\n\n内容二。\n"))

    response = await client.post(
        f"{API}/admin/kb/documents/batch-delete",
        json={"documentIds": [first["id"], second["id"], "kbd_missing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = data_of(response)
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    missing = next(item for item in result["results"] if not item["ok"])
    assert missing["documentId"] == "kbd_missing"
    assert missing["errorCode"] == "KB_DOCUMENT_NOT_FOUND"

    listed = data_of(await client.get(f"{API}/admin/kb/documents", headers=headers))
    assert listed["items"] == []


async def test_recipe_draft_requires_explicit_generation(client):
    """上传只存资料与切片，菜谱草稿必须由运营显式触发；重复触发只更新同一条。

    不在上传时自动生成，是为了避免批量导入时悄悄产生大量没人核对的草稿；
    生成动作放在文档行“生成菜谱”或批量操作里，运营明确知道自己在做什么。
    """
    headers = auth_headers(await login_as_admin(client))
    content = """# 番茄炒蛋

预估烹饪时间：15 分钟
预估烹饪难度：★★

## 必备原料和工具

- 番茄 2 个
- 鸡蛋 3 个
- 食用油 10ml
- 炒锅

## 计算

一份正好够 2 个人食用

## 操作

1. 番茄切块，鸡蛋打散。
2. 热锅下油，倒入蛋液炒至凝固后盛出。
3. 下番茄翻炒出汁，倒回鸡蛋，加盐调味。

## 附加内容

- 番茄去皮口感更好。
"""
    uploaded = await _upload(client, headers, "番茄炒蛋.md", content)
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert "recipeDraftTitle" not in document

    drafts_before = data_of(
        await client.get(f"{API}/admin/recipes", params={"status": "draft"}, headers=headers)
    )
    assert drafts_before["items"] == []

    generated = await client.post(
        f"{API}/admin/kb/documents/{document['id']}/recipe-draft", headers=headers
    )
    assert generated.status_code == 200, generated.text
    result = data_of(generated)
    assert result["created"] is True

    listed = data_of(
        await client.get(f"{API}/admin/recipes", params={"status": "draft"}, headers=headers)
    )
    draft = next(item for item in listed["items"] if item["id"] == result["recipeId"])
    assert draft["status"] == "draft"
    assert draft["totalMinutes"] == 15
    assert draft["servings"] == 2
    assert draft["tools"] == ["wok"]
    # 分类默认“推荐”：客户端列表按分类筛选，分类为空的菜谱发布后也查不到。
    assert draft["categories"] == ["recommended"]
    assert len(draft["ingredients"]) == 3
    assert len(draft["steps"]) == 3

    regenerated = await client.post(
        f"{API}/admin/kb/documents/{document['id']}/recipe-draft", headers=headers
    )
    assert regenerated.status_code == 200, regenerated.text
    assert data_of(regenerated)["created"] is False
    assert data_of(regenerated)["recipeId"] == result["recipeId"]

    listed_again = data_of(
        await client.get(f"{API}/admin/recipes", params={"status": "draft"}, headers=headers)
    )
    assert sum(1 for item in listed_again["items"] if item["id"] == result["recipeId"]) == 1


async def test_batch_rechunk_recipe_and_index(client, fake_embedding):
    """批量重新切片、生成菜谱、建立索引：逐篇执行并汇总结果。

    三个操作都允许部分失败，所以接口返回成功、失败、跳过数量与逐篇结果；
    超过 20 篇时直接 422，避免一次请求占用太久。
    """
    headers = auth_headers(await login_as_admin(client))
    template = """# {title}

预估烹饪时间：10 分钟

## 必备原料和工具

- 鸡蛋 2 个
- 食用油 5ml
- 炒锅

## 操作

1. 鸡蛋打散。
2. 热锅下油炒熟。

## 附加内容

- 少放盐。
"""
    first = data_of(
        await _upload(client, headers, "批量番茄.md", template.format(title="批量番茄"))
    )
    second = data_of(
        await _upload(client, headers, "批量青椒.md", template.format(title="批量青椒"))
    )
    ids = [first["id"], second["id"]]

    recipe_result = data_of(
        await client.post(
            f"{API}/admin/kb/documents/batch-recipe-draft",
            json={"documentIds": ids},
            headers=headers,
        )
    )
    assert recipe_result["succeeded"] == 2
    assert recipe_result["failed"] == 0

    rechunk_result = data_of(
        await client.post(
            f"{API}/admin/kb/documents/batch-rechunk",
            json={"documentIds": ids},
            headers=headers,
        )
    )
    assert rechunk_result["succeeded"] == 2
    for item in rechunk_result["results"]:
        assert item["ok"] is True

    index_result = data_of(
        await client.post(
            f"{API}/admin/kb/documents/batch-index",
            json={"documentIds": ids},
            headers=headers,
        )
    )
    assert index_result["succeeded"] == 2
    assert index_result["failed"] == 0

    ready = data_of(
        await client.get(
            f"{API}/admin/kb/documents", params={"status": "ready"}, headers=headers
        )
    )
    assert {item["id"] for item in ready["items"]} >= set(ids)

    too_many = await client.post(
        f"{API}/admin/kb/documents/batch-index",
        json={"documentIds": [f"kbd_{index}" for index in range(21)]},
        headers=headers,
    )
    assert too_many.status_code == 422


async def test_document_list_paginates_and_reports_total(client):
    """文档列表按页码返回，并带上总数，前端才能算出总页数。

    文档会越积越多，接口必须只返回当前页；同时筛选条件和总数
    要使用同一组查询条件，否则会出现“总数 3、第 2 页却没数据”。
    """
    headers = auth_headers(await login_as_admin(client))
    for index in range(3):
        await _upload(
            client,
            headers,
            f"分页验证{index}.md",
            f"# 分页验证 {index}\n\n第 {index} 篇。",
        )

    first = data_of(
        await client.get(
            f"{API}/admin/kb/documents", params={"page": 1, "pageSize": 2}, headers=headers
        )
    )
    assert first["total"] == 3
    assert first["page"] == 1
    assert first["pageSize"] == 2
    assert len(first["items"]) == 2

    second = data_of(
        await client.get(
            f"{API}/admin/kb/documents", params={"page": 2, "pageSize": 2}, headers=headers
        )
    )
    assert second["total"] == 3
    assert len(second["items"]) == 1

    too_large = await client.get(
        f"{API}/admin/kb/documents", params={"pageSize": 101}, headers=headers
    )
    assert too_large.status_code == 422


async def test_batch_delete_accepts_selection_larger_than_fifty(client):
    """勾选全部文档时可能超过 50 篇，接口不应把它当成格式错误。

    曾经上限是 50，用户在列表里全选（例如 64 篇）后点批量删除，
    后端直接返回 422，界面只显示“提交内容不完整或格式不正确”，很难排查。
    现在上限与文档列表一致（200 篇），超过才拒绝。
    """
    headers = auth_headers(await login_as_admin(client))
    ids = [f"kbd_missing_{index}" for index in range(51)]
    response = await client.post(
        f"{API}/admin/kb/documents/batch-delete",
        json={"documentIds": ids},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert data_of(response)["failed"] == 51

    too_many = await client.post(
        f"{API}/admin/kb/documents/batch-delete",
        json={"documentIds": [f"kbd_{index}" for index in range(201)]},
        headers=headers,
    )
    assert too_many.status_code == 422

