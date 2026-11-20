"""口味标签字典接口。

前端不再自己写死口味选项，而是启动发布页时调用这个接口拿字典。
这样产品增减口味、调整展示顺序，只改数据库即可，不需要发客户端新版本。

为什么放在独立的 /taste-tags 而不是塞进 /posts：
它属于基础字典数据，不依赖具体饭帖，也不要求登录；
以后其他页面（例如筛选、搜索）也可能使用，独立出来更容易复用和缓存。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import ok
from app.db.models import TasteTag
from app.db.session import get_db

router = APIRouter(tags=["taste-tags"])


@router.get("/taste-tags")
async def list_taste_tags(db: AsyncSession = Depends(get_db)):
    """返回所有“已启用”的口味标签，按展示顺序排列。

    只返回启用中的标签：停用的标签不下发给前端，用户就不会再选到它。
    历史饭帖里的旧标签不受影响，详情页仍然原样展示。
    """
    rows = (
        await db.scalars(
            select(TasteTag)
            .where(TasteTag.enabled.is_(True))
            .order_by(TasteTag.sort_order, TasteTag.name)
        )
    ).all()
    return ok(
        {
            "items": [
                {"name": row.name, "sortOrder": row.sort_order} for row in rows
            ]
        }
    )
