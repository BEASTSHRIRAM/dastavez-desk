from fastapi.testclient import TestClient

from app.main import app
from app.verticals import WORKSPACES

client = TestClient(app)


def login(email: str = "operator@demo.test", password: str = "demo-pass") -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def new_case(h: dict, workspace: str, text: str | None = None, **kw) -> dict:
    r = client.post("/api/cases", json={"workspace": workspace, **kw}, headers=h)
    assert r.status_code == 201, r.text
    case = r.json()
    r = client.post(f"/api/cases/{case['id']}/intake", json={"transcript": text or WORKSPACES[workspace].example_prompt},
                    headers=h)
    assert r.status_code == 202, r.text
    return client.get(f"/api/cases/{case['id']}", headers=h).json()


def manifest(h: dict, case_id: str, view: str | None = None) -> dict:
    r = client.get(f"/api/cases/{case_id}/manifest", params={"view": view} if view else None, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def components(m: dict, kind: str | None = None) -> list[dict]:
    out = [c for s in m["sections"] for c in s["components"]]
    return [c for c in out if kind is None or c["component"] == kind]


def asked_fields(m: dict) -> list[str]:
    return [c["field_id"] for c in components(m) if "field_id" in c and not c.get("optional")
            and c["component"] not in ("source_evidence", "conflict_choice")]


def answer(h: dict, case_id: str, answers: dict, **kw):
    return client.post(f"/api/cases/{case_id}/answers", json={"answers": answers, **kw}, headers=h)


def confirm_list(m: dict) -> list[str]:
    panel = components(m, "approval_panel")[0]
    return [f["field_id"] for f in panel["confirm_fields"]]


def approve(h: dict, case_id: str):
    m = manifest(h, case_id)
    r = client.post(f"/api/cases/{case_id}/approve", json={"confirm": confirm_list(m)}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()
