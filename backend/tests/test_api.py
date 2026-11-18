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
