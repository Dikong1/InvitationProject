import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.inv_templates.models import (
    InvitationTemplate,
    TemplatePreview,
    TemplateRevision,
    TemplateStatus,
)
from app.inv_templates.schemas import (
    TemplatePreviewSnapshotOut,
    TemplatePublicOut,
)
from app.logging_config import get_logger

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])
preview_router = APIRouter(
    prefix="/api/v1/template-previews",
    tags=["template-previews"],
)
logger = get_logger("templates")


def public_template_payload(
    template: InvitationTemplate,
    revision: TemplateRevision,
) -> Dict[str, object]:
    """Build a public response without exposing any draft revision state."""
    return {
        "id": template.id,
        "category_id": template.category_id,
        "name_kk": template.name_kk,
        "name_ru": template.name_ru,
        "description": template.description,
        "preview_url": template.preview_url,
        "thumbnail_url": template.thumbnail_url,
        "images": template.images or [],
        "config": revision.config,
        "is_premium": template.is_premium,
        "is_active": template.is_active,
        "sort_order": template.sort_order,
        "published_revision_id": revision.id,
        "published_revision_number": revision.revision_number,
        "created_at": template.created_at,
        "created_by_id": template.created_by_id,
        "updated_by_id": template.updated_by_id,
    }


@router.get("", response_model=List[TemplatePublicOut])
async def list_templates(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    db: AsyncSession = Depends(get_db),
):
    from app.categories.models import EventCategory

    stmt = (
        select(InvitationTemplate, TemplateRevision)
        .join(
            TemplateRevision,
            TemplateRevision.id == InvitationTemplate.published_revision_id,
        )
        .where(
            InvitationTemplate.status == TemplateStatus.published,
            InvitationTemplate.is_active.is_(True),
            InvitationTemplate.published_revision_id.is_not(None),
        )
    )

    if category:
        category_result = await db.execute(
            select(EventCategory).where(EventCategory.slug == category)
        )
        event_category = category_result.scalar_one_or_none()
        if event_category:
            stmt = stmt.where(
                InvitationTemplate.category_id == event_category.id
            )

    stmt = stmt.order_by(InvitationTemplate.sort_order)
    result = await db.execute(stmt)
    return [
        public_template_payload(template, revision)
        for template, revision in result.all()
    ]


@router.get("/{template_id}", response_model=TemplatePublicOut)
async def get_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InvitationTemplate, TemplateRevision)
        .join(
            TemplateRevision,
            TemplateRevision.id == InvitationTemplate.published_revision_id,
        )
        .where(
            InvitationTemplate.id == template_id,
            InvitationTemplate.status == TemplateStatus.published,
            InvitationTemplate.is_active.is_(True),
            InvitationTemplate.published_revision_id.is_not(None),
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Template not found")
    return public_template_payload(row[0], row[1])


@preview_router.get(
    "/{preview_id}",
    response_model=TemplatePreviewSnapshotOut,
)
async def get_template_preview(
    preview_id: uuid.UUID,
    token: str = Query(..., min_length=20),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(TemplatePreview).where(TemplatePreview.id == preview_id)
    )
    preview = result.scalar_one_or_none()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not preview or not hmac.compare_digest(preview.token_hash, token_hash):
        raise HTTPException(404, "Template preview not found")

    now = datetime.now(timezone.utc)
    if preview.revoked_at is not None or preview.expires_at <= now:
        raise HTTPException(410, "Template preview has expired")

    return {
        "preview_id": preview.id,
        "template_id": preview.template_id,
        "revision_id": preview.revision_id,
        "config": preview.config,
        "locale": preview.locale,
        "sample_data": preview.sample_data,
        "expires_at": preview.expires_at,
    }
