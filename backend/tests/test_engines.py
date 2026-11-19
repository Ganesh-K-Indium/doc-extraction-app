"""Reading engines: model providers, local OCR, the reading plan, the escalation ladder and the API. All offline."""
import asyncio
import io

import pytest
from fastapi.testclient import TestClient

from app import config
from app.engines import ladder, llm, local, plan
from app.services.reading import ocr, pdf_pages
from app.services import pipeline
from app.services.reading.tess import available as tess_available
from app.services.usage_tracker import track_usage
from tests.test_api import H, mk, reload_app, wait


def run(coro):
    return asyncio.run(coro)


KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OLLAMA_BASE_URL", "LLM_CUSTOM_BASE_URL", "LLM_CUSTOM_MODEL", "LOCAL_ONLY",
        "EXTRACTION_MODELS", "HANDWRITING_OCR_MODELS", "READING_STRATEGY", "LOCAL_OCR_ENGINE", "ESCALATE_BELOW", "TOKEN_CAP")


@pytest.fixture()
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_ENABLED", "1")
    return monkeypatch


# ---- model specs and providers ---------------------------------------------------------------------------------------

def test_spec_parsing():
    assert llm.split("gpt-4.1") == ("openai", "gpt-4.1")
    assert llm.split("anthropic:claude-sonnet-5-5") == ("anthropic", "claude-sonnet-5-5")
    assert llm.split("ollama:qwen2.5vl:7b") == ("ollama", "qwen2.5vl:7b")      # only the first colon separates
    assert llm.split("qwen2.5vl:7b") == ("openai", "qwen2.5vl:7b")            # an unknown prefix is part of an OpenAI-style name
    assert llm.valid_spec("gemini:gemini-2.5-flash")
    assert not llm.valid_spec("anthropic:") and not llm.valid_spec("a b") and not llm.valid_spec("") and not llm.valid_spec(None)


def test_defaults_follow_the_configured_provider(clean_env):
    assert llm.default_models() == ["gpt-4.1", "gpt-4.1-mini"] and not config.llm_enabled()
    clean_env.setenv("ANTHROPIC_API_KEY", "k")
    assert llm.default_models()[0].startswith("anthropic:") and config.llm_enabled()
    clean_env.setenv("OPENAI_API_KEY", "k")
    assert llm.default_models() == ["gpt-4.1", "gpt-4.1-mini"]                   # OpenAI stays the default when it is there
    clean_env.delenv("OPENAI_API_KEY"), clean_env.delenv("ANTHROPIC_API_KEY")
    clean_env.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    assert llm.default_models() == ["ollama:qwen2.5vl:7b"] and config.llm_enabled()
    clean_env.setenv("EXTRACTION_MODELS", "anthropic:claude-haiku-5-5")
    assert config.extraction_models() == ["anthropic:claude-haiku-5-5"]          # an explicit server setting wins


def test_local_only_switches_cloud_providers_off(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "k")
    assert config.llm_enabled()
    clean_env.setenv("LOCAL_ONLY", "1")
    assert not llm.provider_ready("openai") and not config.llm_enabled()
    with pytest.raises(llm.LLMError) as e:
        run(llm.complete("gpt-4.1", "hi", stage="t"))
    assert e.value.status == 503 and "LOCAL_ONLY" in str(e.value)
    clean_env.setenv("OLLAMA_BASE_URL", "http://localhost:11434")                # a model on your own hardware still works
    assert config.llm_enabled()
    with pytest.raises(ValueError, match="switched off"):
        plan.clean({"models": ["openai:gpt-4.1"]})
    assert next(p for p in llm.providers_status() if p["id"] == "openai")["status"] == "blocked"


def test_clean_json():
    assert llm.clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert llm.clean_json('Here you go: {"a": 1} Hope it helps') == '{"a": 1}'
    assert llm.clean_json("not json") == "not json"


def test_anthropic_request_and_usage(clean_env):
    clean_env.setenv("ANTHROPIC_API_KEY", "ak")
    seen = {}

    async def fake_post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"content": [{"type": "text", "text": '```json\n{"lines": ["a"]}\n```'}], "usage": {"input_tokens": 1500, "output_tokens": 20}}
    clean_env.setattr(llm, "_post", fake_post)
    with track_usage("t") as u:
        out = run(llm.complete("anthropic:claude-sonnet-5-5", "read this", b"\xff\xd8jpeg", stage="handwriting_ocr"))
    assert out == '{"lines": ["a"]}'
    assert seen["url"].endswith("/v1/messages") and seen["headers"]["x-api-key"] == "ak"
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg" and "JSON" in content[1]["text"]
    assert seen["body"]["model"] == "claude-sonnet-5-5"
    assert u.entries[0].total_tokens == 1520 and u.entries[0].model == "anthropic:claude-sonnet-5-5"


def test_anthropic_retries_without_temperature_when_the_model_refuses_it(clean_env):
    clean_env.setenv("ANTHROPIC_API_KEY", "ak")
    calls = []

    async def fake_post(url, headers, body):
        calls.append("temperature" in body)
        if "temperature" in body:
            raise llm.LLMError("temperature is not supported for this model", 400)
        return {"content": [{"type": "text", "text": "{}"}], "usage": {}}
    clean_env.setattr(llm, "_post", fake_post)
    assert run(llm.complete("anthropic:m", "p", stage="t")) == "{}" and calls == [True, False]


def test_gemini_request_and_usage(clean_env):
    clean_env.setenv("GOOGLE_API_KEY", "gk")
    seen = {}

    async def fake_post(url, headers, body):
        seen.update(url=url, headers=headers, body=body)
        return {"candidates": [{"content": {"parts": [{"text": '{"x": 1}'}]}}], "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 10, "totalTokenCount": 410}}
    clean_env.setattr(llm, "_post", fake_post)
    with track_usage("t") as u:
        assert run(llm.complete("gemini:gemini-2.5-flash", "p", b"jpg", stage="discover")) == '{"x": 1}'
    assert "models/gemini-2.5-flash:generateContent" in seen["url"] and seen["headers"]["x-goog-api-key"] == "gk"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    assert u.entries[0].total_tokens == 410                                       # includes the model's thinking tokens


class FakeCompletions:
    def __init__(self, fail_first=False):
        self.calls, self.fail_first = [], fail_first

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail_first and "response_format" in kw:
            err = Exception("bad request")
            err.status_code = 400
            raise err
        msg = type("M", (), {"content": '{"ok": true}'})
        usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
        return type("R", (), {"choices": [type("C", (), {"message": msg})], "usage": usage})


def fake_client(comp):
    return type("Client", (), {"chat": type("Chat", (), {"completions": comp})})


def test_openai_style_providers(clean_env):
    clean_env.setenv("OPENAI_API_KEY", "k")
    clean_env.setenv("OLLAMA_BASE_URL", "http://box:11434/")
    comp, bases = FakeCompletions(), []
    clean_env.setattr(llm, "_openai_client", lambda base, key: (bases.append(base), fake_client(comp))[1])
    run(llm.complete("gpt-4.1", "p", b"j", stage="t"))
    run(llm.complete("gpt-5", "p", stage="t"))
    run(llm.complete("ollama:qwen2.5vl:7b", "p", b"j", stage="t"))
    gpt41, gpt5, ollama = comp.calls
    assert gpt41["temperature"] == 0 and gpt41["response_format"] == {"type": "json_object"} and gpt41["messages"][0]["content"][1]["image_url"]["detail"] == "high"
    assert gpt5["reasoning_effort"] == "low" and "temperature" not in gpt5 and len(gpt5["messages"][0]["content"]) == 1   # text-only: no image part
    assert ollama["model"] == "qwen2.5vl:7b" and bases == [None, None, "http://box:11434/v1"]


def test_self_hosted_server_without_json_mode_is_retried(clean_env):
    clean_env.setenv("LLM_CUSTOM_BASE_URL", "http://vllm:8000/v1")
    comp = FakeCompletions(fail_first=True)
    clean_env.setattr(llm, "_openai_client", lambda base, key: fake_client(comp))
    assert run(llm.complete("custom:my-model", "p", b"j", stage="t")) == '{"ok": true}'
    assert ["response_format" in c for c in comp.calls] == [True, False]


# ---- local OCR ---------------------------------------------------------------------------------------------------------

def W(x0, y0, x1, y1, t, c=0.95):
    return local.Word(x0, y0, x1, y1, t, c)


def test_words_become_rows_with_cells():
    words = [W(10, 100, 60, 120, "Revenue"), W(300, 101, 360, 121, "70,066"), W(500, 99, 560, 119, "61,858"),
             W(10, 140, 40, 160, "Net"), W(45, 141, 90, 161, "income")]
    r = local.build_reading(words, "x")
    assert r.lines == ["Revenue | 70,066 | 61,858", "Net income"]                # wide gaps are cells, a word space is not
    assert r.words == 5 and r.confidence == pytest.approx(0.95) and r.low_share == 0


def test_confidence_summary_counts_doubtful_words_and_numbers():
    words = [W(0, 0, 40, 20, "Total", 0.95), W(50, 0, 90, 20, "1,250.75", 0.5), W(100, 0, 140, 20, "due", 0.4), W(150, 0, 190, 20, "$", None)]
    r = local.build_reading(words, "x")
    assert r.low_share == pytest.approx(2 / 3) and r.digit_low_share == 1.0 and r.words == 3
    assert r.line_conf[0] == pytest.approx((0.95 + 0.5 + 0.4) / 3)                  # punctuation-only tokens do not count


def test_tesseract_tsv_is_parsed():
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
          "4\t1\t1\t1\t1\t0\t5\t5\t100\t20\t-1\t\n5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t93.5\tHello\n5\t1\t1\t1\t1\t2\t70\t10\t40\t20\t-1\t \n"
    words = local.words_from_tsv(tsv)
    assert [(w.text, w.conf) for w in words] == [("Hello", 0.935)] and words[0].x1 == 60


def test_box_words_accepts_polygons_and_rectangles():
    ws = local._box_words([([[0, 0], [50, 0], [50, 20], [0, 20]], "Hi", 0.9), ([5, 5, 25, 15], "yo", None), ([0, 0, 1, 1], "  ", 1.0)])
    assert [(w.text, w.x1, w.y1, w.conf) for w in ws] == [("Hi", 50, 20, 0.9), ("yo", 25, 15, None)]


def jpeg_of(ink: bool) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("L", (600, 800), 255)
    if ink:
        d = ImageDraw.Draw(img)
        for y in range(50, 750, 20):
            d.rectangle((40, y, 560, y + 8), fill=0)
    out = io.BytesIO()
    img.save(out, "JPEG")
    return out.getvalue()


def test_assess_decides_whether_a_local_reading_can_stand():
    good = local.build_reading([W(0, 0, 40, 20, "Total", 0.97), W(50, 0, 90, 20, "125", 0.96)], "x")
    assert local.assess(good, 0.85).ok
    weak = local.build_reading([W(0, 0, 40, 20, "Total", 0.7), W(50, 0, 90, 20, "125", 0.7)], "x")
    v = local.assess(weak, 0.85)
    assert not v.ok and "70%" in v.reasons[0]
    assert local.assess(weak, 0.6).ok                                               # the threshold is the user's call
    digits = local.build_reading([W(i * 50, 0, i * 50 + 40, 20, f"{n}{n}", 0.99 if i > 1 else 0.5) for i, n in enumerate("12345")], "x")
    assert any("numbers" in r for r in local.assess(digits, 0.5).reasons)
    garbled = local.build_reading([W(0, 0, 40, 20, "(cid:12)(cid:7)" * 6, 0.99)], "x")
    assert not local.assess(garbled, 0.5).ok
    empty = local.Reading("x", [], [], 0)
    assert local.assess(empty, 0.85, jpeg_of(ink=False)).ok                         # a blank page has nothing to read
    inked = local.assess(empty, 0.85, jpeg_of(ink=True))
    assert not inked.ok and "no text was recognised" in inked.reasons[0]            # marks but no words: handwriting, a photo


def test_agreement_separates_clean_pages_from_unreadable_ones():
    clean_a = "Revenue | 70,066 | 61,858\nNet income 25,824 21,939\nTotal assets $512,163"
    clean_b = "Revenue 70,066 61,858\nNet income 25,824 21,939\nTotal assets 512,163"
    assert local.agreement(clean_a, clean_b) > 0.9
    assert local.agreement(clean_a, "7o,o66 b1,858\nNet inc0me 2S,824") < 0.5
    assert local.agreement(clean_a, "") == 0.0
    mine = local.build_reading([W(0, 0, 90, 20, "Revenue 70,066", 0.8), W(0, 40, 90, 60, "Net inc0me 2S,824", 0.8)], "rapidocr")
    other = local.build_reading([W(0, 0, 90, 20, "Revenue 70,066", 0.9), W(0, 40, 90, 60, "Net income 25,824", 0.9)], "tesseract")
    out = local.cross_check(mine, other)
    assert out.line_conf[0] == 1.0 and out.line_conf[1] < 0.5 and out.agreement == pytest.approx(0.6)                 # the line they disagree on is the doubtful one
    assert not local.assess_cross(out).ok and "60%" in local.assess_cross(out).reasons[0]
    same = local.cross_check(local.build_reading([W(0, 0, 90, 20, "Revenue 70,066", 0.6), W(0, 40, 90, 60, "Net income 25,824", 0.6)], "rapidocr"), other)
    assert same.agreement == 1.0 and local.assess_cross(same).ok                                # its own low confidence no longer matters


def test_engine_listing_names_every_engine():
    ids = [e["id"] for e in local.listing()]
    assert ids == ["tesseract", "rapidocr", "paddleocr", "doctr"]
    missing = [e for e in local.listing() if not e["ready"]]
    assert all(e["status"] == "not_installed" and e["hint"] for e in missing)


@pytest.mark.skipif(not tess_available(), reason="Tesseract is not installed")
def test_tesseract_reads_a_clean_page_confidently():
    from app.api.engines import SAMPLE_TOKENS, _found, sample_page
    jpeg = sample_page()
    r = run(local.get("tesseract").read(jpeg))
    assert _found(r.text) >= 0.75, r.text
    assert r.confidence > 0.85 and local.assess(r, 0.85, jpeg).ok


# ---- the reading plan -------------------------------------------------------------------------------------------------

class FakeLocal(local.Engine):
    """A local engine with a scripted reading, so the ladder is tested without OCR."""
    id, label = "tesseract", "Fake"

    def __init__(self, reading=None, fail=False):
        self.reading, self.fail, self.calls = reading, fail, 0

    def available(self):
        return True

    async def read(self, jpeg):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return self.reading


def reading(conf=0.95, lines=("Invoice No. 4821", "Total $120.00"), digit_low=0.0, low=0.0):
    r = local.build_reading([W(0, i * 30, 90, i * 30 + 20, t, conf) for i, t in enumerate(lines)], "tesseract")
    r.digit_low_share, r.low_share = digit_low, low
    return r


@pytest.fixture()
def fake_engine(monkeypatch):
    def install(**kw):
        eng = FakeLocal(**kw)
        monkeypatch.setitem(local._ENGINES, "tesseract", eng)
        return eng
    return install


def test_strategies_map_to_modes(clean_env, fake_engine):
    fake_engine(reading=reading())
    clean_env.setenv("OPENAI_API_KEY", "k")
    assert plan.resolve({"strategy": "economy"}).mode == "local" and not plan.resolve({"strategy": "economy"}).llm
    b = plan.resolve({"strategy": "balanced"})
    assert (b.mode, b.llm, b.local_engine) == ("escalate", True, "tesseract")
    assert plan.resolve({"strategy": "accuracy"}).mode == "vision"
    assert plan.resolve({"strategy": "custom", "mode": "local"}).mode == "local"
    assert plan.resolve({"strategy": "balanced", "mode": "local"}).mode == "escalate"           # mode only counts for custom
    assert plan.resolve({}).strategy == "balanced"                                             # the default
    assert plan.resolve({"strategy": "economy"}, {"strategy": "accuracy"}).strategy == "accuracy"   # an upload can override
    assert plan.resolve({"strategy": "nonsense"}).strategy == "balanced"


def test_plan_degrades_with_a_note_instead_of_failing(clean_env, fake_engine, monkeypatch):
    fake_engine(reading=reading())
    p = plan.resolve({"strategy": "balanced"})                                                  # no model key at all
    assert p.mode == "escalate" and not p.llm and any("no model is configured" in n for n in p.notes)
    monkeypatch.setattr(local, "ready", lambda: [])
    clean_env.setenv("OPENAI_API_KEY", "k")
    p = plan.resolve({"strategy": "balanced", "local_engine": "rapidocr"})
    assert p.local_engine is None and p.mode == "vision" and any("straight to the vision models" in n for n in p.notes)


def test_plan_settings_and_fingerprint(clean_env, fake_engine):
    fake_engine(reading=reading())
    clean_env.setenv("OPENAI_API_KEY", "k")
    base = plan.resolve({"strategy": "balanced"})
    assert base.fingerprint() == plan.resolve({"strategy": "balanced"}).fingerprint()
    assert base.fingerprint() != plan.resolve({"strategy": "accuracy"}).fingerprint()
    assert base.fingerprint() != plan.resolve({"strategy": "balanced", "escalate_below": 0.7}).fingerprint()
    assert base.fingerprint() != plan.resolve({"strategy": "balanced", "models": ["openai:gpt-5"]}).fingerprint()
    assert plan.resolve({"models": ["openai:gpt-5", "bad model"]}).models == ("openai:gpt-5",)
    assert plan.resolve({"escalate_below": 5}).escalate_below == 0.99 and plan.resolve({"token_cap": -4}).token_cap == 0
    clean_env.setenv("READING_STRATEGY", "accuracy")
    assert plan.resolve({}).strategy == "accuracy"                                              # the server's default
    assert plan.resolve({"strategy": "economy"}).strategy == "economy"                          # a workspace beats it


def test_settings_are_validated(clean_env, fake_engine):
    fake_engine(reading=reading())
    clean_env.setenv("OPENAI_API_KEY", "k")
    ok = plan.clean({"strategy": "custom", "mode": "escalate", "local_engine": "tesseract", "models": ["openai:gpt-4.1", "openai:gpt-4.1"],
                     "escalate_below": "0.8", "token_cap": 50000})
    assert ok == {"strategy": "custom", "mode": "escalate", "local_engine": "tesseract", "models": ["openai:gpt-4.1"], "escalate_below": 0.8, "token_cap": 50000}
    for bad, msg in [({"strategy": "x"}, "Choose"), ({"mode": "x"}, "mode"), ({"local_engine": "nope"}, "does not exist"),
                     ({"local_engine": "doctr"}, "not installed"), ({"models": ["a", "b", "c"]}, "up to two"), ({"models": ["anthropic:claude-haiku-5-5"]}, "not available"),
                     ({"escalate_below": 0.1}, "between"), ({"token_cap": -1}, "token cap")]:
        with pytest.raises(ValueError, match=msg):
            plan.clean(bad)


# ---- the escalation ladder ----------------------------------------------------------------------------------------------

async def vision_ok(model, jpeg):
    return ["Invoice No. 4821", "Total $120.00"]


def scan(**kw):
    return run(ladder.read_scanned(jpeg=jpeg_of(True), models=["m-a", "m-b"], **kw))


def test_a_confident_local_reading_never_reaches_a_model(fake_engine):
    eng = fake_engine(reading=reading(0.96))
    calls = []

    async def reader(model, jpeg):
        calls.append(model)
        return ["x"]
    s = scan(mode="escalate", engine_id="tesseract", reader=reader)
    assert calls == [] and eng.calls == 1
    assert s.source == "ocr-local" and not s.verified and [l.text for l in s.lines] == ["Invoice No. 4821", "Total $120.00"]
    assert s.reading["engine"] == "tesseract" and s.reading["escalated"] is False and s.reading["confidence"] == pytest.approx(0.96)


def test_an_uncalibrated_engine_needs_tesseract_to_agree(fake_engine, monkeypatch):
    fake_engine(reading=reading(0.97, ("Invoice No. 4821", "Total $120.00")))                 # Tesseract (the reference)
    rapid = FakeLocal(reading=reading(0.7, ("Invoice No. 4821", "Total $120.00")))               # low own confidence, but they agree
    rapid.id, rapid.calibrated = "rapidocr", False
    monkeypatch.setitem(local._ENGINES, "rapidocr", rapid)
    s = scan(mode="escalate", engine_id="rapidocr", reader=vision_ok)
    assert s.source == "ocr-local" and s.reading["engine"] == "rapidocr" and s.reading["agreement"] == 1.0 and rapid.calls == 1
    rapid.reading = reading(0.99, ("Invc1ce N0. 48Z1", "T0tal $l2O.OO"))                         # confident, but Tesseract disagrees
    s = scan(mode="escalate", engine_id="rapidocr", reader=vision_ok)
    assert s.source == "ocr" and s.reading["escalated"] and "agree on only" in s.reading["reasons"][0]
    lone = scan(mode="local", engine_id="rapidocr")                                              # economy keeps the local reading, flagged
    assert lone.source == "ocr-local" and lone.reading["reasons"] and any(l.status == "review" for l in lone.lines)
    monkeypatch.setitem(local._ENGINES, "tesseract", type("Gone", (FakeLocal,), {"available": lambda self: False})())
    rapid.reading = reading(0.82, ("Invoice No. 4821",))
    s = scan(mode="escalate", engine_id="rapidocr", reader=vision_ok)                            # no reference: its own number is not enough
    assert s.source == "ocr" and "cross-check" in s.reading["reasons"][-1]


def test_a_doubtful_page_is_escalated_and_says_why(fake_engine):
    fake_engine(reading=reading(0.5))
    s = scan(mode="escalate", engine_id="tesseract", reader=vision_ok)
    assert s.source == "ocr" and s.verified and s.reading["escalated"] is True and s.reading["engine"] == "vision"
    assert s.reading["models"] == ["m-a", "m-b"] and "OCR confidence 50%" in s.reading["reasons"][0] and s.reading["local_confidence"] == pytest.approx(0.5)


def test_local_mode_only_flags_and_never_escalates(fake_engine):
    fake_engine(reading=reading(0.5))
    calls = []

    async def reader(model, jpeg):
        calls.append(1)
        return []
    s = scan(mode="local", engine_id="tesseract", reader=reader)
    assert calls == [] and s.source == "ocr-local" and s.reading["reasons"] and all(l.status == "review" for l in s.lines)


def test_unsure_lines_are_flagged_individually(fake_engine):
    r = local.build_reading([W(0, 0, 90, 20, "Invoice", 0.97), W(0, 40, 90, 60, "T0tal", 0.4)], "tesseract")
    fake_engine(reading=r)
    s = scan(mode="local", engine_id="tesseract")
    assert [l.status for l in s.lines] == ["agreed", "review"] and s.lines[1].reason


def test_vision_mode_skips_the_local_engine(fake_engine):
    eng = fake_engine(reading=reading())
    s = scan(mode="vision", engine_id="tesseract", reader=vision_ok)
    assert eng.calls == 0 and s.source == "ocr" and s.reading["escalated"] is False


def test_force_vision_overrides_a_good_local_reading(fake_engine):
    eng = fake_engine(reading=reading(0.99))
    s = scan(mode="escalate", engine_id="tesseract", reader=vision_ok, force_vision=True)
    assert eng.calls == 0 and s.source == "ocr" and s.reading["escalated"] and "re-read" in s.reading["reasons"][0]


def test_the_token_cap_stops_escalation(fake_engine):
    fake_engine(reading=reading(0.5))
    with track_usage("t") as u:
        u.record("discover", "m", total_tokens=900)
        capped = scan(mode="escalate", engine_id="tesseract", reader=vision_ok, token_cap=500)
        free = scan(mode="escalate", engine_id="tesseract", reader=vision_ok, token_cap=5000)
    assert capped.source == "ocr-local" and capped.reading["cost_capped"] and "token cap" in capped.reading["reasons"][-1]
    assert free.source == "ocr"


def test_a_failing_local_engine_falls_back_to_vision_and_vision_failure_keeps_local(fake_engine):
    fake_engine(fail=True)
    s = scan(mode="escalate", engine_id="tesseract", reader=vision_ok)
    assert s.source == "ocr" and s.reading["escalated"] and "could not read" in s.reading["reasons"][0]
    fake_engine(reading=reading(0.5))

    async def down(model, jpeg):
        raise RuntimeError("503")
    s = scan(mode="escalate", engine_id="tesseract", reader=down)
    assert s.source == "ocr-local" and any("unavailable" in r for r in s.reading["reasons"])     # the page is not lost
    fake_engine(fail=True)
    with pytest.raises(ocr.OcrError):
        scan(mode="escalate", engine_id="tesseract", reader=down)                               # nothing could read it: now it fails


def test_tesseract_words_from_the_work_pass_are_reused(fake_engine):
    eng = fake_engine(reading=reading())
    tsv = "h\n5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t96\tHello\n"
    s = scan(mode="escalate", engine_id="tesseract", tsv=tsv)
    assert eng.calls == 0 and [l.text for l in s.lines] == ["Hello"]                            # no second OCR pass


# ---- through the whole pipeline ---------------------------------------------------------------------------------------

def scanned_pdf(path, lines_per_page):
    """Image-only pages (so each is a scan) with printed text drawn in."""
    import pymupdf as fitz
    from PIL import Image, ImageDraw, ImageFont
    doc = fitz.open()
    font = ImageFont.load_default(size=34)
    for lines in lines_per_page:
        img = Image.new("RGB", (1224, 1584), "white")
        d = ImageDraw.Draw(img)
        for i, t in enumerate(lines):
            d.text((90, 120 + i * 80), t, fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        page = doc.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()
    return str(path)


PAGE_A = ["Invoice No. 48213", "Date: 03/14/2026", "Total due $1,250.75", "Customer Northwind Traders"]


@pytest.mark.skipif(not tess_available(), reason="Tesseract is not installed")
def test_balanced_plan_reads_a_clean_scan_without_any_vision_call(tmp_path, clean_env):
    clean_env.setenv("OPENAI_API_KEY", "k")
    pdf = scanned_pdf(tmp_path / "scan.pdf", [PAGE_A])
    vision, structuring = [], []

    async def reader(model, jpeg):
        vision.append(model)
        return ["x"]

    async def form(model, jpeg, prompt):
        structuring.append(jpeg is None)               # text-only reads have no image
        return {"title": "Invoice", "checkboxes": [], "tables": [], "fields": [{"label": "Invoice No", "value": "48213"}, {"label": "Total due", "value": "1,250.75"}]}
    from app.services.extraction import discover
    clean_env.setattr(discover, "_read", form)
    res = run(pipeline.process(pdf, plan=plan.resolve({"strategy": "balanced"}), ocr_reader=reader, form_reader=form))
    page = res["pages"][0]
    assert vision == [] and page["source"] == "ocr-local" and page["reading"]["engine"] == "tesseract" and not page["reading"]["escalated"]
    assert "48213" in page["text"] and "1,250.75" in page["text"]
    assert structuring and all(structuring)            # the page was structured from its text, never from the picture
    assert res["stats"]["local_ocr_pages"] == 1 and res["stats"]["vision_pages"] == 0 and res["stats"]["escalated_pages"] == 0
    assert res["reading"]["strategy"] == "balanced" and res["reading"]["fingerprint"]
    values = {c["label"]: c["value"] for c in res["forms"][0]["fields"].values()}
    assert values["Invoice No"] == "48213"


def test_pipeline_escalates_only_the_doubtful_page(tmp_path, clean_env, fake_engine):
    clean_env.setenv("OPENAI_API_KEY", "k")
    pdf = scanned_pdf(tmp_path / "two.pdf", [PAGE_A, PAGE_A])
    good, bad = reading(0.97), reading(0.45)
    state = {"n": 0}

    class PerPage(FakeLocal):
        async def read(self, jpeg):                                  # first call -> a good page, second -> a poor one
            state["n"] += 1
            return good if state["n"] == 1 else bad
    clean_env.setitem(local._ENGINES, "tesseract", PerPage())
    seen = []

    async def reader(model, jpeg):
        seen.append(model)
        return ["Invoice No. 4821", "Total $120.00"]

    async def form(model, jpeg, prompt):
        return {"fields": {}, "table_rows": []}
    # this test is about page reading, so the pipeline's own tesseract word table must not be used
    clean_env.setattr(pdf_pages, "build_work_pdf", lambda src, dst, scanned, tsv=None: (__import__("shutil").copy(src, dst), {})[1])
    res = run(pipeline.process(pdf, plan=plan.resolve({"strategy": "balanced"}), ocr_reader=reader, form_reader=form))
    sources = sorted(p["source"] for p in res["pages"])
    assert sources == ["ocr", "ocr-local"] and len(seen) == 2          # one page, two vision readers
    assert res["stats"]["escalated_pages"] == 1 and res["stats"]["vision_pages"] == 1 and res["stats"]["local_ocr_pages"] == 1


def test_economy_plan_never_calls_a_model_even_with_readers_available(tmp_path, clean_env, fake_engine):
    clean_env.setenv("OPENAI_API_KEY", "k")
    fake_engine(reading=reading(0.4))
    pdf = scanned_pdf(tmp_path / "one.pdf", [PAGE_A])
    clean_env.setattr(pdf_pages, "build_work_pdf", lambda src, dst, scanned, tsv=None: (__import__("shutil").copy(src, dst), {})[1])
    called = []

    async def boom(*a):
        called.append(a)
        return []
    res = run(pipeline.process(pdf, plan=plan.resolve({"strategy": "economy"}), ocr_reader=boom, form_reader=boom))
    assert called == [] and res["pages"][0]["source"] == "ocr-local" and res["pages"][0]["reading"]["reasons"]
    assert res["reading"]["uses_models"] is False


def test_force_vision_sends_chosen_pages_to_the_models(tmp_path, clean_env, fake_engine):
    clean_env.setenv("OPENAI_API_KEY", "k")
    eng = fake_engine(reading=reading(0.99))
    pdf = scanned_pdf(tmp_path / "two.pdf", [PAGE_A, PAGE_A])
    clean_env.setattr(pdf_pages, "build_work_pdf", lambda src, dst, scanned, tsv=None: (__import__("shutil").copy(src, dst), {})[1])
    res = run(pipeline.process(pdf, plan=plan.resolve({"strategy": "balanced"}), ocr_reader=vision_ok, force_vision={2},
                               form_reader=lambda *a: asyncio.sleep(0, {"fields": {}, "table_rows": []})))
    by = {p["page"]: p["source"] for p in res["pages"]}
    assert by == {1: "ocr-local", 2: "ocr"} and eng.calls == 1


# ---- the API ------------------------------------------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    with TestClient(reload_app(tmp_path, monkeypatch)) as c:
        yield c


def test_engines_overview(client):
    r = client.get("/api/engines")
    assert r.status_code == 401
    body = client.get("/api/engines", headers=H).json()
    assert [e["id"] for e in body["local_engines"]] == ["tesseract", "rapidocr", "paddleocr", "doctr"]
    assert {p["id"] for p in body["providers"]} == {"openai", "anthropic", "gemini", "ollama", "custom"}
    assert [s["id"] for s in body["strategies"]] == ["economy", "balanced", "accuracy", "custom"]
    assert body["local_only"] is False and body["defaults"]["plan"]["strategy"] in ("balanced", "accuracy")
    assert "OPENAI_API_KEY" in next(p for p in body["providers"] if p["id"] == "openai")["hint"]
    health = client.get("/health").json()
    assert "local_engines" in health and "providers" in health and health["local_only"] is False


def test_workspace_reading_settings_round_trip(client, monkeypatch):
    wid = mk(client)
    url = f"/api/workspaces/{wid}/reading"
    assert client.get(url).status_code == 401
    got = client.get(url, headers=H).json()
    assert got["settings"] == {} and got["plan"]["strategy"] == got["strategy_default"]
    saved = client.put(url, json={"strategy": "economy", "escalate_below": 0.7}, headers=H)
    assert saved.status_code == 200 and saved.json()["plan"]["strategy"] == "economy" and saved.json()["plan"]["escalate_below"] == 0.7
    assert client.get(url, headers=H).json()["settings"] == {"strategy": "economy", "escalate_below": 0.7}
    other = mk(client, "Other")
    assert client.get(f"/api/workspaces/{other}/reading", headers=H).json()["settings"] == {}   # settings belong to one workspace
    bad = client.put(url, json={"strategy": "wild"}, headers=H)
    assert bad.status_code == 422 and "Choose" in bad.json()["detail"]
    assert client.put(url, json={"models": ["anthropic:claude-haiku-5-5"]}, headers=H).status_code == 422     # no Anthropic key here
    assert client.put(f"/api/workspaces/nope/reading", json={}, headers=H).status_code == 404
    assert client.delete(f"/api/workspaces/{wid}", headers=H).status_code == 204


def test_engine_test_endpoint(client, monkeypatch):
    assert client.post("/api/engines/test", json={"kind": "local", "id": "nope"}, headers=H).status_code == 404
    assert client.post("/api/engines/test", json={"kind": "other", "id": "x"}, headers=H).status_code == 422
    assert client.post("/api/engines/test", json={"kind": "model", "id": "no spaces allowed"}, headers=H).status_code == 422
    missing = next(e for e in client.get("/api/engines", headers=H).json()["local_engines"] if not e["ready"])
    r = client.post("/api/engines/test", json={"kind": "local", "id": missing["id"]}, headers=H).json()
    assert r["ok"] is False and "not installed" in r["error"]
    r = client.post("/api/engines/test", json={"kind": "model", "id": "anthropic:claude-haiku-5-5"}, headers=H).json()
    assert r["ok"] is False and "not available" in r["error"]                                    # no key: a clear message, not a 500
    if tess_available():
        r = client.post("/api/engines/test", json={"kind": "local", "id": "tesseract"}, headers=H).json()
        assert r["ok"] and r["score"] >= 0.75 and r["tokens"] == 0
    monkeypatch.setenv("LLM_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")

    async def fake_post(url, headers, body):
        return {"content": [{"type": "text", "text": '{"lines": ["Invoice No. 48213", "Date: 03/14/2026", "Total due $1,250.75", "Ref AB-9071"]}'}],
                "usage": {"input_tokens": 700, "output_tokens": 40}}
    monkeypatch.setattr(llm, "_post", fake_post)
    r = client.post("/api/engines/test", json={"kind": "model", "id": "anthropic:claude-haiku-5-5"}, headers=H).json()
    assert r["ok"] and r["score"] == 1.0 and r["tokens"] == 740


def test_upload_reading_choice_and_reuse(client, tmp_path, monkeypatch):
    from tests.make_packet import build
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    wid = mk(client)
    base = f"/api/workspaces/{wid}/extractions"
    send = lambda reading="": client.post(base, files={"file": ("p.pdf", pdf.read_bytes(), "application/pdf")}, data={"template": "auto", "reading": reading}, headers=H)
    assert send("wild").status_code == 422
    first = send("economy").json()
    done = wait(client, wid, first["id"])
    assert done["status"] == "done" and done["reading"]["strategy"] == "economy" and done["reading"]["uses_models"] is False
    assert send("economy").json().get("reused") is True                       # the same file under the same plan is not read again
    other = send("accuracy").json()
    assert other["id"] != first["id"] and other.get("reused") is not True      # a different plan is a different reading


def test_reread_makes_a_second_extraction_and_leaves_the_first(client, tmp_path, monkeypatch):
    from tests.make_packet import build
    pdf = tmp_path / "p.pdf"
    build(str(pdf))
    wid = mk(client)
    base = f"/api/workspaces/{wid}/extractions"
    first = client.post(base, files={"file": ("p.pdf", pdf.read_bytes(), "application/pdf")}, data={"template": "auto"}, headers=H).json()["id"]
    wait(client, wid, first)
    assert client.post(f"{base}/{first}/reread", json={}, headers=H).status_code == 503              # no model here: it must say so
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    assert client.post(f"{base}/{first}/reread", json={"strategy": "wild"}, headers=H).status_code == 422
    assert client.post(f"{base}/{first}/reread", json={"pages": [99]}, headers=H).status_code == 422
    assert client.post(f"{base}/nope/reread", json={}, headers=H).status_code == 404
    from app.services.reading import ocr as ocr_mod
    from tests import test_pipeline as tp
    monkeypatch.setattr(ocr_mod, "read_image", tp.fake_ocr)
    monkeypatch.setattr(pipeline.form_extractor, "_read", tp.fake_form)
    r = client.post(f"{base}/{first}/reread", json={"pages": [4]}, headers=H)
    assert r.status_code == 202 and r.json()["id"] != first
    done = wait(client, wid, r.json()["id"])
    assert done["status"] == "done" and done["filename"] == "p.pdf"
    page4 = next(p for p in done["pages"]["pages"] if p["page"] == 4)
    assert page4["source"] == "ocr"                                                                  # the page you picked went to the models
    assert client.get(f"{base}/{first}", headers=H).json()["status"] == "done"                      # the original is untouched
    assert len(client.get(base, headers=H).json()) == 2
    other = mk(client, "Other")
    assert client.post(f"/api/workspaces/{other}/extractions/{first}/reread", json={}, headers=H).status_code == 404
