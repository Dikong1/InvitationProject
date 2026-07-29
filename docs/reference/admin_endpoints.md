# Admin template API

All endpoints require an authenticated user with `is_admin=true`. Missing
authentication returns `401`; authenticated non-admin users receive `403`.

Template `config` is opaque. Any JSON object, including `{}`, is accepted and
returned without key normalization, default insertion, or value coercion. A
top-level array, scalar, or `null` returns `422`.

## Lifecycle

- `draft`: never published and unavailable publicly.
- `published`: has a published revision. A newer editable revision may also
  exist.
- `archived`: unavailable publicly and not editable until restored.
- `is_active` remains independent. Public visibility requires `published`,
  `is_active=true`, and a non-null published revision.

The complete admin representation contains the existing catalogue fields plus:

| Field | Type | Meaning |
|---|---|---|
| `status` | `draft \| published \| archived` | Current lifecycle state |
| `latest_revision_id` | UUID | Latest editable revision |
| `published_revision_id` | UUID or null | Revision exposed publicly |
| `latest_revision_number` | integer | Monotonic latest revision number |
| `published_revision_number` | integer or null | Published revision number |
| `has_unpublished_changes` | boolean | A published template has a newer draft |

The top-level admin `config` is always the latest editable config.

## List templates

`GET /api/v1/admin/templates`

Returns drafts, published templates, inactive templates, and archived templates.
Results sort by `sort_order ASC`, then `created_at DESC`.

Query parameters:

| Parameter | Type | Notes |
|---|---|---|
| `status` | string | `draft`, `published`, or `archived` |
| `category_id` | integer | Exact category match |
| `is_active` | boolean | Exact active-state match |
| `search` | string | Case-insensitive match against `name_kk` or `name_ru` |
| `limit` | integer | Default `100`, range `1..200` |
| `offset` | integer | Default `0` |

## Get a template

`GET /api/v1/admin/templates/{template_id}`

Returns the complete admin representation. Missing templates return `404`.

## Create a draft

`POST /api/v1/admin/templates`

The request remains `multipart/form-data` for compatibility:

| Field | Type | Required |
|---|---|---|
| `name_kk` | string | yes |
| `name_ru` | string | yes |
| `category_id` | integer | no |
| `description` | string | no |
| `config` | JSON object encoded as a string | no; defaults to `{}` |
| `is_premium` | boolean | no; defaults to `false` |
| `is_active` | boolean | no; defaults to `true` |
| `sort_order` | integer | no; defaults to `0` |
| `preview` | JPEG, PNG, or WebP file | no |
| `thumbnail` | JPEG, PNG, or WebP file | no |
| `images` | repeated image files | no |

Image files are limited to 10 MB each. The response is `201`. Creation produces
revision `1` in `draft` state and does not make the template public.

Example `config` form value:

```json
{
  "theme": {"palette": ["#112233", "#f8f4ed"]},
  "blocks": [
    {"type": "hero", "props": {"align": "center", "showDate": true}},
    {"type": "custom-widget", "props": {"unknown": [1, null, "kept"]}}
  ]
}
```

## Update metadata or config

`PUT /api/v1/admin/templates/{template_id}`

The JSON request accepts all mutable catalogue fields plus:

```json
{
  "base_revision_number": 3,
  "name_ru": "Обновлённый шаблон",
  "config": {
    "arbitrary": {
      "nested": ["configuration", 4, true, null]
    }
  }
}
```

- Omitted fields are preserved.
- Metadata-only edits do not create revisions.
- A different `config` creates the next immutable revision.
- An identical `config` does not create a duplicate revision.
- `base_revision_number` is optional. A stale value returns `409` with
  `current_revision_number`.
- Archived templates return `409` until restored.
- Updating a published template does not change its public config until publish.

The existing image-management routes remain:

- `POST /api/v1/admin/templates/{template_id}/preview-image`
- `POST /api/v1/admin/templates/{template_id}/images`
- `DELETE /api/v1/admin/templates/{template_id}/images/{image_index}`

## Publish

`POST /api/v1/admin/templates/{template_id}/publish`

Publishes the latest revision, records publication audit data, clears
`has_unpublished_changes`, and sets status to `published`. Publishing the already
published latest revision is idempotent. Archived templates return `409`.

## Archive and restore

- `POST /api/v1/admin/templates/{template_id}/archive`
- `POST /api/v1/admin/templates/{template_id}/restore`

Archive hides the template immediately without deleting revisions or its
published pointer. Restore returns to `published` when a published revision
exists; otherwise it returns to `draft`. Restore does not change `is_active`.
Restoring a non-archived template returns `409`.

## Revision history

`GET /api/v1/admin/templates/{template_id}/revisions`

Returns newest first. Each summary contains `id`, `template_id`,
`revision_number`, creation/publication audit fields, `is_latest`, and
`is_published`.

`GET /api/v1/admin/templates/{template_id}/revisions/{revision_id}`

Returns the same fields plus the exact immutable `config`. A revision belonging
to another template returns `404`.

## Temporary preview

`POST /api/v1/admin/templates/{template_id}/preview`

All fields are optional:

```json
{
  "config": {
    "blocks": [{"type": "experimental", "props": {"enabled": true}}]
  },
  "locale": "ru",
  "sample_data": {
    "title": "Алия и Данияр",
    "event_date": "2026-09-12",
    "venue_name": "The Garden Hall"
  }
}
```

When `config` is omitted, the saved latest revision is snapshotted. When it is
present, the unsaved config is snapshotted without creating a revision. The
response is `201`:

```json
{
  "preview_id": "f6802992-32f4-45eb-8910-5896935d2967",
  "template_id": "123e4567-e89b-12d3-a456-426614174000",
  "revision_id": null,
  "preview_url": "https://api.example.com/api/v1/template-previews/f6802992-32f4-45eb-8910-5896935d2967?token=opaque-token",
  "expires_at": "2026-07-29T12:30:00Z"
}
```

The default lifetime is 30 minutes, configurable with
`TEMPLATE_PREVIEW_EXPIRE_MINUTES` and constrained to 15–60 minutes. The URL
contains a random preview token, never an admin credential. The database stores
only its SHA-256 hash.

## Delete

`DELETE /api/v1/admin/templates/{template_id}`

Hard delete is allowed only for a never-published draft that no invitation
references. Published or referenced templates return `409` and must be archived.

## Errors

| Status | Meaning |
|---|---|
| `401` | Missing or invalid authentication |
| `403` | Authenticated user is not an administrator |
| `404` | Template or revision not found |
| `409` | Invalid lifecycle transition, stale revision, or forbidden hard delete |
| `422` | Invalid request shape or top-level non-object `config` |
