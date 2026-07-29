import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TemplateStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class InvitationTemplate(Base):
    __tablename__ = "invitation_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("event_categories.id"), nullable=True
    )
    name_kk: Mapped[str] = mapped_column(String(150), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preview_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    images: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    # Retained as a backward-compatible mirror of the latest revision. API reads
    # always select the appropriate revision explicitly.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[TemplateStatus] = mapped_column(
        SAEnum(TemplateStatus, name="templatestatus"),
        default=TemplateStatus.draft,
        nullable=False,
    )
    latest_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    published_revision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    latest_revision_number: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    published_revision_number: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    has_unpublished_changes: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<InvitationTemplate id={self.id} name_ru={self.name_ru}>"


class TemplateRevision(Base):
    __tablename__ = "template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "revision_number",
            name="uq_template_revisions_template_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invitation_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TemplatePreview(Base):
    __tablename__ = "template_previews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invitation_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("template_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    locale: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sample_data: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
