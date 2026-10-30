Deployed on Render at https://invitationproject-8uku.onrender.com
Frontend available at https://www.invitation.kz

## Deploying on Render

- **Start command:** `bash start.sh`. It runs `alembic upgrade head` before starting uvicorn, so every deploy brings the Neon schema up to date.
- **Uploads:** Render's disk is wiped on every deploy and restart, so production keeps files in Cloudflare R2. Set these environment variables:

  | Variable | Value |
  |---|---|
  | `STORAGE_BACKEND` | `s3` |
  | `S3_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
  | `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | an R2 API token with Object Read & Write on the bucket |
  | `S3_BUCKET` | the bucket name, e.g. `invitely-media` |
  | `S3_PUBLIC_BASE_URL` | the bucket's public URL: `https://pub-<id>.r2.dev` or a custom domain |

  The app refuses to start if `STORAGE_BACKEND=s3` is set and any of these is missing. Locally, leave `STORAGE_BACKEND` unset to keep files under `media/`.
