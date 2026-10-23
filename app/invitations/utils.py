import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.invitations.models import Invitation


async def get_owned_invitation(invitation_id: uuid.UUID, user: User, db: AsyncSession) -> Invitation:
    """Load an invitation owned by `user`, or raise 404 (also for other users' invitations)."""
    result = await db.execute(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.user_id == user.id,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(404, "Приглашение не найдено")
    return invitation
