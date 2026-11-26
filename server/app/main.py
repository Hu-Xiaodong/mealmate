"""FastAPI 应用入口。"""

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers, request_id_ctx
from app.core.responses import ok
from app.db.seed import seed_admin_data, seed_demo_data, seed_taste_tags
from app.db.session import SessionLocal, init_db
from app.services import langfuse_service
from app.services.cache import close_cache

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("mealmate")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.media_root).mkdir(parents=True, exist_ok=True)
    await init_db()
    # 口味标签字典是页面的基础数据，必须无条件补齐：
    # 它不依赖演示数据开关，生产环境第一次启动也需要这 9 个默认标签。
    async with SessionLocal() as db:
        await seed_taste_tags(db)
    if settings.seed_demo_data and settings.app_env != "prod":
        async with SessionLocal() as db:
            await seed_demo_data(db)
    # 后台角色与首个管理员需要独立初始化：
    # 即使演示数据已经存在，也要补齐新增的角色和权限点。
    async with SessionLocal() as db:
        await seed_admin_data(db)
    # Langfuse 未配置时 start_worker 直接返回，不会产生任何后台任务。
    # 配置后由后台协程批量上报模型调用，避免拖慢用户请求。
    langfuse_service.start_worker()
    logger.info("应用启动完成 env=%s", settings.app_env)
    yield
    await langfuse_service.stop_worker()
    await close_cache()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "prod" else "/docs",
    redoc_url=None,
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    incoming = (request.headers.get("x-request-id") or "").strip()
    request_id = incoming[:64] if incoming else f"req_{secrets.token_hex(8)}"
    token = request_id_ctx.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Device-Id",
        "X-Request-Id",
    ],
    expose_headers=["X-Request-Id", "Retry-After"],
)

Path(settings.media_root).mkdir(parents=True, exist_ok=True)
if settings.media_backend == "local":
    # 仅本地存储需要静态挂载；迁移到对象存储后由云服务直接提供访问地址。
    app.mount("/media", StaticFiles(directory=str(settings.media_root)), name="media")

register_error_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/healthz", tags=["system"])
async def healthz() -> dict:
    return ok({"status": "ok", "env": settings.app_env})
