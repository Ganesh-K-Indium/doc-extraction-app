"""Provider keys saved from the Settings screen: encrypted at rest, never returned, and used by the model layer."""
import asyncio
import os
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient

from app import config
from app.engines.providers import credentials, llm
from tests.test_api import H, reload_app

KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OLLAMA_BASE_URL", "LLM_CUSTOM_BASE_URL", "LLM_CUSTOM_API_KEY",
        "LLM_CUSTOM_MODEL", "OPENAI_BASE_URL", "LOCAL_ONLY", "LOCK_SETTINGS", "APP_SECRET_KEY")
SECRET = "sk-ant-api03-SUPERSECRETVALUE-1234"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_ENABLED", "1")
    with TestClient(reload_app(tmp_path, monkeypatch)) as c:
        c.data_dir = tmp_path
        yield c


def put(client, provider, values):
    return client.put(f"/api/settings/providers/{provider}", json={"values": values}, headers=H)


def field(body, name):
    return next(f for p in body["providers"] for f in p["fields"] if f["name"] == name)


def test_a_saved_key_is_encrypted_masked_and_used(client):
    assert client.get("/api/settings/providers").status_code == 401
    before = client.get("/api/settings/providers", headers=H).json()
    assert field(before, "ANTHROPIC_API_KEY")["set"] is False and not llm.provider_ready("anthropic")
    r = put(client, "anthropic", {"ANTHROPIC_API_KEY": SECRET})
    assert r.status_code == 200 and SECRET not in r.text                                   # never echoed back
    body = client.get("/api/settings/providers", headers=H).json()
    f = field(body, "ANTHROPIC_API_KEY")
    assert f["set"] and f["source"] == "saved" and f["preview"] == "••••••••1234" and SECRET not in str(body)
    assert next(p for p in body["providers"] if p["id"] == "anthropic")["status"] == "ready"
    assert llm.provider_ready("anthropic") and config.llm_enabled()                         # the model layer sees it at once
    assert body["encryption"] == "ok" and body["locked"] is False

    raw = sqlite3.connect(client.data_dir / "extractions.db").execute("select name, value from provider_credentials").fetchall()
    assert [n for n, _ in raw] == ["ANTHROPIC_API_KEY"] and SECRET not in raw[0][1] and "SUPERSECRET" not in raw[0][1]   # ciphertext only
    key_file = client.data_dir / "secret.key"
    assert key_file.exists() and stat.S_IMODE(key_file.stat().st_mode) == 0o600           # the key is owner-only
    assert SECRET.encode() not in key_file.read_bytes()

    seen = {}

    async def fake_post(url, headers, body):
        seen.update(headers)
        return {"content": [{"type": "text", "text": "{}"}], "usage": {}}
    llm._post, original = fake_post, llm._post
    try:
        asyncio.run(llm.complete("anthropic:claude-haiku-5-5", "p", stage="t"))
    finally:
        llm._post = original
    assert seen["x-api-key"] == SECRET                                                      # and it is the saved key that is sent


def test_saved_values_beat_the_environment_and_removal_falls_back(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-from-the-server")
    f = field(client.get("/api/settings/providers", headers=H).json(), "ANTHROPIC_API_KEY")
    assert f["set"] and f["source"] == "environment" and credentials.get("ANTHROPIC_API_KEY") == "env-key-from-the-server"
    put(client, "anthropic", {"ANTHROPIC_API_KEY": SECRET})
    assert credentials.get("ANTHROPIC_API_KEY") == SECRET
    assert put(client, "anthropic", {"ANTHROPIC_API_KEY": ""}).status_code == 200            # an empty box leaves it alone
    assert credentials.get("ANTHROPIC_API_KEY") == SECRET
    r = put(client, "anthropic", {"ANTHROPIC_API_KEY": None})                                 # null removes the saved one
    assert r.status_code == 200 and credentials.get("ANTHROPIC_API_KEY") == "env-key-from-the-server"
    assert field(client.get("/api/settings/providers", headers=H).json(), "ANTHROPIC_API_KEY")["source"] == "environment"


def test_addresses_are_shown_in_full_and_validated(client):
    assert put(client, "ollama", {"OLLAMA_BASE_URL": "http://gpu-box:11434"}).status_code == 200
    f = field(client.get("/api/settings/providers", headers=H).json(), "OLLAMA_BASE_URL")
    assert f["preview"] == "http://gpu-box:11434" and not f["secret"]
    assert llm.provider_ready("ollama")
    bad = [("ollama", {"OLLAMA_BASE_URL": "gpu-box"}, "http://"), ("anthropic", {"ANTHROPIC_API_KEY": "short"}, "complete"),
           ("anthropic", {"ANTHROPIC_API_KEY": "has a space inside it"}, "complete"), ("anthropic", {"OLLAMA_BASE_URL": "http://x"}, "belong"),
           ("anthropic", {"NOPE": "x"}, "belong"), ("openai", {"OPENAI_API_KEY": "sk-" + "x" * 600}, "too long")]
    for provider, values, msg in bad:
        r = put(client, provider, values)
        assert r.status_code == 422 and msg in r.json()["detail"], (values, r.text)
    assert put(client, "nope", {}).status_code == 404
    assert credentials.get("OLLAMA_BASE_URL") == "http://gpu-box:11434"                       # nothing bad was half-saved


def test_settings_can_be_locked_by_the_operator(client, monkeypatch):
    monkeypatch.setenv("LOCK_SETTINGS", "1")
    r = put(client, "openai", {"OPENAI_API_KEY": "sk-" + "a" * 20})
    assert r.status_code == 403 and "locked" in r.json()["detail"]
    assert client.get("/api/settings/providers", headers=H).json()["locked"] is True
    assert credentials.get("OPENAI_API_KEY") != "sk-" + "a" * 20                              # nothing was saved


def test_local_only_blocks_a_saved_cloud_key(client, monkeypatch):
    put(client, "openai", {"OPENAI_API_KEY": "sk-" + "a" * 20})
    assert llm.provider_ready("openai")
    monkeypatch.setenv("LOCAL_ONLY", "1")
    assert not llm.provider_ready("openai")
    assert next(p for p in client.get("/api/settings/providers", headers=H).json()["providers"] if p["id"] == "openai")["status"] == "blocked"


def test_an_operator_secret_key_is_used_instead_of_a_key_file(client, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "operator-managed-secret")
    put(client, "gemini", {"GEMINI_API_KEY": "gem-key-123456789"})
    assert not (client.data_dir / "secret.key").exists() and credentials.get("GEMINI_API_KEY") == "gem-key-123456789"
    monkeypatch.setenv("APP_SECRET_KEY", "a-different-secret")                                # the wrong key cannot read it, and nothing crashes
    credentials.invalidate()
    assert credentials.get("GEMINI_API_KEY") == "" and not llm.provider_ready("gemini")
    monkeypatch.setenv("APP_SECRET_KEY", "operator-managed-secret")
    credentials.invalidate()
    assert credentials.get("GEMINI_API_KEY") == "gem-key-123456789"


def test_deleting_the_encryption_key_does_not_crash_the_app(client):
    put(client, "gemini", {"GEMINI_API_KEY": "gem-key-123456789"})
    (client.data_dir / "secret.key").unlink()
    credentials.invalidate()
    assert credentials.get("GEMINI_API_KEY") == ""                                            # unreadable: treated as not set
    assert client.get("/api/settings/providers", headers=H).status_code == 200


def test_engines_overview_points_to_settings(client):
    body = client.get("/api/engines", headers=H).json()
    assert "Settings" in next(p for p in body["providers"] if p["id"] == "anthropic")["hint"]
