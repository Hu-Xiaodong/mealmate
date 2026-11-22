"""口味标签字典维护。

标签是运营数据：新增、排序、启停、删除都在后台完成，
普通用户端只读取启用中的标签。
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import iso
from app.core.errors import AppError
from app.db.models import AdminUser, MealPost, TasteTag
from app.schemas import TasteTagCreateRequest, TasteTagUpdateRequest
from app.services.audit_service import write_audit
from app.utils.time import now_utc


def _payload(tag: TasteTag) -> dict[str, Any]:
    return {
        "name": tag.name,
        "sortOrder": tag.sort_order,
        "enabled": tag.enabled,
        "createdAt": iso(tag.created_at),
    }


def _snapshot(tag: TasteTag) -> dict[str, Any]:
    return {"name": tag.name, "sortOrder": tag.sort_order, "enabled": tag.enabled}


async def count_tag_usage(db: AsyncSession, name: str) -> int:
    """统计有多少饭帖使用了该标签。

    taste_tags 在饭帖里是 JSON 数组，跨数据库的 JSON 查询语法不一致，
    当前数据量小，直接取出非空数组在 Python 中统计；
    数据量变大后应改成独立的标签关联表。
    """
    rows = (
        await db.scalars(select(MealPost.taste_tags).where(MealPost.taste_tags.is_not(None)))
    ).all()
    return sum(1 for tags in rows if name in (tags or []))


async def list_tags(db: AsyncSession) -> dict[str, Any]:
    """后台列表包含停用标签，运营需要看到完整字典。

    使用量只扫描一次饭帖标签，避免每个标签都查一遍数据库。
    """
    rows = (
        await db.scalars(select(TasteTag).order_by(TasteTag.sort_order, TasteTag.name))
    ).all()
    post_tag_rows = (
        await db.scalars(select(MealPost.taste_tags).where(MealPost.taste_tags.is_not(None)))
    ).all()
    counter: dict[str, int] = {}
    for tags in post_tag_rows:
        for tag_name in tags or []:
            counter[tag_name] = counter.get(tag_name, 0) + 1

    items = []
    for tag in rows:
        payload = _payload(tag)
        payload["usageCount"] = counter.get(tag.name, 0)
        items.append(payload)
    return {"items": items}


async def create_tag(
    db: AsyncSession,
    admin: AdminUser,
    body: TasteTagCreateRequest,
    ip: str | None,
) -> dict[str, Any]:
    if await db.get(TasteTag, body.name) is not None:
        raise AppError("TASTE_TAG_EXISTS", "该口味标签已存在", status_code=409)
    tag = TasteTag(
        name=body.name,
        sort_order=body.sort_order,
        enabled=body.enabled,
        created_at=now_utc(),
    )
    db.add(tag)
    write_audit(
        db,
        actor=admin,
        action="taste_tag.create",
        target_type="taste_tag",
        target_id=tag.name,
        after=_snapshot(tag),
        ip=ip,
    )
    await db.commit()
    payload = _payload(tag)
    payload["usageCount"] = 0
    return payload


async def update_tag(
    db: AsyncSession,
    admin: AdminUser,
    name: str,
    body: TasteTagUpdateRequest,
    ip: str | None,
) -> dict[str, Any]:
    tag = await db.get(TasteTag, name)
    if tag is None:
        raise AppError("TASTE_TAG_NOT_FOUND", "口味标签不存在", status_code=404)
    before = _snapshot(tag)
    if body.sort_order is not None:
        tag.sort_order = body.sort_order
    if body.enabled is not None:
        tag.enabled = body.enabled
    write_audit(
        db,
        actor=admin,
        action="taste_tag.update",
        target_type="taste_tag",
        target_id=tag.name,
        before=before,
        after=_snapshot(tag),
        ip=ip,
    )
    await db.commit()
    payload = _payload(tag)
    payload["usageCount"] = await count_tag_usage(db, tag.name)
    return payload


async def delete_tag(
    db: AsyncSession, admin: AdminUser, name: str, ip: str | None
) -> dict[str, Any]:
    """删除从未被使用的标签。

    已被饭帖引用的标签不允许删除，只能停用：
    否则历史饭帖会出现“用户选过、字典里却查不到”的孤儿标签。
    """
    tag = await db.get(TasteTag, name)
    if tag is None:
        raise AppError("TASTE_TAG_NOT_FOUND", "口味标签不存在", status_code=404)
    usage = await count_tag_usage(db, name)
    if usage > 0:
        raise AppError(
            "TASTE_TAG_IN_USE",
            f"该标签已被 {usage} 条饭帖使用，请改为停用",
            status_code=409,
            data={"usageCount": usage},
        )
    before = _snapshot(tag)
    await db.execute(delete(TasteTag).where(TasteTag.name == name))
    write_audit(
        db,
        actor=admin,
        action="taste_tag.delete",
        target_type="taste_tag",
        target_id=name,
        before=before,
        ip=ip,
    )
    await db.commit()
    return {"name": name, "deleted": True}
