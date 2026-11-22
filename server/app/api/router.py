from fastapi import APIRouter

from app.api.routes import (
    ai,
    analytics,
    auth,
    feed,
    interactions,
    maps,
    me,
    media,
    posts,
    rank,
    recipes,
    taste_tags,
)
from app.api.routes.admin import router as admin_router

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(feed.router)
api_router.include_router(posts.router)
api_router.include_router(recipes.router)
api_router.include_router(rank.router)
api_router.include_router(interactions.router)
api_router.include_router(me.router)
api_router.include_router(media.router)
api_router.include_router(maps.router)
api_router.include_router(taste_tags.router)
api_router.include_router(ai.router)
api_router.include_router(analytics.router)
# 管理后台接口统一挂在 /api/v1/admin 下，与普通用户接口共用同一个服务。
api_router.include_router(admin_router)
