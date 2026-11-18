import importlib
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from tests.make_packet import build

H = {"X-API-Key": "secret"}
MODULES = ("app.config", "app.db", "app.api.deps", "app.api.extractions", "app.api.registry", "app.api.templates", "app.api.workspaces", "app.main")


def reload_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_API_KEY", "secret")
    for name in MODULES:
        importlib.reload(importlib.import_module(name))
    from app import main
    return main.app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    with TestClient(reload_app(tmp_path, monkeypatch)) as c:
        yield c


@pytest.fixture()
def pdf(tmp_path):
    p = tmp_path / "p.pdf"
    build(str(p))
    return p


def mk(client, name="Team A", description=None):
    r = client.post("/api/workspaces", json={"name": name, **({"description": description} if description else {})}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def up(client, wid, pdf, choice="auto", name="packet.pdf"):
    return client.post(f"/api/workspaces/{wid}/extractions", files={"file": (name, pdf.read_bytes(), "application/pdf")}, data={"template": choice}, headers=H)


def wait(client, wid, eid):
    for _ in range(150):
        got = client.get(f"/api/workspaces/{wid}/extractions/{eid}", headers=H).json()
        if got["status"] in ("done", "failed"):
            return got
        time.sleep(0.1)
    raise AssertionError("extraction did not finish")


# ---- workspaces ---------------------------------------------------------------------------------------------------

def test_workspace_lifecycle(client):
    assert client.get("/api/workspaces").status_code == 401
    assert client.get("/api/workspaces", headers=H).json() == []
    assert client.post("/api/workspaces", json={"name": "   "}, headers=H).status_code == 422
    wid = mk(client, "Acme onboarding", "Vendor packets")
    dup = client.post("/api/workspaces", json={"name": "  acme ONBOARDING "}, headers=H)
    assert dup.status_code == 409 and "already have" in dup.json()["detail"]        # names are unique, ignoring case and spaces
    other = mk(client, "Beta")
    assert client.patch(f"/api/workspaces/{other}", json={"name": "Acme onboarding"}, headers=H).status_code == 409
    got = client.patch(f"/api/workspaces/{other}", json={"name": "Beta intake", "description": "Second client"}, headers=H).json()
    assert got["name"] == "Beta intake" and got["description"] == "Second client"
    assert client.patch(f"/api/workspaces/{wid}", json={"name": "Acme onboarding"}, headers=H).status_code == 200   # keeping its own name is fine
    row = client.get(f"/api/workspaces/{wid}", headers=H).json()
    assert row["documents"] == 0 and row["to_check"] == 0 and row["custom_types"] == 0 and row["description"] == "Vendor packets"
    assert client.get("/api/workspaces/nope", headers=H).status_code == 404
    assert {w["name"] for w in client.get("/api/workspaces", headers=H).json()} == {"Acme onboarding", "Beta intake"}


def test_workspaces_are_isolated(client, pdf):
    a, b = mk(client, "A"), mk(client, "B")
    eid = up(client, a, pdf).json()["id"]
    assert wait(client, a, eid)["status"] == "done"
    # B cannot see, fetch or change A's document
    assert client.get(f"/api/workspaces/{b}/extractions", headers=H).json() == []
    for path in (f"/{eid}", f"/{eid}/fields.json", f"/{eid}/pages.json", f"/{eid}/pdf", f"/{eid}/truth.json"):
        assert client.get(f"/api/workspaces/{b}/extractions{path}", headers=H).status_code == 404, path
    assert client.patch(f"/api/workspaces/{b}/extractions/{eid}/fields", json={"doc_index": 0, "key": "x", "value": 1}, headers=H).status_code == 404
    assert client.delete(f"/api/workspaces/{b}/extractions/{eid}", headers=H).status_code == 404
    # the same bytes in B is a new extraction, not A's cached result
    other = up(client, b, pdf).json()
    assert other.get("reused") is not True and other["id"] != eid
    # and a missing workspace is a 404, not a silent create
    assert up(client, "nope", pdf).status_code == 404


def test_custom_types_belong_to_one_workspace(client, pdf):
    a, b = mk(client, "A"), mk(client, "B")
    tpl = {"doc_type": "vendor_form", "title": "Vendor form", "single_page": True, "canonical": {}, "rules": [], "tables": [],
           "sections": [{"id": "main", "header": None, "fields": [{"key": "company", "label": "Company", "type": "text", "required": True}]}]}
    assert client.post(f"/api/workspaces/{a}/templates", json={"template": {**tpl, "doc_type": "prior_auth_form"}}, headers=H).status_code == 422
    assert client.post(f"/api/workspaces/{a}/templates", json={"template": tpl}, headers=H).status_code == 201
    again = client.post(f"/api/workspaces/{a}/templates", json={"template": tpl}, headers=H)
    assert again.status_code == 409 and "already has" in again.json()["detail"]      # no silent overwrite
    ta = {t["type"]: t for t in client.get(f"/api/workspaces/{a}/registry", headers=H).json()["types"]}
    tb = {t["type"]: t for t in client.get(f"/api/workspaces/{b}/registry", headers=H).json()["types"]}
    assert ta["vendor_form"]["custom"] is True and ta["vendor_form"]["required"] == 1
    assert "vendor_form" not in tb and tb["prior_auth_form"]["custom"] is False      # B sees only the built-ins
    assert up(client, a, pdf, "vendor_form").status_code == 202                      # valid in A
    assert up(client, b, pdf, "vendor_form").status_code == 422                      # unknown in B
    assert client.get(f"/api/workspaces/{a}", headers=H).json()["custom_types"] == 1
    assert client.delete(f"/api/workspaces/{b}/templates/vendor_form", headers=H).status_code == 404   # B cannot delete A's
    assert client.delete(f"/api/workspaces/{a}/templates/vendor_form", headers=H).status_code == 204
    assert client.delete(f"/api/workspaces/{a}/templates/vendor_form", headers=H).status_code == 404
    assert client.delete(f"/api/workspaces/{a}/templates/prior_auth_form", headers=H).status_code == 404   # built-ins are not deletable


def test_delete_workspace_removes_everything_it_owned(client, pdf, tmp_path):
    a, b = mk(client, "A"), mk(client, "B")
    keep = up(client, b, pdf).json()["id"]
    eid = up(client, a, pdf).json()["id"]
    wait(client, a, eid), wait(client, b, keep)
    client.post(f"/api/workspaces/{a}/templates", headers=H, json={"template": {
        "doc_type": "t_one", "title": "T one", "sections": [{"id": "m", "fields": [{"key": "a", "label": "A", "type": "text"}]}]}})
    from app import config
    files = [config.UPLOAD_DIR / f"{eid}.pdf", config.UPLOAD_DIR / f"{eid}.work.pdf"]
    assert files[0].exists()
    assert client.delete(f"/api/workspaces/{a}", headers=H).status_code == 204
    assert not any(f.exists() for f in files)                                        # uploads and OCR layers are gone too
    assert client.get(f"/api/workspaces/{a}", headers=H).status_code == 404
    assert client.get(f"/api/workspaces/{a}/extractions", headers=H).status_code == 404
    survivor = client.get(f"/api/workspaces/{b}/extractions/{keep}", headers=H)
    assert survivor.status_code == 200 and survivor.json()["status"] == "done"       # the other workspace is untouched
    from app import db
    with db.session() as s:
        assert s.query(db.CustomType).filter_by(workspace_id=a).count() == 0


def test_workspace_counts_follow_the_documents(client, pdf):
    wid = mk(client, "Counted")
    eid = up(client, wid, pdf).json()["id"]
    done = wait(client, wid, eid)
    row = client.get(f"/api/workspaces/{wid}", headers=H).json()
    assert row["documents"] == 1 and row["to_check"] == done["stats"]["needs_review"] and row["errors"] == done["stats"]["errors"]
    listing = client.get("/api/workspaces", headers=H).json()[0]
    assert listing["id"] == wid and listing["last_activity"] >= row["created_at"]


# ---- the flow inside a workspace (unchanged behaviour, workspace-scoped URLs) ----------------------------------------------------

def test_upload_to_download(client, pdf):
    wid = mk(client)
    base = f"/api/workspaces/{wid}/extractions"
    assert client.post(base, files={"file": ("x.txt", b"hello")}, headers=H).status_code == 415
    r = up(client, wid, pdf)
    assert r.status_code == 202
    eid = r.json()["id"]
    got = wait(client, wid, eid)
    assert got["status"] == "done", got
    again = up(client, wid, pdf, name="copy.pdf").json()                            # same bytes, same choice: reuse, no second OCR bill
    assert again == {"id": eid, "status": "done", "reused": True}
    assert len(client.get(f"{base}/{eid}/pages.json", headers=H).json()["pages"]) == 6
    fields = client.get(f"{base}/{eid}/fields.json", headers=H).json()
    assert fields["forms"][0]["values"]["review_type"] == "ROUTINE"

    di = fields["forms"][0]["doc_index"]
    assert client.patch(f"{base}/{eid}/fields", json={"doc_index": di, "key": "nope", "value": "x"}, headers=H).status_code == 404
    assert client.patch(f"{base}/{eid}/fields", json={"doc_index": di, "key": "member.last_name", "value": "Fixed"}, headers=H).status_code == 200
    f2 = client.get(f"{base}/{eid}/fields.json", headers=H).json()["forms"][0]
    assert f2["values"]["member.last_name"] == "Fixed" and f2["fields"]["member.last_name"]["status"] == "corrected"
    assert client.get(f"{base}/{eid}/pdf", headers=H).headers["content-type"] == "application/pdf"
    assert client.delete(f"{base}/{eid}", headers=H).status_code == 204
    assert client.get(f"{base}/{eid}", headers=H).status_code == 404


def test_registry_lists_readers_and_builtins(client):
    wid = mk(client)
    body = client.get(f"/api/workspaces/{wid}/registry", headers=H).json()
    by = {t["type"]: t for t in body["types"]}
    assert by["prior_auth_form"]["extractor"] == "template_form" and by["prior_auth_form"]["required"] > 10
    assert by["fax_cover"]["extractor"] == "skip" and {r["id"] for r in body["readers"]} >= {"text_layer", "ocr_dual"}


def test_template_choice_at_upload(client, pdf):
    wid = mk(client)
    assert up(client, wid, pdf, "no_such_type").status_code == 422
    r = up(client, wid, pdf, "prior_auth_form")
    assert r.status_code == 202
    assert client.get(f"/api/workspaces/{wid}/extractions/{r.json()['id']}", headers=H).json()["template_choice"] == "prior_auth_form"
    other = up(client, wid, pdf, "auto").json()                                     # same bytes, different choice: a new extraction
    assert other["id"] != r.json()["id"]


def test_draft_needs_a_model_key(client, pdf):
    wid = mk(client)
    r = client.post(f"/api/workspaces/{wid}/templates/draft", files={"file": ("blank.pdf", pdf.read_bytes(), "application/pdf")}, headers=H)
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_answer_key_and_promote_guard(client, pdf):
    wid = mk(client)
    base = f"/api/workspaces/{wid}/extractions"
    eid = up(client, wid, pdf).json()["id"]
    wait(client, wid, eid)
    form = client.get(f"{base}/{eid}/fields.json", headers=H).json()["forms"][0]
    client.patch(f"{base}/{eid}/fields", json={"doc_index": form["doc_index"], "key": "member.last_name", "value": "Reviewed"}, headers=H)
    key = client.get(f"{base}/{eid}/truth.json", headers=H).json()
    doc = next(d for d in key["documents"] if d["doc_type"] == "prior_auth_form")
    assert doc["fields"]["member.last_name"] == "Reviewed"
    assert client.post(f"{base}/{eid}/forms/{form['doc_index']}/promote", json={}, headers=H).status_code == 409


def test_typed_corrections_keep_their_type(client, pdf):
    wid = mk(client)
    base = f"/api/workspaces/{wid}/extractions"
    eid = up(client, wid, pdf).json()["id"]
    wait(client, wid, eid)
    di = client.get(f"{base}/{eid}/fields.json", headers=H).json()["forms"][0]["doc_index"]
    for key, value in (("transition_of_care", True), ("member.place_of_service", ["Office", "Home"])):
        assert client.patch(f"{base}/{eid}/fields", json={"doc_index": di, "key": key, "value": value}, headers=H).status_code == 200
    got = client.get(f"{base}/{eid}/fields.json", headers=H).json()["forms"][0]
    assert got["values"]["transition_of_care"] is True and got["fields"]["transition_of_care"]["status"] == "corrected"
    assert got["values"]["member.place_of_service"] == ["Office", "Home"]


# ---- upgrading a database that predates workspaces ----------------------------------------------------------------------------

def test_legacy_data_moves_into_my_workspace(tmp_path, monkeypatch):
    db_file = tmp_path / "extractions.db"
    con = sqlite3.connect(db_file)                     # the OLD schema: no workspace_id, template_choice or sha256
    con.execute("""CREATE TABLE extractions (id VARCHAR(36) PRIMARY KEY, filename VARCHAR(255), status VARCHAR(16), stage VARCHAR(32),
                   progress_done INTEGER, progress_total INTEGER, error TEXT, created_at DATETIME, result JSON, corrections JSON)""")
    con.execute("INSERT INTO extractions (id, filename, status, progress_done, progress_total, created_at, corrections) VALUES "
                "('old1', 'before.pdf', 'done', 0, 0, '2026-11-01 10:00:00', '{}')")
    con.commit(); con.close()
    (tmp_path / "templates").mkdir()
    entry = {"type": "legacy_form", "label": "Legacy form", "score": 3, "any": ["legacy"], "template": "legacy_form", "extractor": "template_form"}
    tpl = {"doc_type": "legacy_form", "title": "Legacy form", "sections": [{"id": "m", "header": None, "fields": [{"key": "a", "label": "A", "type": "text"}]}], "tables": []}
    (tmp_path / "custom_types.json").write_text(json.dumps([entry]))
    (tmp_path / "templates" / "legacy_form.json").write_text(json.dumps(tpl))

    reload_app(tmp_path, monkeypatch)
    from app import db
    db.init_db()
    with db.session() as s:
        ws = s.query(db.Workspace).all()
        assert [w.name for w in ws] == ["My workspace"]
        assert s.get(db.Extraction, "old1").workspace_id == ws[0].id            # the document kept, now owned by a workspace
        types = s.query(db.CustomType).all()
        assert [(t.workspace_id, t.doc_type) for t in types] == [(ws[0].id, "legacy_form")]
    assert not (tmp_path / "custom_types.json").exists() and (tmp_path / "custom_types.json.migrated").exists()
    db._migrate_legacy()                                                         # running it again changes nothing
    with db.session() as s:
        assert s.query(db.Workspace).count() == 1 and s.query(db.CustomType).count() == 1


def test_fresh_install_has_no_workspace(tmp_path, monkeypatch):
    reload_app(tmp_path, monkeypatch)
    from app import db
    db.init_db()
    with db.session() as s:
        assert s.query(db.Workspace).count() == 0                               # the first screen offers to create one
