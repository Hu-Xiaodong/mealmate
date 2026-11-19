"""后台路由集合。

所有接口统一挂在 /api/v1/admin 下，与面向用户的接口共用同一个 FastAPI 服务。
不单独拆服务是因为当前规模不需要微服务，拆开只会增加部署和联调成本。
"""

from fastapi import APIRouter

from app.api.routes.admin import audit, auth, posts, users

router = APIRouter()
router.include_router(auth.router)
router.include_router(posts.router)
router.include_router(users.router)
router.include_router(audit.router)
