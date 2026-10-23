# Changelog

This file is used for tracking releases in `master`.

Rule: before each deploy merge and after each master-build add new record on the top. Write not only "what committed", but what was actually changed in the application, which version released and which checks were passed.

The developer-facing change list in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format stays in the root `CHANGELOG.md`.

## Record template

```md
## YYYY-MM-DD - X.Y.Z master build

Release version: `X.Y.Z`
Commit/merge range: `<from>` -> `<to>`
Build owner: `<name>` (Dias or Nurlan)

### Changes

...

### Technical changes

...

```

## Unreleased

## 2026-10-23 - 1.2.0 master build

Release version: `1.2.0`
Commit/merge range: `cc59ae1` -> `16874d3`
Build owner: `Dias`

### Changes

- Guests now see the host's extra RSVP questions on the invitation page. They were saved before but never returned publicly.
- Wishes wall: a guest can choose to show their message on the invitation. It appears only after the host approves it, and needs approval again if the guest edits it.
- Guest list with personal links: hosts add guests (up to 1000 per invitation) and each gets a personal link. The link greets the guest by name and ties their RSVP to them, and the guest summary shows how many invited guests have not answered yet.
- Activity feed of recent RSVPs across all of a host's invitations, flagging wishes that wait for approval.
- AI invitation text can follow a tone (formal, warm, fun, poetic) and return up to 3 variants. Existing clients keep working unchanged.
- RSVP input is limited to the database column sizes: name 1–255 characters, phone up to 20, guest count 0–20 (0 when declining), message up to 1000.

### Technical changes

- Migrations `h7i8j9k0l1m2` (`rsvp_responses.wish_public`, `wish_visible` and an index) and `i8j9k0l1m2n3` (`rsvp_invitees` table, `rsvp_responses.invitee_id`). Run `python -m alembic upgrade head` before starting the app; the head is `i8j9k0l1m2n3`.
- New endpoints: `PATCH /api/v1/my/invitations/{id}/guests/{response_id}`, `GET/POST/DELETE /api/v1/my/invitations/{id}/invitees`, `GET /api/v1/my/activity`. `GET /api/v1/invite/{slug}` accepts `?g=<token>` and returns `questions`, `wishes` and `invitee`.
- New router `app/rsvp/invitees_router.py`; shared owner check `get_owned_invitation()` in `app/invitations/utils.py`.
- AI variants are parallel Groq calls, since Groq supports only `n=1`. The response adds `texts`; `text` stays the first variant.
- Invitee tokens are stored in plain text (unlike template preview tokens) so hosts can copy links again; a token only reveals the guest's name.
- Docs updated: `FRONTEND_API.md`, `CLAUDE.md`, `CHANGELOG.md`.
- Checks: 21 pytest tests pass with `TEST_DATABASE_URL` set (14 pass and 7 skip without it). Migrations upgraded from an empty PostgreSQL 16 database, downgraded two revisions and upgraded again. Manual uvicorn run with real login cookies through the whole guest flow. `alembic check` reports only the existing `invitation_details` unique-constraint difference.

## 2026-07-29 - 1.1.0 master build

Release version: `1.1.0`
Commit/merge range: `cfa2cfe` -> `0725c5f`
Build owner: `Dias`

### Changes

- Templates have a lifecycle: draft, published and archived, with explicit publish, archive and restore.
- Edits to a published template stay private until it is republished. The public catalogue shows only active, published templates.
- Admins can list, search, filter and page templates and browse each template's revision history.
- Short-lived preview links for saved and unsaved template designs.
- Templates have a description and an image gallery; admin template create and edit use file uploads.
- Admin PATCH endpoints for templates and categories.
- Frontend URLs and CORS origins are configurable in settings, and the hosting domain is allowed.

### Technical changes

- Immutable, numbered template revisions with optional optimistic concurrency checks (`base_revision_number`).
- The preview-image upload moved from `POST /api/v1/admin/templates/{id}/preview` to `/preview-image`; `/preview` now creates a temporary preview session.
- Migrations `f5g6h7i8j9k0` (template description and images, nullable `preview_url`) and `g6h7i8j9k0l1` (`templatestatus` enum, `template_revisions`, `template_previews`; existing templates backfilled as revision 1).
- New setting `TEMPLATE_PREVIEW_EXPIRE_MINUTES` (15–60, default 30).
- `CLAUDE.md` project context and admin/public template API reference docs added.
- Checks: 8 automated tests pass; OpenAPI generation has no duplicate routes; Alembic reports `g6h7i8j9k0l1` as head.
