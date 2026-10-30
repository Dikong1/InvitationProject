"""
File storage for uploads (invitation photos, thumbnails, template images).

Two backends, chosen by STORAGE_BACKEND:
- "local" (default): files under MEDIA_DIR / MEDIA_THUMBS_DIR / TEMPLATES_DIR, served by the
  /media static mount. Fine for development, but Render's free tier wipes the disk on every
  deploy and restart, so production must not use it.
- "s3": any S3-compatible bucket (Cloudflare R2 in production). Files are public objects and
  the database stores their absolute public URL.

Keys look like "uploads/<invitation_id>/<file>", "thumbs/<invitation_id>/<file>" and
"templates/<file>", the same layout the local mount always used.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("storage")

# One year: every stored file gets a fresh uuid name, so a URL never changes content.
CACHE_CONTROL = "public, max-age=31536000, immutable"


class Storage(Protocol):
    async def save(self, key: str, data: bytes, content_type: str) -> str:
        """Stores the file and returns the URL saved in the database."""

    async def delete(self, url: Optional[str]) -> None:
        """Removes a file this storage created. Other URLs are ignored."""


class LocalStorage:
    def __init__(self, base_url: str = settings.MEDIA_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.roots = {
            "uploads": Path(settings.MEDIA_DIR),
            "thumbs": Path(settings.MEDIA_THUMBS_DIR),
            "templates": Path(settings.TEMPLATES_DIR),
        }

    def _path(self, key: str) -> Optional[Path]:
        prefix, _, rest = key.partition("/")
        root = self.roots.get(prefix)
        if root is None or not rest:
            return None
        path = (root / rest).resolve()
        # Never touch anything outside the storage folders.
        return path if path.is_relative_to(root.resolve()) else None

    async def save(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        if path is None:
            raise ValueError(f"Unknown storage key: {key}")
        path.parent.mkdir(parents=True, exist_ok=True)
        await run_in_threadpool(path.write_bytes, data)
        return f"{self.base_url}/{key}"

    async def delete(self, url: Optional[str]) -> None:
        if not url or not url.startswith(f"{self.base_url}/"):
            return
        path = self._path(url[len(self.base_url) + 1:])
        if path is not None and path.exists():
            await run_in_threadpool(path.unlink)


class S3Storage:
    def __init__(self, client, bucket: str, public_base_url: str):
        self.client = client
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/")

    async def save(self, key: str, data: bytes, content_type: str) -> str:
        await run_in_threadpool(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=CACHE_CONTROL,
        )
        return f"{self.public_base_url}/{key}"

    async def delete(self, url: Optional[str]) -> None:
        if not url or not url.startswith(f"{self.public_base_url}/"):
            return
        key = url[len(self.public_base_url) + 1:]
        await run_in_threadpool(self.client.delete_object, Bucket=self.bucket, Key=key)


S3_SETTINGS = ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET", "S3_PUBLIC_BASE_URL")


def build_storage() -> Storage:
    backend = settings.STORAGE_BACKEND.strip().lower()
    if backend == "local":
        return LocalStorage()
    if backend != "s3":
        raise RuntimeError(f"STORAGE_BACKEND must be 'local' or 's3', got {settings.STORAGE_BACKEND!r}")
    missing = [name for name in S3_SETTINGS if not getattr(settings, name)]
    if missing:
        raise RuntimeError(f"STORAGE_BACKEND=s3 needs these settings: {', '.join(missing)}")

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )
    logger.info("Using S3 storage: bucket=%s public=%s", settings.S3_BUCKET, settings.S3_PUBLIC_BASE_URL)
    return S3Storage(client, settings.S3_BUCKET, settings.S3_PUBLIC_BASE_URL)


@lru_cache
def get_storage() -> Storage:
    return build_storage()
