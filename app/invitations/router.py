from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logging_config import get_logger
from app.auth.models import User
from app.auth.config import get_current_user
from app.invitations.models import Invitation, InvitationDetails, InvitationStatus
from app.invitations.schemas import (
    InvitationCreate, InvitationUpdate, InvitationOut, InvitationPublicOut, MediaOutBasic,
)
from app.utils import build_base_slug, make_unique_slug

router = APIRouter(tags=["invitations"])
logger = get_logger("invitations")

EDITABLE_DAYS = 3
PUBLIC_WISHES_LIMIT = 50


async def _get_own_invitation(
    invitation_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
) -> Invitation:
    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == current_user.id,
        )
    )
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Приглашение не найдено")
    return inv


async def _get_details(invitation_id: uuid.UUID, db: AsyncSession) -> Optional[InvitationDetails]:
    result = await db.execute(
        select(InvitationDetails).where(InvitationDetails.invitation_id == invitation_id)
    )
    return result.scalar_one_or_none()


async def _check_slug_unique(slug: str, db: AsyncSession) -> bool:
    result = await db.execute(select(Invitation).where(Invitation.slug == slug))
    return result.scalar_one_or_none() is None


async def _generate_unique_slug(base_slug: str, db: AsyncSession) -> str:
    if await _check_slug_unique(base_slug, db):
        return base_slug
    for _ in range(10):
        candidate = make_unique_slug(base_slug)
        if await _check_slug_unique(candidate, db):
            return candidate
    raise HTTPException(500, "Не удалось сгенерировать уникальный slug")


# ─── My invitations (authenticated) ──────────────────────────────────────────

@router.get("/api/v1/my/invitations", response_model=list[InvitationOut])
async def list_my_invitations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invitation)
        .where(Invitation.user_id == current_user.id)
        .order_by(Invitation.created_at.desc())
    )
    invitations = result.scalars().all()

    # Attach details to each invitation
    out = []
    for inv in invitations:
        details = await _get_details(inv.id, db)
        inv_dict = InvitationOut.model_validate(inv)
        if details:
            inv_dict.details = details
        out.append(inv_dict)
    return out


@router.post("/api/v1/my/invitations", response_model=InvitationOut, status_code=201)
async def create_invitation(
    data: InvitationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Resolve category slug for slug generation
        category_slug = "event"
        if data.category_id:
            from app.categories.models import EventCategory
            cat_result = await db.execute(
                select(EventCategory).where(EventCategory.id == data.category_id)
            )
            cat = cat_result.scalar_one_or_none()
            if cat:
                category_slug = cat.slug

        base_slug = build_base_slug(data.details.organizer_name, category_slug)
        slug = await _generate_unique_slug(base_slug, db)

        now = datetime.now(timezone.utc)
        inv = Invitation(
            user_id=current_user.id,
            template_id=data.template_id,
            category_id=data.category_id,
            slug=slug,
            title=data.title,
            status=InvitationStatus.draft,
            is_paid=False,
            editable_until=now + timedelta(days=EDITABLE_DAYS),
        )
        db.add(inv)
        await db.flush()  # get inv.id before adding details

        details = InvitationDetails(
            invitation_id=inv.id,
            **data.details.model_dump(),
        )
        db.add(details)
        await db.commit()
        await db.refresh(inv)
        await db.refresh(details)

        logger.info(
            "Invitation created: id=%s slug=%s user=%s",
            inv.id, inv.slug, current_user.username,
        )
        result_inv = InvitationOut.model_validate(inv)
        result_inv.details = details
        return result_inv
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Create invitation error for user %s: %s", current_user.username, e)
        raise HTTPException(500, f"Ошибка создания приглашения: {str(e)}")


@router.get("/api/v1/my/invitations/{invitation_id}", response_model=InvitationOut)
async def get_my_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    inv = await _get_own_invitation(invitation_id, current_user, db)
    details = await _get_details(inv.id, db)
    result_inv = InvitationOut.model_validate(inv)
    if details:
        result_inv.details = details
    return result_inv


@router.put("/api/v1/my/invitations/{invitation_id}", response_model=InvitationOut)
async def update_invitation(
    invitation_id: uuid.UUID,
    data: InvitationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        inv = await _get_own_invitation(invitation_id, current_user, db)

        if datetime.now(timezone.utc) > inv.editable_until:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Срок редактирования истёк (3 дня с момента создания)",
            )

        if data.title is not None:
            inv.title = data.title
        if data.category_id is not None:
            inv.category_id = data.category_id
        if data.template_id is not None:
            inv.template_id = data.template_id

        if data.details is not None:
            details = await _get_details(inv.id, db)
            if details:
                for field, value in data.details.model_dump(exclude_none=True).items():
                    setattr(details, field, value)
            else:
                details = InvitationDetails(
                    invitation_id=inv.id,
                    **data.details.model_dump(),
                )
                db.add(details)

        inv.updated_by_id = current_user.id  # audit: track who last edited

        await db.commit()
        await db.refresh(inv)
        logger.info("Invitation updated: id=%s user=%s", inv.id, current_user.username)
        details = await _get_details(inv.id, db)
        result_inv = InvitationOut.model_validate(inv)
        if details:
            result_inv.details = details
        return result_inv
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Update invitation error id=%s: %s", invitation_id, e)
        raise HTTPException(500, f"Ошибка обновления приглашения: {str(e)}")


@router.delete("/api/v1/my/invitations/{invitation_id}", status_code=204)
async def delete_invitation(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        inv = await _get_own_invitation(invitation_id, current_user, db)
        await db.delete(inv)
        await db.commit()
        logger.info("Invitation deleted: id=%s user=%s", invitation_id, current_user.username)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"Ошибка удаления: {str(e)}")


# ─── Public invitation page ───────────────────────────────────────────────────

@router.get("/api/v1/invite/{slug}", response_model=InvitationPublicOut)
async def get_public_invitation(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invitation).where(Invitation.slug == slug))
    inv = result.scalar_one_or_none()

    if not inv:
        raise HTTPException(404, "Приглашение не найдено")

    # Auto-expire check
    now = datetime.now(timezone.utc)
    if inv.expires_at and now > inv.expires_at and inv.status == InvitationStatus.published:
        inv.status = InvitationStatus.expired
        await db.commit()

    if not inv.is_paid or inv.status != InvitationStatus.published:
        raise HTTPException(404, "Приглашение не найдено")

    details = await _get_details(inv.id, db)
    result_inv = InvitationPublicOut.model_validate(inv)
    if details:
        result_inv.details = details

    # Attach media
    from app.media.models import InvitationMedia
    media_result = await db.execute(
        select(InvitationMedia)
        .where(InvitationMedia.invitation_id == inv.id)
        .order_by(InvitationMedia.sort_order)
    )
    result_inv.media = [m for m in media_result.scalars().all()]

    # Attach the host's extra RSVP questions so guests can answer them
    from app.rsvp.models import RSVPQuestion
    questions_result = await db.execute(
        select(RSVPQuestion)
        .where(RSVPQuestion.invitation_id == inv.id)
        .order_by(RSVPQuestion.sort_order)
    )
    result_inv.questions = list(questions_result.scalars().all())

    # Wishes the guest made public and the host approved, newest first
    from app.rsvp.models import RSVPResponse
    wishes_result = await db.execute(
        select(RSVPResponse)
        .where(
            RSVPResponse.invitation_id == inv.id,
            RSVPResponse.wish_public.is_(True),
            RSVPResponse.wish_visible.is_(True),
            RSVPResponse.message.isnot(None),
            RSVPResponse.message != "",
        )
        .order_by(RSVPResponse.responded_at.desc())
        .limit(PUBLIC_WISHES_LIMIT)
    )
    result_inv.wishes = list(wishes_result.scalars().all())

    return result_inv
