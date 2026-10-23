import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logging_config import get_logger
from app.auth.models import User
from app.auth.config import get_current_user
from app.invitations.models import Invitation, InvitationStatus
from app.invitations.utils import get_owned_invitation
from app.rsvp.models import Invitee, RSVPResponse, RSVPQuestion
from app.rsvp.schemas import (
    RSVPResponseCreate, RSVPResponseOut, RSVPResponseUpdate, RSVPSummary,
    RSVPQuestionCreate, RSVPQuestionOut,
)

router = APIRouter(tags=["rsvp"])
logger = get_logger("rsvp")

RATE_LIMIT_PER_HOUR = 5


@router.post("/api/v1/invite/{slug}/rsvp", response_model=RSVPResponseOut)
async def submit_rsvp(
    slug: str,
    data: RSVPResponseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit RSVP response for a published invitation."""
    # Load invitation
    result = await db.execute(select(Invitation).where(Invitation.slug == slug))
    inv = result.scalar_one_or_none()
    if not inv or not inv.is_paid or inv.status != InvitationStatus.published:
        raise HTTPException(404, "Приглашение не найдено")

    ip_address = request.client.host if request.client else None

    # IP-based rate limit (DB query, no Redis needed)
    if ip_address:
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        count_result = await db.execute(
            select(func.count(RSVPResponse.id)).where(
                RSVPResponse.invitation_id == inv.id,
                RSVPResponse.ip_address == ip_address,
                RSVPResponse.responded_at >= one_hour_ago,
            )
        )
        if count_result.scalar() >= RATE_LIMIT_PER_HOUR:
            raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")

    try:
        # Personal link: the guest is on the host's list
        invitee = None
        if data.invitee_token:
            invitee_result = await db.execute(
                select(Invitee).where(
                    Invitee.invitation_id == inv.id,
                    Invitee.token == data.invitee_token,
                )
            )
            invitee = invitee_result.scalar_one_or_none()
            if not invitee:
                logger.warning("RSVP with unknown invitee token: invitation=%s", slug)

        # Deduplication: an invited guest's earlier response first, then the same phone.
        # A phone match never takes over a response linked to a different invitee.
        existing = None
        if invitee:
            existing_result = await db.execute(
                select(RSVPResponse).where(RSVPResponse.invitee_id == invitee.id)
            )
            existing = existing_result.scalar_one_or_none()
        if existing is None and data.guest_phone:
            phone_query = select(RSVPResponse).where(
                RSVPResponse.invitation_id == inv.id,
                RSVPResponse.guest_phone == data.guest_phone,
            )
            if invitee:
                phone_query = phone_query.where(RSVPResponse.invitee_id.is_(None))
            existing_result = await db.execute(
                phone_query.order_by(RSVPResponse.responded_at.desc()).limit(1)
            )
            existing = existing_result.scalar_one_or_none()

        if existing:
            # An edited or withdrawn wish needs the host's approval again
            if existing.message != data.message or not data.wish_public:
                existing.wish_visible = False
            existing.guest_name = data.guest_name
            existing.will_attend = data.will_attend
            existing.guest_count = data.guest_count
            existing.message = data.message
            existing.wish_public = data.wish_public
            existing.answers = data.answers
            if invitee and existing.invitee_id is None:
                existing.invitee_id = invitee.id
            existing.ip_address = ip_address
            existing.responded_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(existing)
            logger.info(
                "RSVP updated: invitation=%s guest=%s phone=%s",
                slug, data.guest_name, data.guest_phone,
            )
            return existing

        response = RSVPResponse(
            invitation_id=inv.id,
            guest_name=data.guest_name,
            guest_phone=data.guest_phone,
            will_attend=data.will_attend,
            guest_count=data.guest_count,
            message=data.message,
            answers=data.answers,
            wish_public=data.wish_public,
            wish_visible=False,
            invitee_id=invitee.id if invitee else None,
            ip_address=ip_address,
        )
        db.add(response)
        await db.commit()
        await db.refresh(response)
        logger.info(
            "RSVP submitted: invitation=%s guest=%s attend=%s",
            slug, data.guest_name, data.will_attend,
        )
        return response
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("RSVP error for invitation %s: %s", slug, e)
        raise HTTPException(500, f"Ошибка отправки RSVP: {str(e)}")


@router.get("/api/v1/my/invitations/{invitation_id}/guests", response_model=RSVPSummary)
async def get_guests(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all RSVP responses for an invitation (owner only)."""
    inv_result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == current_user.id,
        )
    )
    if not inv_result.scalar_one_or_none():
        raise HTTPException(404, "Приглашение не найдено")

    responses_result = await db.execute(
        select(RSVPResponse)
        .where(RSVPResponse.invitation_id == invitation_id)
        .order_by(RSVPResponse.responded_at.desc())
    )
    responses = responses_result.scalars().all()

    attending = [r for r in responses if r.will_attend]
    not_attending = [r for r in responses if not r.will_attend]
    total_guests = sum(r.guest_count for r in attending)

    invited_result = await db.execute(
        select(func.count(Invitee.id)).where(Invitee.invitation_id == invitation_id)
    )
    invited_count = invited_result.scalar() or 0
    responded_invitees = sum(1 for r in responses if r.invitee_id is not None)

    return RSVPSummary(
        total_responses=len(responses),
        attending=len(attending),
        not_attending=len(not_attending),
        total_guests=total_guests,
        invited_count=invited_count,
        pending=max(invited_count - responded_invitees, 0),
        responses=responses,
    )


@router.patch("/api/v1/my/invitations/{invitation_id}/guests/{response_id}", response_model=RSVPResponseOut)
async def update_guest_response(
    invitation_id: uuid.UUID,
    response_id: uuid.UUID,
    data: RSVPResponseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve or hide a guest's wish on the public wishes wall (owner only)."""
    await get_owned_invitation(invitation_id, current_user, db)
    result = await db.execute(
        select(RSVPResponse).where(
            RSVPResponse.id == response_id,
            RSVPResponse.invitation_id == invitation_id,
        )
    )
    response = result.scalar_one_or_none()
    if not response:
        raise HTTPException(404, "Ответ не найден")
    if data.wish_visible and not (response.wish_public and response.message):
        raise HTTPException(400, "Гость не разрешил показывать это сообщение")

    response.wish_visible = data.wish_visible
    await db.commit()
    await db.refresh(response)
    logger.info(
        "Wish %s: invitation=%s response=%s user=%s",
        "approved" if data.wish_visible else "hidden", invitation_id, response_id, current_user.username,
    )
    return response


@router.get("/api/v1/my/invitations/{invitation_id}/questions", response_model=list[RSVPQuestionOut])
async def list_rsvp_questions(
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
        select(RSVPQuestion)
        .where(RSVPQuestion.invitation_id == invitation_id)
        .order_by(RSVPQuestion.sort_order)
    )
    return result.scalars().all()


@router.post("/api/v1/my/invitations/{invitation_id}/questions", response_model=RSVPQuestionOut, status_code=201)
async def add_rsvp_question(
    invitation_id: uuid.UUID,
    data: RSVPQuestionCreate,
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

    question = RSVPQuestion(invitation_id=invitation_id, **data.model_dump())
    db.add(question)
    await db.commit()
    await db.refresh(question)
    logger.info("RSVP question added: invitation=%s", invitation_id)
    return question


@router.delete("/api/v1/my/invitations/{invitation_id}/questions/{question_id}", status_code=204)
async def delete_rsvp_question(
    invitation_id: uuid.UUID,
    question_id: uuid.UUID,
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

    q_result = await db.execute(
        select(RSVPQuestion).where(
            RSVPQuestion.id == question_id,
            RSVPQuestion.invitation_id == invitation_id,
        )
    )
    q = q_result.scalar_one_or_none()
    if not q:
        raise HTTPException(404, "Вопрос не найден")

    await db.delete(q)
    await db.commit()
