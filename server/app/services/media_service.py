"""本地媒体存储与图片处理。

生产可替换为 OSS/COS 适配器，但校验逻辑（真实类型、大小、像素、去元信息）必须保留。
"""

import io

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import new_id
from app.db.models import MediaAsset
from app.services.storage import get_storage

MAX_BYTES = 5 * 1024 * 1024
THUMB_SIZE = 320
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


async def save_upload(db: AsyncSession, owner_id: str, upload: UploadFile) -> MediaAsset:
    raw = await upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AppError("FILE_TOO_LARGE", "单张图片不能超过 5MB", status_code=413)
    if not raw:
        raise AppError("FILE_EMPTY", "图片内容为空")

    try:
        image = Image.open(io.BytesIO(raw))
        image.verify()
        image = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError("FILE_INVALID", "文件不是可识别的图片") from exc

    if image.format not in ALLOWED_FORMATS:
        raise AppError("FILE_TYPE_UNSUPPORTED", "仅支持 JPG、PNG、WebP 图片")

    width, height = image.size
    if width < 200 or height < 200:
        raise AppError("IMAGE_TOO_SMALL", "图片尺寸过小，至少 200×200")

    asset_id = new_id("m")
    normalized = _normalize(image)
    original_key = f"uploads/{asset_id}.jpg"
    thumb_key = f"uploads/{asset_id}_thumb.jpg"

    storage = get_storage()
    original_buffer = io.BytesIO()
    normalized.save(original_buffer, "JPEG", quality=86, optimize=True)
    original_bytes = original_buffer.getvalue()
    storage.put(original_key, original_bytes)

    thumb_buffer = io.BytesIO()
    _make_thumb(normalized).save(thumb_buffer, "JPEG", quality=80, optimize=True)
    storage.put(thumb_key, thumb_buffer.getvalue())

    asset = MediaAsset(
        id=asset_id,
        owner_id=owner_id,
        mime="image/jpeg",
        bytes=len(original_bytes),
        width=normalized.width,
        height=normalized.height,
        storage_key=original_key,
        thumb_key=thumb_key,
        status="ready",
    )
    db.add(asset)
    await db.commit()

    return asset


def _normalize(image: Image.Image) -> Image.Image:
    # 重新编码会移除 EXIF 中的定位等元信息，并统一方向。
    fixed = ImageOps.exif_transpose(image).convert("RGB")
    max_side = 1600
    if max(fixed.size) > max_side:
        fixed.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return fixed


def _make_thumb(image: Image.Image) -> Image.Image:
    return ImageOps.fit(
        image, (THUMB_SIZE, THUMB_SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
    )
