import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel

from app.invitations.models import InvitationStatus
from app.rsvp.schemas import RSVPQuestionOut


# ─── InvitationDetails ────────────────────────────────────────────────────────

class InvitationDetailsBase(BaseModel):
    organizer_name: str
    honoree_name: Optional[str] = None
    invitation_text: Optional[str] = None
    event_description: Optional[str] = None
    event_date: date
    event_time: Optional[str] = None
    event_end_time: Optional[str] = None
    dress_code: Optional[str] = None
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    venue_lat: Optional[Decimal] = None
    venue_lng: Optional[Decimal] = None
    venue_map_url: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_name: Optional[str] = None
    additional_info: Optional[str] = None
    custom_fields: Optional[dict] = None


class InvitationDetailsOut(InvitationDetailsBase):
    id: uuid.UUID
    invitation_id: uuid.UUID

    model_config = {"from_attributes": True}


# ─── Invitation ───────────────────────────────────────────────────────────────

class InvitationCreate(BaseModel):
    title: str
    category_id: Optional[int] = None
    template_id: Optional[uuid.UUID] = None
    details: InvitationDetailsBase


class InvitationUpdate(BaseModel):
    title: Optional[str] = None
    category_id: Optional[int] = None
    template_id: Optional[uuid.UUID] = None
    details: Optional[InvitationDetailsBase] = None


class InvitationOut(BaseModel):
    id: uuid.UUID
    user_id: int
    template_id: Optional[uuid.UUID] = None
    category_id: Optional[int] = None
    slug: str
    title: str
    status: InvitationStatus
    is_paid: bool
    editable_until: datetime
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Audit
    updated_by_id: Optional[int] = None
    details: Optional[InvitationDetailsOut] = None

    model_config = {"from_attributes": True}


class MediaOutBasic(BaseModel):
    id: uuid.UUID
    media_type: str
    url: str
    thumbnail_url: Optional[str] = None
    caption: Optional[str] = None
    display_style: str
    sort_order: int

    model_config = {"from_attributes": True}


class InvitationPublicOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    category_id: Optional[int] = None
    template_id: Optional[uuid.UUID] = None
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    details: Optional[InvitationDetailsOut] = None
    media: list[MediaOutBasic] = []
    questions: List[RSVPQuestionOut] = []  # Дополнительные RSVP-вопросы организатора

    model_config = {"from_attributes": True}
