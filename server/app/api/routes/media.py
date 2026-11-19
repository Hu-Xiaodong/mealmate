from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.serializers import media_url
from app.core.responses import ok
from app.db.models import User
from app.db.session import get_db
from app.services.media_service import save_upload

router = APIRouter(prefix="/media", tags=["media"])


@router.post("")
async def upload_media(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    asset = await save_upload(db, user.id, file)
    return ok(
        {
            "assetId": asset.id,
            "url": media_url(asset.storage_key),
            "thumbUrl": media_url(asset.thumb_key),
            "width": asset.width,
            "height": asset.height,
        }
    )
