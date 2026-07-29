import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import get_logger
from app.auth.models import User
from app.auth.config import get_current_admin_user
from app.invitations.models import Invitation, InvitationStatus
from app.payments.models import Payment, PaymentStatus, PaymentPlan
from app.payments.schemas import PaymentOut, PaymentPlanOut
from app.categories.models import EventCategory
from app.categories.schemas import CategoryCreate, CategoryUpdate, CategoryOut
from app.inv_templates.models import InvitationTemplate
from app.inv_templates.schemas import TemplateAdminOut, TemplateUpdate

TemplateOut = TemplateAdminOut

TEMPLATE_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
TEMPLATE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _save_template_file(contents: bytes, original_filename: str) -> str:
    ext = Path(original_filename or "image.jpg").suffix.lower() or ".jpg"
    filename = f"{uuid.uuid4()}{ext}"
    dest = Path(settings.TEMPLATES_DIR) / filename
    dest.write_bytes(contents)
    return f"{settings.MEDIA_BASE_URL}/templates/{filename}"


async def _validate_and_save_upload(file: UploadFile) -> str:
    if file.content_type not in TEMPLATE_ALLOWED_TYPES:
        raise HTTPException(400, "Допустимые форматы: jpeg, png, webp")
    contents = await file.read()
    if len(contents) > TEMPLATE_MAX_BYTES:
        raise HTTPException(400, "Файл слишком большой. Максимум 10 МБ")
    return _save_template_file(contents, file.filename or "image.jpg")


def _parse_template_config(config: Optional[str]) -> dict:
    if not config:
        return {}
    try:
        parsed = json.loads(config)
    except json.JSONDecodeError:
        raise HTTPException(422, "Поле config должно быть валидным JSON")
    if not isinstance(parsed, dict):
        raise HTTPException(422, "config must be a JSON object")
    return parsed


router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = get_logger("admin")


# ─── Payment management ───────────────────────────────────────────────────────

@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    payment_status: Optional[str] = Query(None, alias="status"),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Payment).order_by(Payment.created_at.desc())
    if payment_status:
        try:
            stmt = stmt.where(Payment.status == PaymentStatus(payment_status))
        except ValueError:
            raise HTTPException(400, f"Неверный статус: {payment_status}")
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/payments/{payment_id}/confirm", response_model=PaymentOut)
async def confirm_payment(
    payment_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin confirms that a Kaspi payment was received.
    Updates payment to success and publishes the associated invitation.
    """
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    if payment.status != PaymentStatus.pending:
        raise HTTPException(400, f"Платёж уже имеет статус: {payment.status.value}")

    try:
        now = datetime.now(timezone.utc)
        payment.status = PaymentStatus.success
        payment.paid_at = now
        payment.confirmed_by = admin.id  # existing audit field on Payment

        if payment.invitation_id:
            inv_result = await db.execute(
                select(Invitation).where(Invitation.id == payment.invitation_id)
            )
            inv = inv_result.scalar_one_or_none()
            if inv:
                inv.status = InvitationStatus.published
                inv.is_paid = True
                inv.published_at = now
                inv.updated_by_id = admin.id  # audit: admin published it

                if payment.plan_id:
                    plan_result = await db.execute(
                        select(PaymentPlan).where(PaymentPlan.id == payment.plan_id)
                    )
                    plan = plan_result.scalar_one_or_none()
                    if plan:
                        inv.expires_at = now + timedelta(days=plan.validity_days)

        await db.commit()
        await db.refresh(payment)
        logger.info(
            "Payment confirmed: payment_id=%s invitation_id=%s admin=%s",
            payment_id, payment.invitation_id, admin.username,
        )
        return payment
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("Payment confirmation error: payment_id=%s error=%s", payment_id, e)
        raise HTTPException(500, f"Ошибка подтверждения платежа: {str(e)}")


@router.post("/payments/{payment_id}/reject", response_model=PaymentOut)
async def reject_payment(
    payment_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(404, "Платёж не найден")
    if payment.status != PaymentStatus.pending:
        raise HTTPException(400, f"Платёж уже имеет статус: {payment.status.value}")

    payment.status = PaymentStatus.failed
    payment.confirmed_by = admin.id  # record who rejected it too
    await db.commit()
    await db.refresh(payment)
    logger.info("Payment rejected: payment_id=%s admin=%s", payment_id, admin.username)
    return payment


# ─── Category management ─────────────────────────────────────────────────────

@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    data: CategoryCreate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(EventCategory).where(EventCategory.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Категория со slug '{data.slug}' уже существует")

    cat = EventCategory(**data.model_dump(), created_by_id=admin.id, updated_by_id=admin.id)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    logger.info("Category created: slug=%s admin=%s", data.slug, admin.username)
    return cat


@router.put("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EventCategory).where(EventCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(cat, field, value)
    cat.updated_by_id = admin.id

    await db.commit()
    await db.refresh(cat)
    logger.info("Category updated: id=%s admin=%s", category_id, admin.username)
    return cat


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(
    category_id: int,
    data: CategoryUpdate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EventCategory).where(EventCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(cat, field, value)
    cat.updated_by_id = admin.id

    await db.commit()
    await db.refresh(cat)
    logger.info("Category patched: id=%s admin=%s", category_id, admin.username)
    return cat


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: int,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EventCategory).where(EventCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(404, "Категория не найдена")
    await db.delete(cat)
    await db.commit()
    logger.info("Category deleted: id=%s admin=%s", category_id, admin.username)


# ─── Template management ─────────────────────────────────────────────────────

async def create_template(
    name_kk: str = Form(...),
    name_ru: str = Form(...),
    category_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    config: Optional[str] = Form(None),
    is_premium: bool = Form(False),
    sort_order: int = Form(0),
    preview: Optional[UploadFile] = File(None),
    thumbnail: Optional[UploadFile] = File(None),
    images: Optional[List[UploadFile]] = File(None),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    preview_url = await _validate_and_save_upload(preview) if preview and preview.filename else None
    thumbnail_url = await _validate_and_save_upload(thumbnail) if thumbnail and thumbnail.filename else None
    image_urls = [await _validate_and_save_upload(img) for img in (images or []) if img.filename]

    tpl = InvitationTemplate(
        category_id=category_id,
        name_kk=name_kk,
        name_ru=name_ru,
        description=description,
        preview_url=preview_url,
        thumbnail_url=thumbnail_url,
        images=image_urls,
        config=_parse_template_config(config),
        is_premium=is_premium,
        sort_order=sort_order,
        created_by_id=admin.id,
        updated_by_id=admin.id,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    logger.info("Template created: id=%s admin=%s", tpl.id, admin.username)
    return tpl


async def update_template(
    template_id: uuid.UUID,
    data: TemplateUpdate,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(tpl, field, value)
    tpl.updated_by_id = admin.id

    await db.commit()
    await db.refresh(tpl)
    logger.info("Template updated: id=%s admin=%s", template_id, admin.username)
    return tpl


async def patch_template(
    template_id: uuid.UUID,
    name_kk: Optional[str] = Form(None),
    name_ru: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    config: Optional[str] = Form(None),
    is_premium: Optional[bool] = Form(None),
    is_active: Optional[bool] = Form(None),
    sort_order: Optional[int] = Form(None),
    preview: Optional[UploadFile] = File(None),
    thumbnail: Optional[UploadFile] = File(None),
    images: Optional[List[UploadFile]] = File(None),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")

    if name_kk is not None:
        tpl.name_kk = name_kk
    if name_ru is not None:
        tpl.name_ru = name_ru
    if category_id is not None:
        tpl.category_id = category_id
    if description is not None:
        tpl.description = description
    if config is not None:
        tpl.config = _parse_template_config(config)
    if is_premium is not None:
        tpl.is_premium = is_premium
    if is_active is not None:
        tpl.is_active = is_active
    if sort_order is not None:
        tpl.sort_order = sort_order

    if preview and preview.filename:
        tpl.preview_url = await _validate_and_save_upload(preview)
    if thumbnail and thumbnail.filename:
        tpl.thumbnail_url = await _validate_and_save_upload(thumbnail)

    # Uploaded images are appended to the existing gallery; if none are
    # uploaded, the gallery is left untouched.
    new_images = [img for img in (images or []) if img.filename]
    if new_images:
        current_images = list(tpl.images or [])
        for img in new_images:
            current_images.append(await _validate_and_save_upload(img))
        tpl.images = current_images

    tpl.updated_by_id = admin.id

    await db.commit()
    await db.refresh(tpl)
    logger.info("Template patched: id=%s admin=%s", template_id, admin.username)
    return tpl


async def delete_template(
    template_id: uuid.UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")
    await db.delete(tpl)
    await db.commit()
    logger.info("Template deleted: id=%s admin=%s", template_id, admin.username)


@router.post("/templates/{template_id}/preview-image", response_model=TemplateOut)
async def upload_template_preview(
    template_id: uuid.UUID,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload (or replace) the preview image for a template."""
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")

    tpl.preview_url = await _validate_and_save_upload(file)
    tpl.updated_by_id = admin.id
    await db.commit()
    await db.refresh(tpl)
    logger.info("Template preview uploaded: id=%s admin=%s", template_id, admin.username)
    return tpl


@router.post("/templates/{template_id}/images", response_model=TemplateOut)
async def upload_template_image(
    template_id: uuid.UUID,
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an example image and append its URL to the template's images list."""
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")

    url = await _validate_and_save_upload(file)
    current_images = list(tpl.images or [])
    current_images.append(url)
    tpl.images = current_images
    tpl.updated_by_id = admin.id
    await db.commit()
    await db.refresh(tpl)
    logger.info("Template image uploaded: id=%s admin=%s url=%s", template_id, admin.username, url)
    return tpl


@router.delete("/templates/{template_id}/images/{image_index}", response_model=TemplateOut)
async def delete_template_image(
    template_id: uuid.UUID,
    image_index: int,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an example image by its index in the images list."""
    result = await db.execute(
        select(InvitationTemplate).where(InvitationTemplate.id == template_id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        raise HTTPException(404, "Шаблон не найден")

    current_images = list(tpl.images or [])
    if image_index < 0 or image_index >= len(current_images):
        raise HTTPException(400, f"Индекс {image_index} вне диапазона (0–{len(current_images) - 1})")

    removed_url = current_images.pop(image_index)
    tpl.images = current_images
    tpl.updated_by_id = admin.id
    await db.commit()
    await db.refresh(tpl)

    # Delete physical file
    try:
        filename = Path(removed_url).name
        target = Path(settings.TEMPLATES_DIR) / filename
        if target.exists():
            target.unlink()
    except Exception as e:
        logger.warning("Could not delete template image file: %s", e)

    logger.info("Template image deleted: id=%s index=%s admin=%s", template_id, image_index, admin.username)
    return tpl


# ─── Payment plan management ─────────────────────────────────────────────────

@router.post("/plans", response_model=PaymentPlanOut, status_code=201)
async def create_plan(
    data: dict,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    plan = PaymentPlan(**data, created_by_id=admin.id, updated_by_id=admin.id)
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    logger.info("Payment plan created: id=%s admin=%s", plan.id, admin.username)
    return plan


# ─── User management ─────────────────────────────────────────────────────────

@router.get("/users", response_model=list[dict])
async def list_users(
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.auth.schemas import UserOut
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [UserOut.model_validate(u).model_dump() for u in users]


@router.post("/users/{user_id}/make-admin", response_model=dict)
async def make_admin(
    user_id: int,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    user.is_admin = True
    await db.commit()
    logger.info("User promoted to admin: user_id=%s by admin=%s", user_id, admin.username)
    return {"message": f"Пользователь {user.username} назначен администратором"}
