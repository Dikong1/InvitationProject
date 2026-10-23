# Changelog

All notable changes to the Invitation Platform API are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.2.0] - 2026-10-23: 16874d381492d60ac61a661bb72f87269eb4d6da

### Added

- Public invitation responses include the host's RSVP `questions`, approved
  guest `wishes`, and an `invitee` greeting when opened with a personal
  link (`?g=<token>`).
- Wishes wall: guests can opt in with `wish_public`; hosts approve or hide
  each wish via `PATCH /api/v1/my/invitations/{id}/guests/{response_id}`.
- Guest list with personal links:
  `GET/POST/DELETE /api/v1/my/invitations/{id}/invitees`. RSVPs sent with
  `invitee_token` are linked to the guest, and the guests summary reports
  `invited_count` and `pending`.
- Activity feed of recent RSVPs across a user's invitations:
  `GET /api/v1/my/activity`.
- AI text generation accepts `tone` and `variants` (1–3) and returns
  `texts` alongside `text`.
- Migrations `h7i8j9k0l1m2` (wishes) and `i8j9k0l1m2n3` (invitees).
- Database-backed API tests, run when `TEST_DATABASE_URL` is set.

### Changed

- RSVP input is validated against the column limits (`guest_name` 1–255,
  `guest_phone` ≤ 20, `guest_count` 0–20, `message` ≤ 1000) and stripped.

## [1.1.0] - 2026-07-29: 0725c5f7641d716962ec5a352c53762b415d0c67

### Added

- Admin template list and detail endpoints with filtering, search, and pagination.
- Draft, published, and archived template lifecycle states.
- Immutable, monotonically numbered template revisions.
- Explicit template publish, archive, and restore operations.
- Revision list and detail endpoints with creation and publication audit fields.
- Optional optimistic concurrency checks through `base_revision_number`.
- Short-lived template preview sessions for saved and unsaved configurations.
- Public, token-protected preview snapshot endpoint.
- Configurable preview lifetime through `TEMPLATE_PREVIEW_EXPIRE_MINUTES`, constrained
  to 15–60 minutes and defaulting to 30 minutes.
- Automated tests covering configuration preservation, authorization, revision
  visibility, lifecycle transitions, preview tokens, expiry, and OpenAPI routes.
- Admin and public template API reference documentation.

### Changed

- Public template list and detail endpoints now return only active, published
  templates with a valid published revision.
- Public template responses read `config` from the published revision, preventing
  unpublished changes from leaking.
- Admin template responses expose the latest editable `config` and lifecycle
  summary fields:
  - `status`
  - `latest_revision_id`
  - `published_revision_id`
  - `latest_revision_number`
  - `published_revision_number`
  - `has_unpublished_changes`
- Updating a template with a changed `config` creates a new immutable revision.
- Updating metadata without changing `config` does not create a revision.
- Published-template edits remain private until explicitly republished.
- Hard deletion is restricted to never-published, unreferenced drafts.
- The template preview-image upload endpoint moved from
  `POST /api/v1/admin/templates/{template_id}/preview` to
  `POST /api/v1/admin/templates/{template_id}/preview-image`.
- `POST /api/v1/admin/templates/{template_id}/preview` now creates a temporary
  JSON preview session.

### Database

- Added the `templatestatus` PostgreSQL enum.
- Added lifecycle and revision-summary columns to `invitation_templates`.
- Added the `template_revisions` table for immutable configuration snapshots.
- Added the `template_previews` table for expiring preview snapshots and hashed
  access tokens.
- Added Alembic revision `g6h7i8j9k0l1`.
- Existing templates are backfilled without changing their UUIDs:
  - Existing `config` becomes revision `1`.
  - Revision `1` becomes the latest and published revision.
  - Existing `is_active` values are preserved.
  - Existing catalogue metadata and audit fields are preserved.

### Compatibility

- Existing multipart template-create payloads remain supported.
- Existing template catalogue fields remain available.
- The parent template `config` column remains as a compatibility mirror of the
  latest revision.
- Unknown configuration keys and nested JSON values are preserved exactly.
- Top-level non-object configuration values are rejected with HTTP `422`.

### Deployment

Apply all pending migrations before starting the updated application:

```powershell
python -m alembic upgrade head
```

Verify that the database reports:

```text
g6h7i8j9k0l1 (head)
```

### Verification

- 8 automated tests pass.
- Application, migration, and test modules compile successfully.
- OpenAPI generation completes without duplicate method/path routes.
- Alembic identifies `g6h7i8j9k0l1` as the migration head.
