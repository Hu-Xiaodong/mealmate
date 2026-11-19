"""测试环境：每个用例独立 SQLite 文件，复用同一 FastAPI 应用。"""

import os
import tempfile
from pathlib import Path

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_placeholder.db"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ALLOW_DEV_AUTH_CODE"] = "true"
os.environ["DEV_AUTH_CODE"] = "123456"
os.environ["AI_PROVIDER"] = "mock"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["RANK_CACHE_SECONDS"] = "10"
os.environ["MEDIA_ROOT"] = Path(tempfile.mkdtemp(prefix="mealmate-media-")).as_posix()
# 测试固定一个管理员初始密码，登录用例不依赖本机 .env。
os.environ["ADMIN_INITIAL_USERNAME"] = "admin"
os.environ["ADMIN_INITIAL_PASSWORD"] = "Admin@123456"

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from app.db.seed import seed_admin_data, seed_demo_data
from app.db.session import get_db
from app.main import app

API = "/api/v1"


@pytest.fixture
async def client():
    workdir = Path(tempfile.mkdtemp(prefix="mealmate-test-"))
    db_path = workdir / "mealmate_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}", poolclass=NullPool
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as db:
        await seed_demo_data(db)
        await seed_admin_data(db)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    # 用例需要直接造数据时可以通过 app.state 取到同一个会话工厂。
    app.state.test_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test.local") as http:
        yield http

    app.dependency_overrides.clear()
    app.state.test_session_factory = None
    await engine.dispose()


def data_of(response: httpx.Response) -> dict:
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]


async def login(client: httpx.AsyncClient, phone: str = "13800000001") -> dict:
    sent = await client.post(f"{API}/auth/sms-codes", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    challenge = data_of(sent)
    code = challenge.get("devCode", "123456")
    logged = await client.post(
        f"{API}/auth/login",
        json={
            "challengeId": challenge["challengeId"],
            "code": code,
            "agreementAccepted": True,
        },
    )
    assert logged.status_code == 200, logged.text
    return data_of(logged)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
