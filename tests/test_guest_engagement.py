import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai import router as ai
from app.auth.models import User
from app.main import app
from app.rsvp.invitees_router import new_invitee_token
from app.rsvp.schemas import InviteeBulkCreate, InviteeCreate, RSVPResponseCreate

HOST = User(id=1, username="host", is_active=True, is_admin=False)


def test_rsvp_input_is_stripped_and_bounded():
    declined = RSVPResponseCreate(guest_name="  Дана ", will_attend=False, guest_count=0)
    assert declined.guest_name == "Дана"
    assert declined.wish_public is False and declined.invitee_token is None

    for bad in [
        {"guest_name": "  ", "will_attend": True},
        {"guest_name": "A", "will_attend": True, "guest_count": -1},
        {"guest_name": "A", "will_attend": True, "guest_count": 21},
        {"guest_name": "A", "will_attend": True, "message": "x" * 1001},
        {"guest_name": "A", "will_attend": True, "guest_phone": "1" * 21},
    ]:
        with pytest.raises(ValidationError):
            RSVPResponseCreate(**bad)


def test_invitee_input_limits_and_tokens():
    assert InviteeCreate(name=" Арман ").name == "Арман"
    with pytest.raises(ValidationError):
        InviteeBulkCreate(invitees=[])
    with pytest.raises(ValidationError):
        InviteeBulkCreate(invitees=[{"name": "X"}] * 201)

    tokens = {new_invitee_token() for _ in range(500)}
    assert len(tokens) == 500
    assert all(len(token) == 12 and token.replace("-", "").replace("_", "").isalnum() for token in tokens)


def test_prompt_follows_the_requested_tone():
    default = ai._build_prompt(ai.GenerateTextRequest(organizer_name="Нұрлановтар"))
    assert "торжественный текст" in default and ai._DEFAULT_STYLE in default

    fun = ai._build_prompt(ai.GenerateTextRequest(organizer_name="Нұрлановтар", tone="fun"))
    assert ai._TONE_STYLES["fun"] in fun
    assert "торжественный" not in fun

    formal = ai._build_prompt(ai.GenerateTextRequest(organizer_name="Нұрлановтар", tone="formal"))
    assert ai._TONE_STYLES["formal"] in formal and "торжественный текст" in formal

    with pytest.raises(ValidationError):
        ai.GenerateTextRequest(organizer_name="X", tone="sarcastic")
    with pytest.raises(ValidationError):
        ai.GenerateTextRequest(organizer_name="X", variants=4)


def test_variants_are_generated_in_parallel_and_first_is_text(monkeypatch):
    monkeypatch.setattr(ai.settings, "GROQ_API_KEY", "test-key")
    calls = []

    async def fake_generate(client, payload):
        calls.append(payload)
        return f"Вариант {len(calls)}"

    monkeypatch.setattr(ai, "_generate_once", fake_generate)
    request = ai.GenerateTextRequest(organizer_name="Нұрлановтар", tone="warm", variants=3)
    response = asyncio.run(ai.generate_invitation_text(request, current_user=HOST))
    assert response.texts == ["Вариант 1", "Вариант 2", "Вариант 3"]
    assert response.text == "Вариант 1"
    assert len(calls) == 3 and calls[0]["temperature"] == 0.95

    single = asyncio.run(ai.generate_invitation_text(ai.GenerateTextRequest(organizer_name="X"), current_user=HOST))
    assert single.texts == [single.text]


def test_ai_without_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(ai.settings, "GROQ_API_KEY", "")
    with pytest.raises(HTTPException) as error:
        asyncio.run(ai.generate_invitation_text(ai.GenerateTextRequest(organizer_name="X"), current_user=HOST))
    assert error.value.status_code == 503


def test_openapi_lists_guest_engagement_routes():
    schema = app.openapi()
    paths = schema["paths"]
    assert "patch" in paths["/api/v1/my/invitations/{invitation_id}/guests/{response_id}"]
    assert {"get", "post"} <= set(paths["/api/v1/my/invitations/{invitation_id}/invitees"])
    assert "delete" in paths["/api/v1/my/invitations/{invitation_id}/invitees/{invitee_id}"]
    assert "get" in paths["/api/v1/my/activity"]
    public_params = {p["name"] for p in paths["/api/v1/invite/{slug}"]["get"]["parameters"]}
    assert "g" in public_params
    public_fields = schema["components"]["schemas"]["InvitationPublicOut"]["properties"]
    assert {"questions", "wishes", "invitee"} <= set(public_fields)
