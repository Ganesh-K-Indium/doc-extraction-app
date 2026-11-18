import importlib
import time

import pytest
from fastapi.testclient import TestClient

from tests.make_packet import build


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_API_KEY", "secret")
    from app import config
    importlib.reload(config)
    from app import db
    importlib.reload(db)
    from app.api import extractions
    importlib.reload(extractions)
    from app import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_upload_to_download(client, tmp_path):
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    h = {"X-API-Key": "secret"}
    assert client.get("/api/extractions").status_code == 401
    assert client.post("/api/extractions", files={"file": ("x.txt", b"hello")}, headers=h).status_code == 415

    r = client.post("/api/extractions", files={"file": ("packet.pdf", pdf.read_bytes(), "application/pdf")}, headers=h)
    assert r.status_code == 202
    eid = r.json()["id"]
    for _ in range(100):
        got = client.get(f"/api/extractions/{eid}", headers=h).json()
        if got["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert got["status"] == "done", got
    # the same bytes again reuse the finished result (no second round of model calls)
    again = client.post("/api/extractions", files={"file": ("copy.pdf", pdf.read_bytes(), "application/pdf")}, headers=h).json()
    assert again == {"id": eid, "status": "done", "reused": True}
    assert len(client.get(f"/api/extractions/{eid}/pages.json", headers=h).json()["pages"]) == 6
    fields = client.get(f"/api/extractions/{eid}/fields.json", headers=h).json()
    assert fields["forms"][0]["values"]["review_type"] == "ROUTINE"

    di = fields["forms"][0]["doc_index"]
    assert client.patch(f"/api/extractions/{eid}/fields", json={"doc_index": di, "key": "nope", "value": "x"}, headers=h).status_code == 404
    assert client.patch(f"/api/extractions/{eid}/fields", json={"doc_index": di, "key": "member.last_name", "value": "Fixed"}, headers=h).status_code == 200
    f2 = client.get(f"/api/extractions/{eid}/fields.json", headers=h).json()["forms"][0]
    assert f2["values"]["member.last_name"] == "Fixed" and f2["fields"]["member.last_name"]["status"] == "corrected"

    assert client.get(f"/api/extractions/{eid}/pdf", headers=h).headers["content-type"] == "application/pdf"
    assert client.delete(f"/api/extractions/{eid}", headers=h).status_code == 204
    assert client.get(f"/api/extractions/{eid}", headers=h).status_code == 404


def test_registry(client):
    h = {"X-API-Key": "secret"}
    body = client.get("/api/registry", headers=h).json()
    by = {t["type"]: t for t in body["types"]}
    assert by["prior_auth_form"]["extractor"] == "template_form" and by["prior_auth_form"]["required"] > 10
    assert by["fax_cover"]["extractor"] == "skip" and {r["id"] for r in body["readers"]} >= {"text_layer", "ocr_dual"}


def test_template_choice_at_upload(client, tmp_path):
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    h = {"X-API-Key": "secret"}
    files = {"file": ("p.pdf", pdf.read_bytes(), "application/pdf")}
    assert client.post("/api/extractions", files=files, data={"template": "no_such_type"}, headers=h).status_code == 422
    r = client.post("/api/extractions", files=files, data={"template": "prior_auth_form"}, headers=h)
    assert r.status_code == 202
    got = client.get(f"/api/extractions/{r.json()['id']}", headers=h).json()
    assert got["template_choice"] == "prior_auth_form"
    # the same bytes with a different choice are a different extraction, not a cached one
    other = client.post("/api/extractions", files=files, data={"template": "auto"}, headers=h).json()
    assert other["id"] != r.json()["id"]


def test_custom_types_save_list_delete(client):
    h = {"X-API-Key": "secret"}
    tpl = {"doc_type": "vendor_form", "title": "Vendor form", "single_page": True, "canonical": {}, "rules": [], "tables": [],
           "sections": [{"id": "main", "header": None, "fields": [{"key": "company", "label": "Company", "type": "text", "required": True}]}]}
    assert client.post("/api/templates", json={"template": {**tpl, "doc_type": "prior_auth_form"}}, headers=h).status_code == 422
    assert client.post("/api/templates", json={"template": tpl}, headers=h).status_code == 201
    types = {t["type"]: t for t in client.get("/api/registry", headers=h).json()["types"]}
    assert types["vendor_form"]["custom"] is True and types["vendor_form"]["required"] == 1
    assert types["prior_auth_form"]["custom"] is False
    # a saved type is now a valid choice at upload
    from app.services import pipeline
    assert pipeline.valid_choice("vendor_form")
    assert client.delete("/api/templates/vendor_form", headers=h).status_code == 204
    assert client.delete("/api/templates/vendor_form", headers=h).status_code == 404
    assert client.delete("/api/templates/prior_auth_form", headers=h).status_code == 404   # built-ins are not deletable


def test_draft_needs_a_model_key(client, tmp_path):
    h = {"X-API-Key": "secret"}
    pdf = tmp_path / "blank.pdf"
    build(str(pdf))
    r = client.post("/api/templates/draft", files={"file": ("blank.pdf", pdf.read_bytes(), "application/pdf")}, headers=h)
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_answer_key_export(client, tmp_path):
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    h = {"X-API-Key": "secret"}
    eid = client.post("/api/extractions", files={"file": ("p.pdf", pdf.read_bytes(), "application/pdf")}, headers=h).json()["id"]
    for _ in range(100):
        if client.get(f"/api/extractions/{eid}", headers=h).json()["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    form = client.get(f"/api/extractions/{eid}/fields.json", headers=h).json()["forms"][0]
    client.patch(f"/api/extractions/{eid}/fields", json={"doc_index": form["doc_index"], "key": "member.last_name", "value": "Reviewed"}, headers=h)
    key = client.get(f"/api/extractions/{eid}/truth.json", headers=h).json()
    doc = next(d for d in key["documents"] if d["doc_type"] == "prior_auth_form")
    assert doc["fields"]["member.last_name"] == "Reviewed"          # corrections are what makes it an answer key
    assert client.post(f"/api/extractions/{eid}/forms/{form['doc_index']}/promote", json={}, headers=h).status_code == 409  # templated already


def test_typed_corrections_keep_their_type(client, tmp_path):
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    h = {"X-API-Key": "secret"}
    eid = client.post("/api/extractions", files={"file": ("p.pdf", pdf.read_bytes(), "application/pdf")}, headers=h).json()["id"]
    for _ in range(100):
        if client.get(f"/api/extractions/{eid}", headers=h).json()["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    form = client.get(f"/api/extractions/{eid}/fields.json", headers=h).json()["forms"][0]
    di = form["doc_index"]
    for key, value in (("transition_of_care", True), ("member.place_of_service", ["Office", "Home"])):
        assert client.patch(f"/api/extractions/{eid}/fields", json={"doc_index": di, "key": key, "value": value}, headers=h).status_code == 200
    got = client.get(f"/api/extractions/{eid}/fields.json", headers=h).json()["forms"][0]
    assert got["values"]["transition_of_care"] is True and got["fields"]["transition_of_care"]["status"] == "corrected"
    assert got["values"]["member.place_of_service"] == ["Office", "Home"]
    doc = next(d for d in client.get(f"/api/extractions/{eid}/truth.json", headers=h).json()["documents"] if d["doc_type"] == "prior_auth_form")
    assert doc["fields"]["transition_of_care"] is True and doc["fields"]["member.place_of_service"] == ["Office", "Home"]
