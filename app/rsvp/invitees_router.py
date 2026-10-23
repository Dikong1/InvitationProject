from __future__ import annotations

import secrets
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.config import get_current_user
from app.auth.models import User
from app.database import get_db
from app.invitations.utils import get_owned_invitation
from app.logging_config import get_logger
from app.rsvp.models import Invitee, RSVPResponse
from app.rsvp.schemas import InviteeBulkCreate, InviteeOut

router = APIRouter(tags=["rsvp"])
logger = get_logger("invitees")

MAX_INVITEES_PER_INVITATION = 1000


def new_invitee_token() -> str:
    """12 URL-safe characters (72 random bits) for the personal link ?g=..."""
    return secrets.token_urlsafe(9)


@router.get("/api/v1/my/invitations/{invitation_id}/invitees", response_model=List[InviteeOut])
async def list_invitees(
    invitation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Guest list with each guest's personal link token and response status (owner only)."""
    await get_owned_invitation(invitation_id, current_user, db)
    invitees_result = await db.execute(
        select(Invitee)
        .where(Invitee.invitation_id == invitation_id)
        .order_by(Invitee.created_at, Invitee.name)
    )
    invitees = invitees_result.scalars().all()

    responses_result = await db.execute(
        select(RSVPResponse.invitee_id, RSVPResponse.will_attend).where(
            RSVPResponse.invitation_id == invitation_id,
            RSVPResponse.invitee_id.isnot(None),
        )
    )
    attendance = {invitee_id: will_attend for invitee_id, will_attend in responses_result.all()}

    out = []
    for invitee in invitees:
        item = InviteeOut.model_validate(invitee)
        if invitee.id in attendance:
            item.responded = True
            item.will_attend = attendance[invitee.id]
        out.append(item)
    return out


@router.post("/api/v1/my/invitations/{invitation_id}/invitees", response_model=List[InviteeOut], status_code=201)
async def add_invitees(
    invitation_id: uuid.UUID,
    data: InviteeBulkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add up to 200 guests at once; each gets a personal link token."""
    await get_owned_invitation(invitation_id, current_user, db)
    count_result = await db.execute(
        select(func.count(Invitee.id)).where(Invitee.invitation_id == invitation_id)
    )
    existing = count_result.scalar() or 0
    if existing + len(data.invitees) > MAX_INVITEES_PER_INVITATION:
        raise HTTPException(
            400, f"Слишком много гостей: максимум {MAX_INVITEES_PER_INVITATION} на приглашение"
        )

    try:
        invitees = [
            Invitee(
                invitation_id=invitation_id,
                name=item.name,
                phone=item.phone or None,
                token=new_invitee_token(),
            )
            for item in data.invitees
        ]
        db.add_all(invitees)
        await db.commit()
        for invitee in invitees:
            await db.refresh(invitee)
        logger.info(
            "Invitees added: invitation=%s count=%s user=%s",
            invitation_id, len(invitees), current_user.username,
        )
        return [InviteeOut.model_validate(invitee) for invitee in invitees]
    except Exception as e:
        await db.rollback()
        logger.error("Add invitees error for invitation %s: %s", invitation_id, e)
        raise HTTPException(500, f"Ошибка добавления гостей: {str(e)}")


@router.delete("/api/v1/my/invitations/{invitation_id}/invitees/{invitee_id}", status_code=204)
async def delete_invitee(
    invitation_id: uuid.UUID,
    invitee_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a guest from the list. Their RSVP, if any, is kept but unlinked."""
    await get_owned_invitation(invitation_id, current_user, db)
    result = await db.execute(
        select(Invitee).where(
            Invitee.id == invitee_id,
            Invitee.invitation_id == invitation_id,
        )
    )
    invitee = result.scalar_one_or_none()
    if not invitee:
        raise HTTPException(404, "Гость не найден")
    await db.delete(invitee)
    await db.commit()
    logger.info("Invitee deleted: invitation=%s invitee=%s user=%s", invitation_id, invitee_id, current_user.username)
