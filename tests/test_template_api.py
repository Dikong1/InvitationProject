import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.config import get_current_admin_user
from app.auth.models import User
from app.inv_templates.admin_router import (
    _parse_template_config,
    _preview_source,
    _revision_payload,
    archive_template,
    create_template,
    publish_template,
    restore_template,
    update_template,
)
from app.inv_templates.models import (
    InvitationTemplate,
    TemplatePreview,
    TemplateRevision,
    TemplateStatus,
)
from app.inv_templates.router import (
    get_template_preview,
    public_template_payload,
)
from app.inv_templates.schemas import (
    TemplatePreviewCreate,
    TemplatePublicOut,
    TemplateUpdate,
)
from app.main import app


def make_template(
    *,
    status: TemplateStatus = TemplateStatus.draft,
    latest_config=None,
) -> InvitationTemplate:
    template = InvitationTemplate(
        id=uuid.uuid4(),
        name_kk="Үлгі",
        name_ru="Шаблон",
        config=latest_config if latest_config is not None else {},
        images=[],
        is_premium=False,
        is_active=True,
        sort_order=0,
        status=status,
        latest_revision_id=uuid.uuid4(),
        published_revision_id=None,
        latest_revision_number=1,
        published_revision_number=None,
        has_unpublished_changes=False,
    )
    template.created_at = datetime.now(timezone.utc)
    return template


def test_config_contract_preserves_flexible_objects_and_rejects_non_objects():
    config = {
        "unknown": {
            "values": ["text", 1, True, None, {"nested": 2.5}],
        }
    }
    assert TemplateUpdate(config=config).config == config
    assert _parse_template_config('{"empty": {}, "array": [1, null]}') == {
        "empty": {},
        "array": [1, None],
    }

    with pytest.raises(ValidationError):
        TemplateUpdate(config=["not", "an", "object"])
    with pytest.raises(HTTPException) as error:
        _parse_template_config("[1, 2]")
    assert error.value.status_code == 422


def test_public_payload_uses_published_revision_and_hides_latest_state():
    template = make_template(
        status=TemplateStatus.published,
        latest_config={"draft": "secret"},
    )
    revision = TemplateRevision(
        id=uuid.uuid4(),
        template_id=template.id,
        revision_number=3,
        config={"published": {"exact": [1, True, None]}},
    )
    template.published_revision_id = revision.id
    template.published_revision_number = 3

    response = TemplatePublicOut.model_validate(
        public_template_payload(template, revision)
    ).model_dump()
    assert response["config"] == revision.config
    assert "latest_revision_id" not in response
    assert "has_unpublished_changes" not in response


def test_revision_summary_marks_latest_and_published_independently():
    template = make_template(status=TemplateStatus.published)
    revision = TemplateRevision(
        id=uuid.uuid4(),
        template_id=template.id,
        revision_number=2,
        config={"version": 2},
        created_by_id=1,
    )
    revision.created_at = datetime.now(timezone.utc)
    template.latest_revision_id = revision.id
    template.latest_revision_number = 2
    template.published_revision_id = uuid.uuid4()
    template.published_revision_number = 1

    summary = _revision_payload(revision, template)
    assert summary["is_latest"] is True
    assert summary["is_published"] is False
    assert "config" not in summary


def test_unsaved_preview_is_not_assigned_a_permanent_revision():
    template = make_template(latest_config={"saved": True})
    unsaved = {"constructor": {"unknown": ["value", 1]}}

    config, revision_id = _preview_source(
        TemplatePreviewCreate(config=unsaved, locale="ru"),
        template,
    )
    assert config == unsaved
    assert revision_id is None

    saved_config, saved_revision_id = _preview_source(
        TemplatePreviewCreate(locale="kk"),
        template,
    )
    assert saved_config == template.config
    assert saved_revision_id == template.latest_revision_id


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class PreviewSession:
    def __init__(self, preview):
        self.preview = preview

    async def execute(self, statement):
        return ScalarResult(self.preview)


class LifecycleSession:
    def __init__(self):
        self.template = None
        self.revisions = {}

    def add_all(self, objects):
        for item in objects:
            self.add(item)

    def add(self, item):
        if isinstance(item, InvitationTemplate):
            self.template = item
        elif isinstance(item, TemplateRevision):
            self.revisions[item.id] = item

    async def execute(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is InvitationTemplate:
            return ScalarResult(self.template)
        if entity is TemplateRevision:
            return ScalarResult(
                self.revisions.get(self.template.latest_revision_id)
            )
        raise AssertionError(f"Unexpected query entity: {entity}")

    async def commit(self):
        return None

    async def refresh(self, item):
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime.now(timezone.utc)


def test_draft_publish_edit_republish_archive_restore_lifecycle():
    async def scenario():
        admin = User(
            id=1,
            username="admin",
            password_hash="unused",
            is_active=True,
            is_admin=True,
        )
        session = LifecycleSession()
        original = {"version": 1, "unknown": {"kept": [None, True]}}
        template = await create_template(
            name_kk="Үлгі",
            name_ru="Шаблон",
            category_id=None,
            description=None,
            config='{"version": 1, "unknown": {"kept": [null, true]}}',
            is_premium=False,
            is_active=True,
            sort_order=0,
            preview=None,
            thumbnail=None,
            images=None,
            admin=admin,
            db=session,
        )
        revision_one_id = template.latest_revision_id
        assert template.status == TemplateStatus.draft
        assert template.latest_revision_number == 1
        assert session.revisions[revision_one_id].config == original

        await publish_template(template.id, admin=admin, db=session)
        assert template.status == TemplateStatus.published
        assert template.published_revision_id == revision_one_id
        assert template.has_unpublished_changes is False

        new_config = {"version": 2, "new": ["opaque", 2]}
        await update_template(
            template.id,
            TemplateUpdate(config=new_config, base_revision_number=1),
            admin=admin,
            db=session,
        )
        revision_two_id = template.latest_revision_id
        assert revision_two_id != revision_one_id
        assert template.latest_revision_number == 2
        assert template.published_revision_id == revision_one_id
        assert template.has_unpublished_changes is True
        assert session.revisions[revision_one_id].config == original
        assert session.revisions[revision_two_id].config == new_config

        await publish_template(template.id, admin=admin, db=session)
        assert template.published_revision_id == revision_two_id
        assert template.published_revision_number == 2
        assert template.has_unpublished_changes is False

        await archive_template(template.id, admin=admin, db=session)
        assert template.status == TemplateStatus.archived
        assert template.published_revision_id == revision_two_id
        await restore_template(template.id, admin=admin, db=session)
        assert template.status == TemplateStatus.published
        assert template.is_active is True

    asyncio.run(scenario())


def test_preview_token_is_required_and_expiry_is_enforced():
    token = "unguessable-token-with-enough-entropy"
    preview = TemplatePreview(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        config={"opaque": [1, None]},
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    response = asyncio.run(
        get_template_preview(
            preview.id,
            token=token,
            db=PreviewSession(preview),
        )
    )
    assert response["config"] == preview.config

    with pytest.raises(HTTPException) as invalid:
        asyncio.run(
            get_template_preview(
                preview.id,
                token="a-different-unguessable-token",
                db=PreviewSession(preview),
            )
        )
    assert invalid.value.status_code == 404

    preview.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException) as expired:
        asyncio.run(
            get_template_preview(
                preview.id,
                token=token,
                db=PreviewSession(preview),
            )
        )
    assert expired.value.status_code == 410


def test_admin_authorization_contract():
    client = TestClient(app)
    assert client.get("/api/v1/admin/templates").status_code == 401

    non_admin = User(
        id=2,
        username="member",
        password_hash="unused",
        is_active=True,
        is_admin=False,
    )
    with pytest.raises(HTTPException) as forbidden:
        asyncio.run(get_current_admin_user(non_admin))
    assert forbidden.value.status_code == 403


def test_openapi_contains_template_lifecycle_and_preview_paths():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/admin/templates",
        "/api/v1/admin/templates/{template_id}",
        "/api/v1/admin/templates/{template_id}/publish",
        "/api/v1/admin/templates/{template_id}/archive",
        "/api/v1/admin/templates/{template_id}/restore",
        "/api/v1/admin/templates/{template_id}/revisions",
        "/api/v1/admin/templates/{template_id}/revisions/{revision_id}",
        "/api/v1/admin/templates/{template_id}/preview",
        "/api/v1/template-previews/{preview_id}",
    }
    assert expected.issubset(paths)
