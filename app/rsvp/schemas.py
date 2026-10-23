import uuid
from datetime import datetime
from typing import List, Optional, Any
from pydantic import BaseModel, Field

from app.rsvp.models import QuestionType


class RSVPQuestionOut(BaseModel):
    id: uuid.UUID
    invitation_id: uuid.UUID
    question_text_kk: str
    question_text_ru: str
    question_type: QuestionType
    options: Optional[dict] = None
    is_required: bool
    sort_order: int

    model_config = {"from_attributes": True}


class RSVPQuestionCreate(BaseModel):
    question_text_kk: str
    question_text_ru: str
    question_type: QuestionType = QuestionType.text
    options: Optional[dict] = None
    is_required: bool = False
    sort_order: int = 0


class RSVPResponseCreate(BaseModel):
    # Limits match the column sizes; guest_count is 0 when the guest declines
    guest_name: str = Field(min_length=1, max_length=255)
    guest_phone: Optional[str] = Field(default=None, max_length=20)
    will_attend: bool
    guest_count: int = Field(default=1, ge=0, le=20)
    message: Optional[str] = Field(default=None, max_length=1000)
    answers: Optional[dict] = None
    wish_public: bool = False  # Гость разрешает показать сообщение на странице (после одобрения организатором)
    invitee_token: Optional[str] = Field(default=None, max_length=32)  # Токен персональной ссылки (?g=...), если гость пришёл по ней

    model_config = {"str_strip_whitespace": True}


class RSVPResponseOut(BaseModel):
    id: uuid.UUID
    invitation_id: uuid.UUID
    guest_name: str
    guest_phone: Optional[str] = None
    will_attend: bool
    guest_count: int
    message: Optional[str] = None
    answers: Optional[dict] = None
    wish_public: bool = False
    wish_visible: bool = False
    invitee_id: Optional[uuid.UUID] = None
    responded_at: datetime

    model_config = {"from_attributes": True}


class RSVPResponseUpdate(BaseModel):
    """Owner moderation of a guest's response."""
    wish_visible: bool


class WishOut(BaseModel):
    """A guest's message approved for the public wishes wall."""
    id: uuid.UUID
    guest_name: str
    message: str
    responded_at: datetime

    model_config = {"from_attributes": True}


class RSVPSummary(BaseModel):
    total_responses: int
    attending: int
    not_attending: int
    total_guests: int
    invited_count: int = 0  # Размер списка гостей; 0 — список не используется
    pending: int = 0  # Приглашённые гости, которые ещё не ответили
    responses: list[RSVPResponseOut]


# ─── Invited guests ───────────────────────────────────────────────────────────

class InviteeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)

    model_config = {"str_strip_whitespace": True}


class InviteeBulkCreate(BaseModel):
    invitees: List[InviteeCreate] = Field(min_length=1, max_length=200)


class InviteeOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: Optional[str] = None
    token: str
    created_at: datetime
    responded: bool = False
    will_attend: Optional[bool] = None

    model_config = {"from_attributes": True}


class InviteeGreeting(BaseModel):
    """What the public page learns from a personal link: only the guest's name."""
    name: str

    model_config = {"from_attributes": True}
