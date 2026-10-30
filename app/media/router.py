import io
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.auth.models import User
from app.auth.config import get_current_user
from app.invitations.models import Invitation
from app.media.models import InvitationMedia, MediaType, DisplayStyle
from app.media.schemas import MediaOut
from app.storage import get_storage

router = APIRouter(tags=["media"])
logger = get_logger("media")

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024


async def _count_media(invitation_id: uuid.UUID, db: AsyncSession) -> int:
    from sqlalchemy import func
    result = await db.execute(
        select(func.count(InvitationMedia.id)).where(
            InvitationMedia.invitation_id == invitation_id
        )
    )
    return result.scalar() or 0


def _make_thumbnail(contents: bytes) -> Optional[bytes]:
    """A 300x300 thumbnail in the original format, or None if Pillow cannot read the image."""
    try:
        from PIL import Image  # type: ignore
        with Image.open(io.BytesIO(contents)) as img:
            fmt = img.format or "JPEG"
            img.thumbnail((300, 300))
            out = io.BytesIO()
            img.save(out, format=fmt, optimize=True, quality=85)
        return out.getvalue()
    except Exception:
        return None


@router.post("/api/v1/my/invitations/{invitation_id}/media", response_model=MediaOut, status_code=201)
async def upload_media(
    invitation_id: uuid.UUID,
    file: UploadFile = File(...),
    media_type: MediaType = Form(MediaType.photo),
    display_style: DisplayStyle = Form(DisplayStyle.rectangle),
    caption: Optional[str] = Form(None),
    sort_order: int = Form(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    inv_result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == current_user.id,
        )
    )
    inv = inv_result.scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Приглашение не найдено")

    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Допустимые форматы: {', '.join(ALLOWED_CONTENT_TYPES)}")

    # Read and check size
    contents = await file.read()
    if len(contents) > MAX_FILE_BYTES:
        raise HTTPException(400, f"Файл слишком большой. Максимум {settings.MAX_FILE_SIZE_MB} МБ")

    # Check photo limit against payment plan (if paid)
    if inv.is_paid:
        from app.payments.models import Payment, PaymentStatus, PaymentPlan
        pay_result = await db.execute(
            select(Payment).where(
                Payment.invitation_id == invitation_id,
                Payment.status == PaymentStatus.success,
            )
        )
        payment = pay_result.scalar_one_or_none()
        if payment and payment.plan_id:
            plan_result = await db.execute(
                select(PaymentPlan).where(PaymentPlan.id == payment.plan_id)
            )
            plan = plan_result.scalar_one_or_none()
            if plan:
                current_count = await _count_media(invitation_id, db)
                if current_count >= plan.max_photos:
                    raise HTTPException(400, f"Лимит фотографий по тарифу: {plan.max_photos}")

    try:
        ext = Path(file.filename or "image.jpg").suffix.lower() or ".jpg"
        file_uuid = str(uuid.uuid4())
        filename = f"{file_uuid}{ext}"

        storage = get_storage()
        content_type = file.content_type or "application/octet-stream"
        relative_url = await storage.save(f"uploads/{invitation_id}/{filename}", contents, content_type)

        thumbnail = _make_thumbnail(contents)
        thumb_url = (
            await storage.save(f"thumbs/{invitation_id}/{filename}", thumbnail, content_type)
            if thumbnail
            else relative_url
        )

        media = InvitationMedia(
            invitation_id=invitation_id,
            media_type=media_type,
            url=relative_url,
            thumbnail_url=thumb_url,
            caption=caption,
            display_style=display_style,
            sort_order=sort_order,
        )
        db.add(media)
        await db.commit()
        await db.refresh(media)

        logger.info(
            "Media uploaded: invitation=%s file=%s type=%s user=%s",
            invitation_id, filename, media_type, current_user.username,
        )
        return media
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Media upload error for invitation %s: %s", invitation_id, e)
        raise HTTPException(500, f"Ошибка загрузки файла: {str(e)}")


@router.get("/api/v1/my/invitations/{invitation_id}/media", response_model=list[MediaOut])
async def list_media(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    inv_result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == current_user.id,
        )
    )
    if not inv_result.scalar_one_or_none():
        raise HTTPException(404, "Приглашение не найдено")

    result = await db.execute(
        select(InvitationMedia)
        .where(InvitationMedia.invitation_id == invitation_id)
        .order_by(InvitationMedia.sort_order)
    )
    return result.scalars().all()


@router.delete("/api/v1/my/invitations/{invitation_id}/media/{media_id}", status_code=204)
async def delete_media(
    invitation_id: uuid.UUID,
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    inv_result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == current_user.id,
        )
    )
    if not inv_result.scalar_one_or_none():
        raise HTTPException(404, "Приглашение не найдено")

    m_result = await db.execute(
        select(InvitationMedia).where(
            InvitationMedia.id == media_id,
            InvitationMedia.invitation_id == invitation_id,
        )
    )
    media = m_result.scalar_one_or_none()
    if not media:
        raise HTTPException(404, "Файл не найден")

    # Delete the stored files
    try:
        storage = get_storage()
        for url in {media.url, media.thumbnail_url}:
            await storage.delete(url)
    except Exception as e:
        logger.warning("Could not delete media files: %s", e)

    await db.delete(media)
    await db.commit()
    logger.info(
        "Media deleted: id=%s invitation=%s user=%s",
        media_id, invitation_id, current_user.username,
    )
