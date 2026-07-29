import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.router import _validate_and_save_upload
from app.auth.config import get_current_admin_user
from app.auth.models import User
from app.config import settings
from app.database import get_db
from app.invitations.models import Invitation
from app.inv_templates.models import (
    InvitationTemplate,
    TemplatePreview,
    TemplateRevision,
    TemplateStatus,
)
from app.inv_templates.schemas import (
    TemplateAdminOut,
    TemplatePreviewCreate,
    TemplatePreviewOut,
    TemplateRevisionOut,
    TemplateRevisionSummary,
    TemplateUpdate,
)
from app.logging_config import get_logger

router = APIRouter(prefix="/api/v1/admin/templates", tags=["admin-templates"])
logger = get_logger("admin_templates")


def _parse_template_config(config: Optional[str]) -> dict:
    if not config:
        return {}
    try:
        parsed = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(422, "config must be valid JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(422, "config must be a JSON object")
    return parsed


def _revision_payload(
    revision: TemplateRevision,
    template: InvitationTemplate,
    include_config: bool = False,
) -> dict:
    payload = {
        "id": revision.id,
        "template_id": revision.template_id,
        "revision_number": revision.revision_number,
        "created_at": revision.created_at,
        "created_by_id": revision.created_by_id,
        "published_at": revision.published_at,
        "published_by_id": revision.published_by_id,
        "is_latest": revision.id == template.latest_revision_id,
        "is_published": revision.id == template.published_revision_id,
    }
    if include_config:
        payload["config"] = revision.config
    return payload


def _preview_source(
    data: TemplatePreviewCreate,
    template: InvitationTemplate,
) -> Tuple[dict, Optional[uuid.UUID]]:
    uses_unsaved_config = "config" in data.model_fields_set
    if uses_unsaved_config:
        assert data.config is not None
        return data.config, None
    return template.config, template.latest_revision_id


async def _get_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    for_update: bool = False,
) -> InvitationTemplate:
    stmt = select(InvitationTemplate).where(
        InvitationTemplate.id == template_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(404, "Template not found")
    return template


@router.get("", response_model=List[TemplateAdminOut])
async def list_admin_templates(
    template_status: Optional[TemplateStatus] = Query(None, alias="status"),
    category_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, max_length=150),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(InvitationTemplate)
    if template_status is not None:
        stmt = stmt.where(InvitationTemplate.status == template_status)
    if category_id is not None:
        stmt = stmt.where(InvitationTemplate.category_id == category_id)
    if is_active is not None:
        stmt = stmt.where(InvitationTemplate.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                InvitationTemplate.name_kk.ilike(pattern),
                InvitationTemplate.name_ru.ilike(pattern),
            )
        )
    stmt = (
        stmt.order_by(
            InvitationTemplate.sort_order.asc(),
            InvitationTemplate.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{template_id}", response_model=TemplateAdminOut)
async def get_admin_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_template(db, template_id)


@router.post("", response_model=TemplateAdminOut, status_code=201)
async def create_template(
    name_kk: str = Form(...),
    name_ru: str = Form(...),
    category_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    config: Optional[str] = Form(None),
    is_premium: bool = Form(False),
    is_active: bool = Form(True),
    sort_order: int = Form(0),
    preview: Optional[UploadFile] = File(None),
    thumbnail: Optional[UploadFile] = File(None),
    images: Optional[List[UploadFile]] = File(None),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    parsed_config = _parse_template_config(config)
    preview_url = (
        await _validate_and_save_upload(preview)
        if preview and preview.filename
        else None
    )
    thumbnail_url = (
        await _validate_and_save_upload(thumbnail)
        if thumbnail and thumbnail.filename
        else None
    )
    image_urls = [
        await _validate_and_save_upload(image)
        for image in (images or [])
        if image.filename
    ]

    template_id = uuid.uuid4()
    revision_id = uuid.uuid4()
    template = InvitationTemplate(
        id=template_id,
        category_id=category_id,
        name_kk=name_kk,
        name_ru=name_ru,
        description=description,
        preview_url=preview_url,
        thumbnail_url=thumbnail_url,
        images=image_urls,
        config=parsed_config,
        is_premium=is_premium,
        is_active=is_active,
        sort_order=sort_order,
        status=TemplateStatus.draft,
        latest_revision_id=revision_id,
        published_revision_id=None,
        latest_revision_number=1,
        published_revision_number=None,
        has_unpublished_changes=False,
        created_by_id=admin.id,
        updated_by_id=admin.id,
    )
    revision = TemplateRevision(
        id=revision_id,
        template_id=template_id,
        revision_number=1,
        config=parsed_config,
        created_by_id=admin.id,
    )
    db.add_all([template, revision])
    await db.commit()
    await db.refresh(template)
    logger.info("Template created: id=%s admin=%s", template.id, admin.username)
    return template


@router.put("/{template_id}", response_model=TemplateAdminOut)
async def update_template(
    template_id: uuid.UUID,
    data: TemplateUpdate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id, for_update=True)
    if template.status == TemplateStatus.archived:
        raise HTTPException(409, "Restore the archived template before editing it")

    if (
        data.base_revision_number is not None
        and data.base_revision_number != template.latest_revision_number
    ):
        raise HTTPException(
            409,
            detail={
                "message": "Template revision is stale",
                "current_revision_number": template.latest_revision_number,
            },
        )

    fields_set = data.model_fields_set
    for field in (
        "category_id",
        "name_kk",
        "name_ru",
        "description",
        "preview_url",
        "thumbnail_url",
        "images",
        "is_premium",
        "is_active",
        "sort_order",
    ):
        if field in fields_set:
            value = getattr(data, field)
            if field in {"name_kk", "name_ru"} and value is None:
                raise HTTPException(422, f"{field} cannot be null")
            setattr(template, field, value)

    if "config" in fields_set and data.config != template.config:
        revision_id = uuid.uuid4()
        revision_number = template.latest_revision_number + 1
        revision = TemplateRevision(
            id=revision_id,
            template_id=template.id,
            revision_number=revision_number,
            config=data.config,
            created_by_id=admin.id,
        )
        db.add(revision)
        template.config = data.config
        template.latest_revision_id = revision_id
        template.latest_revision_number = revision_number
        template.has_unpublished_changes = (
            template.published_revision_id is not None
        )

    template.updated_by_id = admin.id
    await db.commit()
    await db.refresh(template)
    logger.info("Template updated: id=%s admin=%s", template_id, admin.username)
    return template


@router.post("/{template_id}/publish", response_model=TemplateAdminOut)
async def publish_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id, for_update=True)
    if template.status == TemplateStatus.archived:
        raise HTTPException(409, "Restore the archived template before publishing it")

    if (
        template.status == TemplateStatus.published
        and template.published_revision_id == template.latest_revision_id
    ):
        return template

    result = await db.execute(
        select(TemplateRevision).where(
            TemplateRevision.id == template.latest_revision_id,
            TemplateRevision.template_id == template.id,
        )
    )
    revision = result.scalar_one_or_none()
    if revision is None:
        raise HTTPException(409, "Latest template revision is missing")

    now = datetime.now(timezone.utc)
    if revision.published_at is None:
        revision.published_at = now
        revision.published_by_id = admin.id
    template.published_revision_id = revision.id
    template.published_revision_number = revision.revision_number
    template.status = TemplateStatus.published
    template.has_unpublished_changes = False
    template.updated_by_id = admin.id
    await db.commit()
    await db.refresh(template)
    logger.info(
        "Template published: id=%s revision=%s admin=%s",
        template_id,
        revision.revision_number,
        admin.username,
    )
    return template


@router.post("/{template_id}/archive", response_model=TemplateAdminOut)
async def archive_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id, for_update=True)
    template.status = TemplateStatus.archived
    template.updated_by_id = admin.id
    await db.commit()
    await db.refresh(template)
    logger.info("Template archived: id=%s admin=%s", template_id, admin.username)
    return template


@router.post("/{template_id}/restore", response_model=TemplateAdminOut)
async def restore_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id, for_update=True)
    if template.status != TemplateStatus.archived:
        raise HTTPException(409, "Only archived templates can be restored")
    template.status = (
        TemplateStatus.published
        if template.published_revision_id is not None
        else TemplateStatus.draft
    )
    template.updated_by_id = admin.id
    await db.commit()
    await db.refresh(template)
    logger.info("Template restored: id=%s admin=%s", template_id, admin.username)
    return template


@router.get(
    "/{template_id}/revisions",
    response_model=List[TemplateRevisionSummary],
)
async def list_template_revisions(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id)
    result = await db.execute(
        select(TemplateRevision)
        .where(TemplateRevision.template_id == template_id)
        .order_by(TemplateRevision.revision_number.desc())
    )
    return [
        _revision_payload(revision, template)
        for revision in result.scalars().all()
    ]


@router.get(
    "/{template_id}/revisions/{revision_id}",
    response_model=TemplateRevisionOut,
)
async def get_template_revision(
    template_id: uuid.UUID,
    revision_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id)
    result = await db.execute(
        select(TemplateRevision).where(
            TemplateRevision.id == revision_id,
            TemplateRevision.template_id == template_id,
        )
    )
    revision = result.scalar_one_or_none()
    if revision is None:
        raise HTTPException(404, "Template revision not found")
    return _revision_payload(revision, template, include_config=True)


@router.post(
    "/{template_id}/preview",
    response_model=TemplatePreviewOut,
    status_code=201,
)
async def create_template_preview(
    template_id: uuid.UUID,
    data: TemplatePreviewCreate,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id)
    snapshot_config, revision_id = _preview_source(data, template)

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expiry_minutes = max(
        15, min(60, settings.TEMPLATE_PREVIEW_EXPIRE_MINUTES)
    )
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
    preview = TemplatePreview(
        template_id=template.id,
        revision_id=revision_id,
        token_hash=token_hash,
        config=snapshot_config,
        locale=data.locale,
        sample_data=data.sample_data,
        expires_at=expires_at,
    )
    db.add(preview)
    await db.commit()
    await db.refresh(preview)

    read_url = request.url_for("get_template_preview", preview_id=str(preview.id))
    preview_url = f"{read_url}?token={token}"
    logger.info(
        "Template preview created: template_id=%s preview_id=%s admin=%s",
        template_id,
        preview.id,
        admin.username,
    )
    return {
        "preview_id": preview.id,
        "template_id": preview.template_id,
        "revision_id": preview.revision_id,
        "preview_url": preview_url,
        "expires_at": preview.expires_at,
    }


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template(db, template_id, for_update=True)
    reference_count = await db.scalar(
        select(func.count(Invitation.id)).where(
            Invitation.template_id == template_id
        )
    )
    if template.published_revision_id is not None or reference_count:
        raise HTTPException(
            409,
            "Published or referenced templates must be archived instead",
        )
    await db.delete(template)
    await db.commit()
    logger.info("Template deleted: id=%s admin=%s", template_id, admin.username)
