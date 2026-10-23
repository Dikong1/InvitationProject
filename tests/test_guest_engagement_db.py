"""End-to-end API tests for guest engagement features against a real PostgreSQL.

Skipped unless TEST_DATABASE_URL points at an empty, disposable database, e.g.:

    TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/invitation_test \\
    DATABASE_URL=$TEST_DATABASE_URL JWT_SECRET_KEY=test python -m pytest tests/test_guest_engagement_db.py

The schema is built with `alembic upgrade head`, so the migrations are exercised too.
"""
import asyncio
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def migrated_database():
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    yield


class Api:
    """Drives the FastAPI app in-process with a fresh session per request."""

    def __init__(self):
        from app.main import app
        from app.database import get_db
        from app.auth.config import get_current_user

        self.app = app
        self.engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
        self.sessions = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        self.user = None

        async def override_db():
            async with self.sessions() as session:
                yield session

        async def override_user():
            if self.user is None:
                from fastapi import HTTPException
                raise HTTPException(401, "Not authenticated")
            return self.user

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def sql(self, statement, **params):
        async with self.engine.begin() as connection:
            return await connection.execute(text(statement), params)

    async def make_user(self, username):
        from app.auth.models import User
        result = await self.sql(
            "INSERT INTO users (username, password_hash, is_active, is_admin, failed_login_attempts, is_locked) "
            "VALUES (:u, 'x', true, false, 0, false) RETURNING id",
            u=username,
        )
        user_id = result.scalar_one()
        return User(id=user_id, username=username, is_active=True, is_admin=False)

    async def published_invitation(self, owner, title="Той"):
        self.user = owner
        response = await self.client.post("/api/v1/my/invitations", json={
            "title": title,
            "details": {"organizer_name": f"Host {uuid.uuid4().hex[:6]}", "event_date": str(date.today() + timedelta(days=30))},
        })
        assert response.status_code == 201, response.text
        invitation = response.json()
        await self.sql(
            "UPDATE invitations SET is_paid = true, status = 'published', published_at = now() WHERE id = :id",
            id=invitation["id"],
        )
        return invitation

    async def close(self):
        self.app.dependency_overrides.clear()
        await self.client.aclose()
        await self.engine.dispose()


def run(scenario):
    async def wrapper():
        api = Api()
        try:
            await scenario(api)
        finally:
            await api.close()
    asyncio.run(wrapper())


def test_public_page_includes_host_questions_in_order():
    async def scenario(api):
        owner = await api.make_user("questions-host")
        invitation = await api.published_invitation(owner)
        for order, text_ru in [(2, "Трансфер нужен?"), (1, "Выбор блюда")]:
            created = await api.client.post(f"/api/v1/my/invitations/{invitation['id']}/questions", json={
                "question_text_kk": text_ru, "question_text_ru": text_ru, "question_type": "text", "sort_order": order,
            })
            assert created.status_code == 201, created.text

        api.user = None
        page = await api.client.get(f"/api/v1/invite/{invitation['slug']}")
        assert page.status_code == 200, page.text
        assert [q["question_text_ru"] for q in page.json()["questions"]] == ["Выбор блюда", "Трансфер нужен?"]

    run(scenario)


def test_rsvp_accepts_declines_with_zero_guests_and_rejects_oversized_input():
    async def scenario(api):
        owner = await api.make_user("limits-host")
        invitation = await api.published_invitation(owner)
        api.user = None
        url = f"/api/v1/invite/{invitation['slug']}/rsvp"

        declined = await api.client.post(url, json={"guest_name": "  Дана  ", "will_attend": False, "guest_count": 0})
        assert declined.status_code == 200, declined.text
        assert declined.json()["guest_name"] == "Дана"

        for body in [
            {"guest_name": "   ", "will_attend": True},
            {"guest_name": "A", "will_attend": True, "guest_count": 21},
            {"guest_name": "A", "will_attend": True, "message": "x" * 1001},
        ]:
            response = await api.client.post(url, json=body)
            assert response.status_code == 422, body

    run(scenario)


def test_wishes_need_guest_consent_and_host_approval_and_reset_when_edited():
    async def scenario(api):
        owner = await api.make_user("wishes-host")
        invitation = await api.published_invitation(owner)
        slug, inv_id = invitation["slug"], invitation["id"]

        api.user = None
        public = await api.client.post(f"/api/v1/invite/{slug}/rsvp", json={
            "guest_name": "Айгерім", "guest_phone": "+77010000001", "will_attend": True,
            "message": "Бақытты болыңдар!", "wish_public": True,
        })
        private = await api.client.post(f"/api/v1/invite/{slug}/rsvp", json={
            "guest_name": "Арман", "will_attend": True, "message": "Only for the host",
        })
        assert public.status_code == private.status_code == 200
        assert public.json()["wish_public"] is True and public.json()["wish_visible"] is False

        page = await api.client.get(f"/api/v1/invite/{slug}")
        assert page.json()["wishes"] == []

        api.user = owner
        moderation = f"/api/v1/my/invitations/{inv_id}/guests"
        refused = await api.client.patch(f"{moderation}/{private.json()['id']}", json={"wish_visible": True})
        assert refused.status_code == 400
        approved = await api.client.patch(f"{moderation}/{public.json()['id']}", json={"wish_visible": True})
        assert approved.status_code == 200 and approved.json()["wish_visible"] is True

        api.user = None
        wishes = (await api.client.get(f"/api/v1/invite/{slug}")).json()["wishes"]
        assert [(w["guest_name"], w["message"]) for w in wishes] == [("Айгерім", "Бақытты болыңдар!")]
        assert set(wishes[0]) == {"id", "guest_name", "message", "responded_at"}

        # Same phone, same text: approval is kept. New text: back to pending.
        same = await api.client.post(f"/api/v1/invite/{slug}/rsvp", json={
            "guest_name": "Айгерім", "guest_phone": "+77010000001", "will_attend": True,
            "guest_count": 2, "message": "Бақытты болыңдар!", "wish_public": True,
        })
        assert same.json()["wish_visible"] is True
        edited = await api.client.post(f"/api/v1/invite/{slug}/rsvp", json={
            "guest_name": "Айгерім", "guest_phone": "+77010000001", "will_attend": True,
            "message": "Жаңа тілек", "wish_public": True,
        })
        assert edited.json()["wish_visible"] is False
        assert (await api.client.get(f"/api/v1/invite/{slug}")).json()["wishes"] == []

    run(scenario)


def test_only_the_owner_can_moderate_wishes():
    async def scenario(api):
        owner = await api.make_user("moderation-owner")
        stranger = await api.make_user("moderation-stranger")
        invitation = await api.published_invitation(owner)
        api.user = None
        response = await api.client.post(f"/api/v1/invite/{invitation['slug']}/rsvp", json={
            "guest_name": "Guest", "will_attend": True, "message": "Hi", "wish_public": True,
        })
        api.user = stranger
        url = f"/api/v1/my/invitations/{invitation['id']}/guests/{response.json()['id']}"
        assert (await api.client.patch(url, json={"wish_visible": True})).status_code == 404
        api.user = owner
        assert (await api.client.patch(f"/api/v1/my/invitations/{invitation['id']}/guests/{uuid.uuid4()}", json={"wish_visible": True})).status_code == 404

    run(scenario)
