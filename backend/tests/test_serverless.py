"""Serverless readiness: durable file storage, no SQLite on Vercel, and the workflow running inside the request."""
import shutil
from pathlib import Path

import httpx
import pytest
from fastapi import BackgroundTasks

from app import db
from app.config import get_settings, normalize_db_url
from app.services import storage
from tests.helpers import client, login, new_case

DOCX = b"PK\x03\x04 pretend this is a docx"
TENANT_A, TENANT_B = "a" * 32, "b" * 32


class FakeResponse:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


class FakeSupabase:
    """An in-memory stand-in for Supabase Storage's REST API."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.buckets_created = 0
        self.fail = False

    def post(self, url, headers=None, json=None, content=None, **kw):
        if self.fail:
            raise httpx.ConnectError("down")
        assert headers["Authorization"].startswith("Bearer ") and headers["apikey"]  # the service key is sent server-side only
        if url.endswith("/bucket"):
            self.buckets_created += 1
            return FakeResponse(200 if self.buckets_created == 1 else 409)
        self.objects[url.split("/object/", 1)[1]] = content
        return FakeResponse(200)

    def get(self, url, headers=None, **kw):
        if self.fail:
            raise httpx.ConnectError("down")
        data = self.objects.get(url.split("/object/authenticated/", 1)[1])
        return FakeResponse(200, data) if data is not None else FakeResponse(404)

    def request(self, method, url, headers=None, json=None, **kw):
        assert method == "DELETE"
        for prefix in json["prefixes"]:
            self.objects.pop(f"{get_settings().supabase_bucket}/{prefix}", None)
        return FakeResponse(200)


@pytest.fixture
def remote(monkeypatch):
    fake = FakeSupabase()
    s = get_settings()
    monkeypatch.setattr(s, "supabase_url", "https://example.supabase.co")
    monkeypatch.setattr(s, "supabase_service_key", "service-key")
    monkeypatch.setattr(storage, "_bucket_ready", False)
    monkeypatch.setattr(storage.httpx, "post", fake.post)
    monkeypatch.setattr(storage.httpx, "get", fake.get)
    monkeypatch.setattr(storage.httpx, "request", fake.request)
    return fake


def local_copy(tenant, kind, stored) -> Path:
    return get_settings().storage_dir / tenant / kind / stored


def test_a_file_written_on_one_instance_is_restored_on_another(remote):
    stored = storage.save_bytes(TENANT_A, "files", DOCX, ".docx")
    assert remote.objects[f"dastavez/{TENANT_A}/files/{stored}"] == DOCX and remote.buckets_created == 1
    local_copy(TENANT_A, "files", stored).unlink()  # a cold instance: nothing on local disk
    restored = storage.resolve(TENANT_A, "files", stored)
    assert restored.read_bytes() == DOCX and restored.exists()


def test_files_written_through_new_path_are_mirrored_on_commit(remote):
    stored, path = storage.new_path(TENANT_A, "documents", ".docx")
    path.write_bytes(DOCX)
    assert remote.objects == {}  # not durable until the caller says the file is complete
    storage.commit(TENANT_A, "documents", stored)
    assert remote.objects[f"dastavez/{TENANT_A}/documents/{stored}"] == DOCX


def test_another_business_cannot_restore_a_file_by_name(remote):
    stored = storage.save_bytes(TENANT_A, "files", DOCX, ".docx")
    with pytest.raises(FileNotFoundError):
        storage.resolve(TENANT_B, "files", stored)  # different tenant folder and bucket key: simply not found


def test_deleting_removes_the_durable_copy_too(remote):
    stored = storage.save_bytes(TENANT_A, "files", DOCX, ".docx")
    storage.delete(TENANT_A, "files", stored)
    assert remote.objects == {} and not local_copy(TENANT_A, "files", stored).exists()
    with pytest.raises(FileNotFoundError):
        storage.resolve(TENANT_A, "files", stored)


@pytest.mark.parametrize("name", ["../x.docx", "..\\x.docx", "a/b.docx", "ABC.docx", "x" * 32 + ".exe.docx", "", "short.docx"])
def test_only_server_generated_names_can_be_resolved(remote, name):
    with pytest.raises(FileNotFoundError):
        storage.resolve(TENANT_A, "files", name)


def test_a_storage_outage_is_a_clear_503_not_a_crash(remote):
    h = login()
    case = new_case(h, "property", "The tenant is Rahul Sharma.")
    remote.fail = True
    r = client.post(f"/api/cases/{case['id']}/attachments", files={"file": ("n.txt", b"notes", "text/plain")}, headers=h)
    assert r.status_code == 503 and "not reachable" in r.json()["detail"]


def test_without_remote_storage_nothing_is_sent_anywhere(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no network call expected")
    monkeypatch.setattr(storage.httpx, "post", boom)
    stored = storage.save_bytes(TENANT_A, "files", DOCX, ".docx")
    assert storage.resolve(TENANT_A, "files", stored).read_bytes() == DOCX
    shutil.rmtree(get_settings().storage_dir / TENANT_A, ignore_errors=True)


# ------------------------------------------------------------------ hosting rules
def test_sqlite_is_refused_on_vercel_with_a_message_that_says_what_to_do(monkeypatch):
    monkeypatch.setattr(db, "ON_VERCEL", True)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db.make_engine("sqlite:///x.db")
    monkeypatch.setattr(db, "ON_VERCEL", False)
    assert db.make_engine("sqlite:///x.db").dialect.name == "sqlite"


def test_the_workflow_runs_inside_the_request_when_background_tasks_cannot_be_trusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "workflow_inline", True)

    def forbidden(*a, **k):
        raise AssertionError("a background task would be frozen on serverless")
    monkeypatch.setattr(BackgroundTasks, "add_task", forbidden)
    h = login()
    case = client.post("/api/cases", json={"workspace": "property"}, headers=h).json()
    r = client.post(f"/api/cases/{case['id']}/intake", json={"transcript": "The tenant is Rahul Sharma, rent is 18000."}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "awaiting_input"  # already finished when the response returns


def test_database_urls_pasted_from_supabase_are_accepted():
    assert normalize_db_url("postgres://u:p@h.pooler.supabase.com:6543/postgres").endswith("?sslmode=require")
