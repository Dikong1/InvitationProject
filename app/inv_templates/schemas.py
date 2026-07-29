import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.inv_templates.models import TemplateStatus


class TemplatePublicOut(BaseModel):
    id: uuid.UUID
    category_id: Optional[int] = None
    name_kk: str
    name_ru: str
    description: Optional[str] = None
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    config: Dict[str, Any]
    is_premium: bool
    is_active: bool
    sort_order: int
    published_revision_id: uuid.UUID
    published_revision_number: int
    created_at: datetime
    created_by_id: Optional[int] = None
    updated_by_id: Optional[int] = None

    model_config = {"from_attributes": True}

    @field_validator("images", mode="before")
    @classmethod
    def coerce_images(cls, value: object) -> List[str]:
        return value if value is not None else []


class TemplateAdminOut(TemplatePublicOut):
    status: TemplateStatus
    latest_revision_id: uuid.UUID
    published_revision_id: Optional[uuid.UUID] = None
    latest_revision_number: int
    published_revision_number: Optional[int] = None
    has_unpublished_changes: bool


class TemplateUpdate(BaseModel):
    category_id: Optional[int] = None
    name_kk: Optional[str] = None
    name_ru: Optional[str] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    images: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None
    is_premium: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    base_revision_number: Optional[int] = Field(None, ge=1)

    @field_validator("config", mode="before")
    @classmethod
    def reject_null_config(cls, value: object) -> object:
        if value is None:
            raise ValueError("config must be a JSON object")
        return value


class TemplateRevisionSummary(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    revision_number: int
    created_at: datetime
    created_by_id: Optional[int] = None
    published_at: Optional[datetime] = None
    published_by_id: Optional[int] = None
    is_latest: bool
    is_published: bool


class TemplateRevisionOut(TemplateRevisionSummary):
    config: Dict[str, Any]


class TemplatePreviewCreate(BaseModel):
    config: Optional[Dict[str, Any]] = None
    locale: Optional[str] = Field(None, max_length=20)
    sample_data: Optional[Any] = None

    @field_validator("config", mode="before")
    @classmethod
    def reject_null_config(cls, value: object) -> object:
        if value is None:
            raise ValueError("config must be a JSON object")
        return value


class TemplatePreviewOut(BaseModel):
    preview_id: uuid.UUID
    template_id: uuid.UUID
    revision_id: Optional[uuid.UUID] = None
    preview_url: str
    expires_at: datetime


class TemplatePreviewSnapshotOut(BaseModel):
    preview_id: uuid.UUID
    template_id: uuid.UUID
    revision_id: Optional[uuid.UUID] = None
    config: Dict[str, Any]
    locale: Optional[str] = None
    sample_data: Optional[Any] = None
    expires_at: datetime


# Backward-compatible import name for code outside this module.
TemplateOut = TemplatePublicOut
