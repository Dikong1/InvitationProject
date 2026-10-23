# Invitation Platform — Project Context for Claude

> Read this file at the start of every session. It covers everything needed to work on this project without prior conversation history.

---

## What this project is

A **FastAPI backend** for a Kazakh digital-invitation platform. Users create, customize and publish event invitations (weddings, birthdays, etc.). Guests receive a public link and can RSVP. Publishing requires payment via Kaspi (manual transfer, confirmed by admin).

---

## Environment

| Item | Value |
|---|---|
| Python | 3.9 (venv at `.venv/`) |
| Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 async (`asyncpg` driver) |
| Migrations | Alembic |
| DB | PostgreSQL `inv_admin:Invitation08022026@localhost:5432/invitation_db` |
| Auth | JWT in httpOnly cookies (`access_token` 30 min, `refresh_token` 1 day) + Bearer header fallback |
| Password | `pwdlib` with argon2 |
| AI | Groq API (`llama-3.3-70b-versatile`) via `httpx` |
| Images | Pillow (thumbnails 300×300) |

### How to run

```bash
.venv\Scripts\activate          # Windows
uvicorn app.main:app --reload
# Docs at http://localhost:8000/docs
```

### Migrations

```bash
python -m alembic upgrade head   # apply all migrations
python -m app.init_db            # seed: 9 categories + 3 payment plans
```

---

## Critical Python 3.9 rules

- Use `Optional[X]` — **never** `X | None` (union syntax requires 3.10+)
- Use `List[X]`, `Dict[X, Y]` from `typing` — **never** `list[X]` as a type hint in function signatures or class bodies (only safe inside `""` strings or with `from __future__ import annotations`)
- Add `from __future__ import annotations` at the top of any file that uses complex forward-reference type hints

---

## Module structure

```
app/
├── auth/           # JWT auth: register, login, lockout (5 attempts → 30 min lock)
├── categories/     # EventCategory model + public listing
├── inv_templates/  # InvitationTemplate model (named inv_templates to avoid clash with Jinja "templates")
├── invitations/    # Invitation + InvitationDetails: CRUD, slug, editable_until
├── media/          # InvitationMedia: file upload to local disk, Pillow thumbnails
├── rsvp/           # RSVPQuestion + RSVPResponse (dedup by phone, rate-limit by IP)
├── payments/       # PaymentPlan + Payment: Kaspi manual flow
├── ai/             # Groq text generation endpoint
├── admin/          # Admin-only CRUD: payments, categories, templates, users
├── config.py       # pydantic-settings (reads .env)
├── database.py     # async engine + session factory + Base
├── logging_config.py  # daily rotating logs → logs/app.log
├── utils.py        # slug generation with Cyrillic transliteration
└── init_db.py      # seed script
```

---

## All API routes

### Auth (`/auth/*`)
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | — | Register new user |
| POST | `/auth/login` | — | Login, sets JWT cookies |
| POST | `/auth/refresh` | cookie/header | Refresh access token |
| POST | `/auth/logout` | — | Clear cookies |
| GET | `/auth/me` | required | Current user info |
| PATCH | `/auth/me` | required | Update profile |

### Public (`/api/v1/*`)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/categories` | — | List event categories |
| GET | `/api/v1/templates` | — | List active templates (filter: `?category=slug`) |
| GET | `/api/v1/templates/{id}` | — | Single template |
| GET | `/api/v1/invite/{slug}` | — | Public invitation page (404 if not paid/published); includes `questions`, approved `wishes`, and `invitee` when `?g=<token>` matches |
| POST | `/api/v1/invite/{slug}/rsvp` | — | Submit RSVP (dedup by invitee token, then phone; `wish_public`, `invitee_token`) |

### My invitations (`/api/v1/my/*`)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/my/invitations` | required | List own invitations |
| POST | `/api/v1/my/invitations` | required | Create invitation |
| GET | `/api/v1/my/invitations/{id}` | required | Get one |
| PUT | `/api/v1/my/invitations/{id}` | required | Full update (403 after editable_until) |
| DELETE | `/api/v1/my/invitations/{id}` | required | Delete |
| GET | `/api/v1/my/invitations/{id}/guests` | required | RSVP summary + responses (`invited_count`, `pending`) |
| PATCH | `/api/v1/my/invitations/{id}/guests/{rid}` | required | Approve/hide a guest's wish (`wish_visible`) |
| GET | `/api/v1/my/invitations/{id}/invitees` | required | Guest list with personal link tokens and response status |
| POST | `/api/v1/my/invitations/{id}/invitees` | required | Add 1–200 guests (max 1000 per invitation) |
| DELETE | `/api/v1/my/invitations/{id}/invitees/{iid}` | required | Remove a guest (their RSVP is kept, unlinked) |
| GET | `/api/v1/my/activity` | required | Recent RSVPs across own invitations (`since`, `limit`) |
| GET | `/api/v1/my/invitations/{id}/questions` | required | List RSVP questions |
| POST | `/api/v1/my/invitations/{id}/questions` | required | Add RSVP question |
| DELETE | `/api/v1/my/invitations/{id}/questions/{qid}` | required | Delete question |
| GET | `/api/v1/my/invitations/{id}/media` | required | List uploaded media |
| POST | `/api/v1/my/invitations/{id}/media` | required | Upload media file (multipart) |
| DELETE | `/api/v1/my/invitations/{id}/media/{mid}` | required | Delete media file |

### Payments (`/api/v1/payment/*`)
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/v1/payment/plans` | — | List active payment plans |
| POST | `/api/v1/payment/create` | required | Create payment → returns Kaspi phone + amount |
| GET | `/api/v1/payment/history` | required | Own payment history |

### AI (`/api/v1/ai/*`)
| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/ai/generate-text` | required | Generate invitation text via Groq (`tone`, `variants` 1–3 → `texts`) |

### Admin (`/api/v1/admin/*`) — `is_admin=True` required
| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/payments` | List all payments (filter: `?status=pending`) |
| POST | `/api/v1/admin/payments/{id}/confirm` | Confirm Kaspi payment → publishes invitation |
| POST | `/api/v1/admin/payments/{id}/reject` | Reject payment |
| POST | `/api/v1/admin/categories` | Create category |
| PUT/PATCH | `/api/v1/admin/categories/{id}` | Update category |
| DELETE | `/api/v1/admin/categories/{id}` | Delete category |
| POST | `/api/v1/admin/templates` | Create template |
| PUT/PATCH | `/api/v1/admin/templates/{id}` | Update template |
| DELETE | `/api/v1/admin/templates/{id}` | Delete template |
| POST | `/api/v1/admin/templates/{id}/preview` | Upload preview image (multipart) |
| POST | `/api/v1/admin/templates/{id}/images` | Upload example image, appended to `images[]` |
| DELETE | `/api/v1/admin/templates/{id}/images/{index}` | Remove example image by index |
| POST | `/api/v1/admin/plans` | Create payment plan |
| GET | `/api/v1/admin/users` | List all users |
| POST | `/api/v1/admin/users/{id}/make-admin` | Promote user to admin |

---

## Key models

### User
`id`, `username`, `password_hash`, `email`, `full_name`, `is_active`, `is_admin`, `failed_login_attempts`, `is_locked`, `locked_until`, `created_at`, `updated_at`

### InvitationTemplate
`id (UUID)`, `category_id`, `name_kk`, `name_ru`, `description`, `preview_url` (nullable, set via upload), `thumbnail_url`, `images (JSONB list of URLs)`, `config (JSONB)`, `is_premium`, `is_active`, `sort_order`, `created_by_id`, `updated_by_id`, `created_at`

### Invitation
`id (UUID)`, `user_id`, `template_id`, `title`, `slug` (unique), `status (draft/published/expired/archived)`, `is_paid`, `editable_until (created_at + 3 days)`, `published_at`, `expires_at`, `created_at`, `updated_at`, `created_by_id`, `updated_by_id`

### InvitationDetails
`id`, `invitation_id (FK)`, `event_date`, `event_time`, `venue_name`, `venue_address`, `dress_code`, `notes`, `google_maps_url`, `custom_fields (JSONB)`

### Payment
`id (UUID)`, `user_id`, `invitation_id`, `plan_id`, `amount`, `status (pending/success/failed)`, `kaspi_phone`, `paid_at`, `confirmed_by (admin user_id)`, `created_at`

### PaymentPlan
`id`, `name`, `price`, `validity_days`, `max_guests`, `max_photos`, `is_active`

### InvitationMedia
`id (UUID)`, `invitation_id`, `media_type (photo/video)`, `url`, `thumbnail_url`, `caption`, `display_style (rectangle/square/circle)`, `sort_order`, `created_at`

### RSVPQuestion / RSVPResponse / Invitee
Questions: `id`, `invitation_id`, `question_text_kk`, `question_text_ru`, `question_type (boolean/number/text/select)`, `options (JSONB)`, `is_required`, `sort_order`
Responses: `id`, `invitation_id`, `invitee_id (FK rsvp_invitees, SET NULL; unique when set)`, `guest_name`, `guest_phone`, `will_attend`, `guest_count`, `message`, `answers (JSONB)`, `wish_public`, `wish_visible`, `ip_address`, `responded_at`
Invitees (`rsvp_invitees`): `id`, `invitation_id`, `name`, `phone`, `token (12 chars, unique)`, `created_at`

### EventCategory
`id`, `name_kk`, `name_ru`, `slug`, `icon`, `sort_order`, `is_active`, `created_by_id`, `updated_by_id`, `created_at`

---

## Business rules

- `editable_until = created_at + 3 days` — PUT invitation returns 403 after that
- Public `/invite/{slug}` returns 404 if `is_paid=False` OR `status != published`
- RSVP dedup: same `guest_phone` = update existing response (no Redis)
- RSVP rate limit: max 5 per IP per hour (DB count query, no Redis)
- Login lockout: 5 failed attempts → 30-minute lock stored in DB
- Wishes: shown on the public page only when the guest sent `wish_public=true` AND the host approved (`wish_visible`); editing the message or withdrawing consent clears approval
- Invitees: personal link `/invite/{slug}?g={token}`; tokens are stored in plain text (hosts re-copy links; a token only reveals the guest's name); max 1000 per invitation
- RSVP input limits: `guest_name` 1–255, `guest_phone` ≤ 20, `guest_count` 0–20 (0 for declines), `message` ≤ 1000
- Payment flow: user creates payment → manually transfers via Kaspi app → admin confirms → invitation published, `is_paid=True`, `expires_at` set from plan

---

## File storage

- User media: `media/uploads/{invitation_id}/{uuid}.ext` served at `/media/uploads/...`
- Thumbnails: `media/thumbs/{invitation_id}/{uuid}.ext` served at `/media/thumbs/...`
- Template images: `media/templates/{uuid}.ext` served at `/media/templates/...`
- All under `app.mount("/media", StaticFiles(directory="media"))` in `main.py`
- Directories auto-created at startup from `settings.MEDIA_DIR`, `MEDIA_THUMBS_DIR`, `TEMPLATES_DIR`

---

## Config (`.env` file required)

```env
DATABASE_URL=postgresql+asyncpg://inv_admin:Invitation08022026@localhost:5432/invitation_db
JWT_SECRET_KEY=your-secret-key
GROQ_API_KEY=your-groq-key
# Optional
FRONTEND_URL=
FRONTEND_VERCEL=http://localhost:3000
FRONTEND_HOSTING=https://www.invitation.kz/
CORS_ORIGINS=
PAYMENT_KASPI_PHONE=+77001234567
```

---

## Logging

- `setup_logging(settings.LOGS_DIR)` called in `main.py` before app creation
- Daily rotating files: `logs/app.log.YYYY-MM-DD` (30-day retention)
- Per module: `logger = get_logger("module_name")` → logger named `invitation_app.module_name`
- Log: all auth events, invitation CRUD, media uploads, RSVP, payments, admin actions

---

## Migrations history

| Revision | Description |
|---|---|
| `c79e292181cf` | initial users table |
| `a1b2c3d4e5f6` | add locked_until to users |
| `b1c2d3e4f5g6` | add full_name, is_admin to users |
| `c2d3e4f5g6h7` | add all platform tables (invitations, templates, categories, media, rsvp, payments) |
| `936c8932f68d` | after lock features |
| `d3e4f5g6h7i8` | add audit fields (created_by_id, updated_by_id) |
| `f5g6h7i8j9k0` | add description, images to templates; make preview_url nullable |
| `g6h7i8j9k0l1` | template lifecycle, revisions, preview sessions |
| `h7i8j9k0l1m2` | RSVP wishes: `wish_public`, `wish_visible` |
| `i8j9k0l1m2n3` | `rsvp_invitees` + `rsvp_responses.invitee_id` |

---

## Code patterns used throughout

```python
# Async DB query pattern
result = await db.execute(select(Model).where(Model.id == some_id))
obj = result.scalar_one_or_none()
if not obj:
    raise HTTPException(404, "Не найдено")

# Partial update pattern (used in PUT/PATCH)
for field, value in data.model_dump(exclude_none=True).items():
    setattr(obj, field, value)
await db.commit()
await db.refresh(obj)

# Auth dependency
current_user: User = Depends(get_current_user)    # any logged-in user
admin: User = Depends(get_current_admin_user)      # is_admin=True required

# Logger per module
logger = get_logger("module_name")
logger.info("Action: param=%s", value)
```

---

## Git

- Branch: `master` (main working branch)
- Remote: `https://github.com/NurlanNNG/InvitationProject`
- Collaborator: Dikong1 (frontend, also contributed CORS config and README)
- Never commit `__pycache__/`, `.pyc`, `.idea/`, `.venv/`, `.env` (covered by `.gitignore`)
