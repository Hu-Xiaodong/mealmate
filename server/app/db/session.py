from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db import (
    models,  # noqa: F401  确保模型注册到 metadata
    rag_models,  # noqa: F401  知识库模型同样需要在建表时注册
)
from app.db.base import Base

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """返回数据库会话工厂，供后台任务自行创建会话。

    为什么需要它：
        接口里的 db 会话在响应返回后就关闭了，后台任务不能继续使用；
        批量导入要逐个文件处理，每个文件都应该是独立会话，单个失败
        才不会影响其他文件。把工厂做成依赖注入后，测试可以替换成
        临时数据库的工厂，后台任务不会误写到开发库。
    """
    return SessionLocal
