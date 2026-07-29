# Public template API

## List published templates

`GET /api/v1/templates`

Returns only templates satisfying all three conditions:

- `status == "published"`
- `is_active == true`
- `published_revision_id` is not null

The optional `category` query parameter continues to filter by category slug.
Results remain ordered by `sort_order`.

`config` is loaded from the published immutable revision. A newer admin draft is
never returned. Existing response fields remain present; these publication fields
are also returned:

```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "name_kk": "Үйлену тойы",
  "name_ru": "Свадьба",
  "category_id": 1,
  "preview_url": "https://cdn.example.com/preview.jpg",
  "thumbnail_url": "https://cdn.example.com/thumbnail.jpg",
  "images": [],
  "config": {
    "layout": {
      "sections": ["hero", "schedule", "venue"],
      "custom": {"unknownKey": true}
    }
  },
  "is_premium": false,
  "is_active": true,
  "sort_order": 0,
  "published_revision_id": "62ab8a75-7e2a-45f3-bc22-8f961882a2ce",
  "published_revision_number": 3,
  "created_at": "2026-07-01T10:00:00Z",
  "created_by_id": 1,
  "updated_by_id": 1
}
```

Draft identifiers, latest revision identifiers, unpublished-change flags, and
unpublished config are not included.

## Get a published template

`GET /api/v1/templates/{template_id}`

Uses the same response and publication rules as the list endpoint. Draft,
archived, inactive, and missing templates all return `404`.

## Read a temporary preview

`GET /api/v1/template-previews/{preview_id}?token={opaque_token}`

This public endpoint returns the immutable preview snapshot created by an admin:

```json
{
  "preview_id": "f6802992-32f4-45eb-8910-5896935d2967",
  "template_id": "123e4567-e89b-12d3-a456-426614174000",
  "revision_id": null,
  "config": {"unsaved": {"preserved": [1, true, null]}},
  "locale": "ru",
  "sample_data": {"title": "Алия и Данияр"},
  "expires_at": "2026-07-29T12:30:00Z"
}
```

The token is required. Invalid tokens return `404`; expired or revoked previews
return `410`. Preview access does not publish or modify a template.
