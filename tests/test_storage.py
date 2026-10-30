import asyncio
import io
import uuid
from types import SimpleNamespace

import boto3
import pytest
from botocore.stub import ANY, Stubber
from fastapi import UploadFile
from PIL import Image

from app import storage as storage_module
from app.admin import router as admin_router
from app.media import router as media_router
from app.storage import CACHE_CONTROL, LocalStorage, S3Storage, build_storage


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def local_dirs(tmp_path, monkeypatch):
    for name, folder in [("MEDIA_DIR", "uploads"), ("MEDIA_THUMBS_DIR", "thumbs"), ("TEMPLATES_DIR", "templates")]:
        monkeypatch.setattr(storage_module.settings, name, str(tmp_path / folder))
    return tmp_path


def png_bytes(size=(800, 600)):
    out = io.BytesIO()
    Image.new("RGB", size, "#c08040").save(out, format="PNG")
    return out.getvalue()


class TestLocalStorage:
    def test_saves_under_the_configured_folders_and_returns_media_url(self, local_dirs):
        store = LocalStorage("/media")
        url = run(store.save("uploads/inv-1/a.png", b"data", "image/png"))
        assert url == "/media/uploads/inv-1/a.png"
        assert (local_dirs / "uploads" / "inv-1" / "a.png").read_bytes() == b"data"

    def test_deletes_only_its_own_files(self, local_dirs):
        store = LocalStorage("/media")
        url = run(store.save("templates/t.png", b"x", "image/png"))
        run(store.delete("https://elsewhere.example/templates/t.png"))
        assert (local_dirs / "templates" / "t.png").exists()
        run(store.delete(url))
        assert not (local_dirs / "templates" / "t.png").exists()
        run(store.delete(None))

    def test_refuses_keys_outside_the_storage_folders(self, local_dirs):
        store = LocalStorage("/media")
        with pytest.raises(ValueError):
            run(store.save("../etc/passwd", b"x", "text/plain"))
        with pytest.raises(ValueError):
            run(store.save("uploads/../../escape.txt", b"x", "text/plain"))
        run(store.delete("/media/uploads/../../escape.txt"))


class TestS3Storage:
    def make(self):
        client = boto3.client(
            "s3", endpoint_url="https://acc.r2.cloudflarestorage.com", region_name="auto",
            aws_access_key_id="k", aws_secret_access_key="s",
        )
        return client, S3Storage(client, "invitely-media", "https://media.invitation.kz/")

    def test_uploads_public_objects_and_returns_the_public_url(self):
        client, store = self.make()
        with Stubber(client) as stub:
            stub.add_response("put_object", {}, {
                "Bucket": "invitely-media", "Key": "uploads/inv-1/a.png", "Body": ANY,
                "ContentType": "image/png", "CacheControl": CACHE_CONTROL,
            })
            url = run(store.save("uploads/inv-1/a.png", b"data", "image/png"))
            stub.assert_no_pending_responses()
        assert url == "https://media.invitation.kz/uploads/inv-1/a.png"

    def test_deletes_by_key_and_ignores_foreign_urls(self):
        client, store = self.make()
        with Stubber(client) as stub:
            stub.add_response("delete_object", {}, {"Bucket": "invitely-media", "Key": "templates/t.png"})
            run(store.delete("https://media.invitation.kz/templates/t.png"))
            run(store.delete("/media/templates/old.png"))
            run(store.delete(None))
            stub.assert_no_pending_responses()


class TestBuildStorage:
    def test_defaults_to_local(self, monkeypatch):
        monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "local")
        assert isinstance(build_storage(), LocalStorage)

    def test_s3_needs_every_setting(self, monkeypatch):
        monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "s3")
        for name in storage_module.S3_SETTINGS:
            monkeypatch.setattr(storage_module.settings, name, "")
        monkeypatch.setattr(storage_module.settings, "S3_BUCKET", "invitely-media")
        with pytest.raises(RuntimeError, match="S3_ENDPOINT_URL"):
            build_storage()

    def test_s3_when_configured(self, monkeypatch):
        values = {
            "STORAGE_BACKEND": "S3", "S3_ENDPOINT_URL": "https://acc.r2.cloudflarestorage.com", "S3_ACCESS_KEY_ID": "k",
            "S3_SECRET_ACCESS_KEY": "s", "S3_BUCKET": "invitely-media", "S3_PUBLIC_BASE_URL": "https://pub-1.r2.dev",
        }
        for name, value in values.items():
            monkeypatch.setattr(storage_module.settings, name, value)
        store = build_storage()
        assert isinstance(store, S3Storage)
        assert store.public_base_url == "https://pub-1.r2.dev"

    def test_rejects_unknown_backends(self, monkeypatch):
        monkeypatch.setattr(storage_module.settings, "STORAGE_BACKEND", "ftp")
        with pytest.raises(RuntimeError):
            build_storage()


class FakeStorage:
    def __init__(self):
        self.saved = {}
        self.deleted = []

    async def save(self, key, data, content_type):
        self.saved[key] = (data, content_type)
        return f"https://cdn.test/{key}"

    async def delete(self, url):
        self.deleted.append(url)


def test_media_thumbnails_are_small_images_in_the_same_format():
    thumb = media_router._make_thumbnail(png_bytes())
    with Image.open(io.BytesIO(thumb)) as img:
        assert img.format == "PNG"
        assert max(img.size) <= 300
    assert media_router._make_thumbnail(b"not an image") is None


def test_template_uploads_go_to_storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(admin_router, "get_storage", lambda: fake)
    upload = UploadFile(io.BytesIO(png_bytes()), filename="Cover.PNG", headers={"content-type": "image/png"})
    url = run(admin_router._validate_and_save_upload(upload))
    [(key, (data, content_type))] = fake.saved.items()
    assert key.startswith("templates/") and key.endswith(".png")
    assert uuid.UUID(key[len("templates/"):-len(".png")])
    assert content_type == "image/png"
    assert url == f"https://cdn.test/{key}"


class FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.deleted = []

    async def execute(self, _query):
        value = self.results.pop(0)
        return SimpleNamespace(scalar_one_or_none=lambda: value, scalar=lambda: value)

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        pass

    async def refresh(self, item):
        pass

    async def rollback(self):
        pass

    async def delete(self, item):
        self.deleted.append(item)


def test_media_upload_stores_the_photo_and_its_thumbnail(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(media_router, "get_storage", lambda: fake)
    invitation_id = uuid.uuid4()
    invitation = SimpleNamespace(id=invitation_id, is_paid=False)
    db = FakeSession([invitation])
    upload = UploadFile(io.BytesIO(png_bytes()), filename="photo.png", headers={"content-type": "image/png"})
    user = SimpleNamespace(id=1, username="host")

    media = run(media_router.upload_media(invitation_id, file=upload, media_type=media_router.MediaType.photo,
                                          display_style=media_router.DisplayStyle.rectangle, caption=None,
                                          sort_order=0, current_user=user, db=db))
    keys = sorted(fake.saved)
    assert [key.split("/")[0] for key in keys] == ["thumbs", "uploads"]
    assert all(key.split("/")[1] == str(invitation_id) for key in keys)
    assert media.url == f"https://cdn.test/{keys[1]}"
    assert media.thumbnail_url == f"https://cdn.test/{keys[0]}"

    # Deleting the media removes both files from storage.
    db = FakeSession([invitation, media])
    run(media_router.delete_media(invitation_id, uuid.uuid4(), current_user=user, db=db))
    assert sorted(fake.deleted) == sorted([media.url, media.thumbnail_url])
    assert db.deleted == [media]
