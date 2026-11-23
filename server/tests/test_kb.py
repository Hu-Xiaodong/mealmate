"""知识库：切片、上传、嵌入、检索与索引版本测试。

嵌入模型在用例中替换成确定性的假实现：
不访问网络、不消耗额度，同时能精确验证排序与阈值。
真实调用云端接口的路径由「失败时文档进入 failed」用例覆盖。
"""

import pytest

from app.services import embedding_service
from app.services.text_chunker import split_document
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


async def test_upload_indexes_document_and_search_ranks(client, fake_embedding):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    uploaded = await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南")
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert document["status"] == "ready"
    assert document["chunkCount"] >= 1
    assert document["title"] == "番茄指南"

    potato = await _upload(client, headers, "potato.md", POTATO_DOC, "土豆指南")
    assert data_of(potato)["status"] == "ready"

    # 相同内容再次上传会被拒绝，避免同一知识被检索两次。
    duplicate = await _upload(client, headers, "tomato-copy.md", TOMATO_DOC)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "KB_DOCUMENT_DUPLICATE"

    listed = await client.get(f"{API}/admin/kb/documents", headers=headers)
    assert listed.status_code == 200
    assert len(data_of(listed)["items"]) == 2

    chunks = await client.get(
        f"{API}/admin/kb/documents/{document['id']}/chunks", headers=headers
    )
    assert chunks.status_code == 200
    chunk_data = data_of(chunks)
    assert chunk_data["total"] >= 1
    assert chunk_data["items"][0]["metadata"]["heading"] == "番茄选购指南"

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


async def test_reindex_uses_new_active_version(client, fake_embedding):
    token = await login_as_admin(client)
    headers = auth_headers(token)

    uploaded = await _upload(client, headers, "tomato.md", TOMATO_DOC, "番茄指南")
    document = data_of(uploaded)
    old_version_id = document["indexVersionId"]
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

    rebuilt = await client.post(
        f"{API}/admin/kb/documents/{document['id']}/reindex", headers=headers
    )
    assert rebuilt.status_code == 200, rebuilt.text
    rebuilt_document = data_of(rebuilt)
    assert rebuilt_document["status"] == "ready"
    assert rebuilt_document["indexVersionId"] == version["id"]

    versions = await client.get(f"{API}/admin/kb/index-versions", headers=headers)
    statuses = {item["id"]: item["status"] for item in data_of(versions)["items"]}
    assert statuses[version["id"]] == "active"
    assert statuses[old_version_id] == "archived"


async def test_upload_without_embedding_provider_marks_failed(client):
    """没有配置嵌入模型时，文件仍会保存，但文档状态是 failed 且带原因。"""
    token = await login_as_admin(client)
    headers = auth_headers(token)

    uploaded = await _upload(client, headers, "guide.md", TOMATO_DOC, "番茄指南")
    assert uploaded.status_code == 200, uploaded.text
    document = data_of(uploaded)
    assert document["status"] == "failed"
    assert "嵌入模型" in (document["errorMessage"] or "")


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
