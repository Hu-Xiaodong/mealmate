"""后台路由集合。

所有接口统一挂在 /api/v1/admin 下，与面向用户的接口共用同一个 FastAPI 服务。
不单独拆服务是因为当前规模不需要微服务，拆开只会增加部署和联调成本。
"""

from fastapi import APIRouter

from app.api.routes.admin import (
    admins,
    ai_metrics,
    ai_providers,
    audit,
    auth,
    dashboard,
    kb,
    langfuse,
    posts,
    prompt_variables,
    prompts,
    recipes,
    taste_tags,
    users,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(posts.router)
router.include_router(recipes.router)
router.include_router(taste_tags.router)
router.include_router(users.router)
router.include_router(admins.router)
router.include_router(audit.router)
router.include_router(ai_providers.router)
router.include_router(ai_providers.logs_router)
# 本地指标与提示词版本：不依赖 Langfuse。
router.include_router(ai_metrics.router)
router.include_router(prompts.router)
# 提示词变量：共用变量与专属变量。
router.include_router(prompt_variables.router)
# Langfuse 观测：连接状态与可选的第二数据源。
router.include_router(langfuse.router)
# 知识库：文档管理、索引版本与检索测试。
router.include_router(kb.router)
