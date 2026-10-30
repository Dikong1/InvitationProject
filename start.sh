#!/usr/bin/env bash
# Render start command: `bash start.sh`.
# Applies pending database migrations before serving, so a deploy can never run new code
# against an old schema (1.2.0 shipped without its tables and broke every public page).
set -euo pipefail
python -m alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
