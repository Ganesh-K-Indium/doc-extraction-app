import asyncio

import pytest

from app.services import checkboxes, classify, cross, form_extractor, kv, locate, normalize as N, ocr, pdf_pages, pipeline, router, validation
from app.services.tess import available as tess_available
from tests.make_packet import build


@pytest.fixture(scope="module")
def pdf(tmp_path_factory):
    p = tmp_path_factory.mktemp("pkt") / "packet.pdf"
    build(str(p))
    return str(p)


# ---- units ------------------------------------------------------------------------------------------------------

def test_fax_stamp_split():
    lines = ["From Sample Health 1.201.555.0121 Wed Nov 11 09:21:38 2026 MST Page 3 of 9", "Last Name: Morgan",
             "PAGE 3/9 * RCVD AT 10/12/2026 11:21:43 AM [Eastern Standard Time] * SVR:FAX-MGA/0 * DNIS:6403 * CSID:201-447-5750 * ANI: 1 * DURATION (mm-ss):07-04"]
    content, meta = pdf_pages.strip_fax_stamp(lines)
    assert content == ["Last Name: Morgan"]
    assert meta["fax_page"] == 3 and meta["fax_pages"] == 9 and meta["dnis"] == "6403" and meta["duration"] == "07-04"


def test_normalize():
    assert N.normalize("07/01/1970", "date") == "1970-07-01"
    assert N.normalize("99-9999999", "tax_id") == "999999999"
    assert N.normalize(" m54.2 ", "icd10") == "M542"


def test_merge_field_statuses():
    assert form_extractor.merge_field("Morgan", "MORGAN", "text", True)["status"] == "agreed"
    r = form_extractor.merge_field("1999999999", "1999999990", "npi", True)
    assert r["status"] == "review" and r["alternatives"] == ["1999999990"]
    assert form_extractor.merge_field(None, None, "text", True)["status"] == "empty"
    assert form_extractor.merge_field("x", None, "text", False)["status"] == "single"
    assert form_extractor.merge_field("9[?]", "93", "text", True)["status"] == "review"


def test_glyph_state():
    assert checkboxes.glyph_state("☑ ROUTINE*  ☐ URGENT*", "ROUTINE") is True
    assert checkboxes.glyph_state("☑ ROUTINE*  ☐ URGENT*", "URGENT") is False
    assert checkboxes.glyph_state("nothing here", "URGENT") is None


def test_kv_parser():
    pairs = kv.parse_kv(["Patient Name: Morgan Taylor Date of Initial Examination: 08/12/2026", "Plan: Begin Plan as Outlined"])
    c = kv.canonical(pairs)
    assert c["patient.name"] == "Morgan Taylor" and c["exam_date"] == "08/12/2026"
    assert kv.cpt_codes("GP:97110 x GP:97140 GP:97110") == ["97110", "97140"]


def test_classification_and_segmentation():
    assert classify.classify_text("Provider Prior Authorization Request Form ... " * 3)["type"] == "prior_auth_form"
    assert classify.classify_text("")["type"] == "blank_or_logo"
    pages = [{"page": i + 1, "classification": {"type": t, "label": t}} for i, t in
             enumerate(["fax_cover", "blank_or_logo", "prior_auth_form", "pt_initial_exam", "pt_initial_exam", "daily_note"])]
    docs = classify.segment(pages)
    assert [(d["type"], d["pages"]) for d in docs] == [("fax_cover", [1, 2]), ("prior_auth_form", [3]), ("pt_initial_exam", [4, 5]), ("daily_note", [6])]


# ---- PDF-backed -------------------------------------------------------------------------------------------------

def test_pixel_checkboxes(pdf):
    out = checkboxes.pixel_states(pdf, 3, {"ROUTINE": (0, 200), "URGENT": (0, 200), "TRANSPLANT": (0, 200)})
    assert out == {"ROUTINE": True, "URGENT": False, "TRANSPLANT": False}


def test_scan_detection(pdf):
    assert pdf_pages.analyze_page(pdf, 4)["scanned"] is True
    assert pdf_pages.analyze_page(pdf, 3)["scanned"] is False


async def fake_ocr(model, jpeg):
    return ["Last Name*: Scanned", "[?] smudge"] if not model.endswith("mini") else ["Last Name*: Scanned", "7 smudge"]


async def fake_form(model, jpeg, prompt):
    """Answers per template, like a model would: the prompt names the document."""
    mini = model.endswith("mini")
    if "Prior Authorization" in prompt:
        f = {"member.last_name": "Morgan", "member.first_name": "Taylor", "member.dob": "07/01/1970", "member.member_id": "9000001234",
             "ordering_provider.tax_id": "99-9999999", "ordering_provider.npi": "1999999999",
             "facility.name": "SAMPLE HEALTH ASSOCIATES", "facility.tax_id": "99-9999998",
             "facility.npi": "199999999" if not mini else "1999999990", "clinical.dx_code_1": "M54.2"}
        return {"fields": f, "table_rows": [
            {"qty": "12 VISITS", "code": "97110", "description": "THERAPEUTIC EXERCISE", "charge": "180.00"},
            {"qty": "12 VISITS", "code": "97140", "description": "MANUAL THERAPY", "charge": "150.00"}]}
    if "initial examination" in prompt:
        return {"fields": {"patient.name": "Morgan Taylor", "patient.dob": "01/15/1975", "diagnosis": "ICD10: M54.2: Cervicalgia"}, "table_rows": []}
    if "Daily note" in prompt:
        return {"fields": {"patient.name": "Morgan Taylor", "patient.dob": "01/15/1975"},
                "table_rows": [{"code": "GP:97110", "description": "Therapeutic Exercise", "units": "1"},
                               {"code": "GP:97162", "description": "PT Evaluation", "units": "1"}]}
    return {"fields": {}, "table_rows": []}


async def fake_ask(model, prompt):
    return '{"type": "unknown"}'


@pytest.fixture(scope="module")
def result(pdf):
    return asyncio.run(pipeline.process(pdf, ocr_reader=fake_ocr, form_reader=fake_form, model_ask=fake_ask))


def test_pages_json(result):
    pages = {p["page"]: p for p in result["pages"]}
    assert len(pages) == 6
    assert pages[1]["page_meta"]["fax_pages"] == 6 and "RCVD" not in pages[1]["text"]
    assert pages[2]["classification"]["type"] == "blank_or_logo"
    assert pages[3]["source"] == "text-layer" and pages[3]["classification"]["type"] == "prior_auth_form"
    assert pages[4]["source"] == "ocr"
    review = [l for l in pages[4]["lines"] if l["status"] == "review"]
    assert review and review[0]["alternatives"]
    # the untitled scanned page 4 continues the form before it
    assert [(d["type"], d["pages"]) for d in result["documents"]] == [
        ("fax_cover", [1, 2]), ("prior_auth_form", [3, 4]), ("pt_initial_exam", [5]), ("daily_note", [6])]


def test_form_fields(result):
    form = result["forms"][0]
    f = form["fields"]
    assert f["review_type"]["value"] == "ROUTINE" and f["review_type"]["method"] == "pixel"
    assert f["member.last_name"]["status"] == "agreed" and f["member.last_name"]["bbox"] is not None
    assert f["facility.npi"]["status"] == "review"
    # same label, different sections -> different boxes
    assert f["ordering_provider.tax_id"]["bbox"] != f["facility.tax_id"]["bbox"]
    assert f["ordering_provider.tax_id"]["bbox"][1] < f["facility.tax_id"]["bbox"][1]
    assert [r["code"]["value"] for r in form["tables"]["cpt"]] == ["97110", "97140"]


def test_validation(result):
    rules = {(v["rule"], v.get("field")) for v in result["validation"]}
    assert ("cross_mismatch", "member.dob") in rules                       # form 1970 vs exam/note 1975
    assert ("required_missing", "ordering_provider.first_name") in rules
    assert ("cross_set_diff", None) in rules                               # 97140 requested, not in the daily note
    assert ("format", "facility.npi") in rules                             # 9-digit NPI
    assert any(v["rule"] == "cross_not_mentioned" for v in result["validation"])  # M54.2 absent from the daily note
    assert result["stats"]["errors"] >= 2


def test_clinical_documents_use_templates(result):
    by = {f["doc_type"]: f for f in result["forms"]}
    assert by["pt_initial_exam"]["fields"]["patient.dob"]["value"] == "01/15/1975"
    assert [r["code"]["value"] for r in by["daily_note"]["tables"]["billing"]] == ["GP:97110", "GP:97162"]


def test_pipeline_without_models(pdf):
    r = asyncio.run(pipeline.process(pdf))  # LLM disabled: embedded text + checkboxes only
    assert r["forms"][0]["fields"]["review_type"]["value"] == "ROUTINE"
    assert r["forms"][0]["fields"]["member.last_name"]["status"] == "empty"


# ---- router / decision layer ------------------------------------------------------------------------------------

def test_reader_decisions(pdf):
    digital = router.decide_reader(router.profile_page(pdf_pages.analyze_page(pdf, 3)), llm_available=True)
    scan = router.decide_reader(router.profile_page(pdf_pages.analyze_page(pdf, 4)), llm_available=True)
    scan_no_llm = router.decide_reader(router.profile_page(pdf_pages.analyze_page(pdf, 4)), llm_available=False)
    assert digital["reader"] == "text_layer" and scan["reader"] == "ocr_dual" and scan_no_llm["reader"] == "text_layer_unverified"
    assert scan["reasons"]


def test_extractor_decisions():
    assert router.decide_extractor("prior_auth_form")["extractor"] == "template_form"
    assert router.decide_extractor("daily_note")["extractor"] == "template_form"
    assert router.decide_extractor("fax_cover")["extractor"] == "skip"
    assert router.decide_extractor("blank_or_logo")["extractor"] == "skip"
    assert router.decide_extractor("something_new")["extractor"] == "kv"  # unregistered: generic label/value reading


def test_routes_are_recorded(result):
    assert result["pages"][3]["route"]["reader"] == "ocr_dual"
    assert all("route" in d for d in result["documents"])
    assert {d["type"]: d["route"]["extractor"] for d in result["documents"]}["prior_auth_form"] == "template_form"


def test_model_classifier_only_picks_registered_types():
    async def good(model, prompt):
        return '{"type": "daily_note"}'

    async def invented(model, prompt):
        return '{"type": "radiology_report"}'

    async def boom(model, prompt):
        raise RuntimeError("down")

    assert asyncio.run(classify.classify_with_model("x", ["m"], good))["type"] == "daily_note"
    assert asyncio.run(classify.classify_with_model("x", ["m"], invented))["type"] == "unknown"
    assert asyncio.run(classify.classify_with_model("x", ["m"], boom))["type"] == "unknown"


def test_model_checkbox_fallback():
    agreed = form_extractor.model_checkbox("enum", "ROUTINE", "ROUTINE", True)
    assert agreed["value"] == "ROUTINE" and agreed["status"] == "agreed" and agreed["method"] == "model"
    split = form_extractor.model_checkbox("enum", "ROUTINE", "URGENT", True)
    assert split["status"] == "review" and split["alternatives"]
    lone = form_extractor.model_checkbox("checkbox", True, None, False)
    assert lone["value"] is True and lone["status"] == "review"
    multi = form_extractor.model_checkbox("multi_enum", ["Office"], ["Office"], True)
    assert multi["value"] == ["Office"] and multi["status"] == "agreed"
    assert form_extractor.model_checkbox("enum", None, None, True) is None


# ---- Tesseract layer / highlighting on a real scan -----------------------------------------------------------------

def _scan_pdf(path):
    """A page that is only a picture of text, as a fax is."""
    import pymupdf as fitz
    src = fitz.open()
    p = src.new_page(width=612, height=792)
    p.insert_text((60, 120), "Member ID 9000001234", fontsize=16)
    p.insert_text((60, 160), "Facility Name SAMPLE HEALTH ASSOCIATES", fontsize=16)
    png = p.get_pixmap(dpi=200).tobytes("png")
    out = fitz.open()
    q = out.new_page(width=612, height=792)
    q.insert_image(q.rect, stream=png)
    out.save(path)


@pytest.mark.skipif(not tess_available(), reason="Tesseract not installed")
def test_tesseract_layer_makes_scans_highlightable(tmp_path):
    from app.services import locate
    src, work = str(tmp_path / "scan.pdf"), str(tmp_path / "scan.work.pdf")
    _scan_pdf(src)
    assert pdf_pages.analyze_page(src, 1)["words"] == []              # a picture: nothing to highlight
    assert pdf_pages.build_work_pdf(src, work, {1}) == {1: "ok"}
    box = locate.find(work, 1, "9000001234", "Member ID")
    assert box and 50 < box[0] < 400 and 100 < box[1] < 130           # found where it was drawn
    assert locate.find(work, 1, "9000001235", "Member ID")            # one wrong digit still lands on the right place
    assert locate.find(work, 1, "no such value anywhere", None) is None


def test_prefers_reading_that_matches_page_text():
    cell = {"value": "900001234", "status": "review", "alternatives": ["9000001234"]}
    form_extractor._prefer_page_text(cell, "text", locate.alnum("Member ID 9000001234 Last Name"))
    assert cell["value"] == "9000001234" and cell["alternatives"] == ["900001234"] and cell["status"] == "review"
    both = {"value": "aaaa1", "status": "review", "alternatives": ["bbbb2"]}
    form_extractor._prefer_page_text(both, "text", locate.alnum("nothing relevant"))
    assert both["value"] == "aaaa1"


# ---- cross-document checks are template-driven ------------------------------------------------------------------------

def test_cross_checks_use_only_template_declarations():
    tpl = {"canonical": {"id.owner": {"kind": "name", "label": "Owner", "fields": ["owner"]},
                         "id.date": {"kind": "date", "label": "Issue date", "fields": ["issued"]}}}
    def doc(i, owner, issued):
        return {"doc_index": i, "doc_type": "invoice" if i == 0 else "receipt", "pages": [i + 1], "template": tpl, "text": "",
                "fields": {"owner": {"value": owner}, "issued": {"value": issued}}, "tables": {}}
    ok = cross.check([doc(0, "Acme Corp", "01/02/2026"), doc(1, "ACME corp", "2026-01-02")])
    assert ok == []
    bad = cross.check([doc(0, "Acme Corp", "01/02/2026"), doc(1, "Other Ltd", "01/03/2026")])
    assert {v["detail"].split(" is ")[0] for v in bad} == {"Owner", "Issue date"} and all(v["severity"] == "error" for v in bad)


def test_third_opinion_flags_shared_misread():
    cell = {"value": "NEUROMUSCLAR", "status": "agreed", "alternatives": []}
    form_extractor._third_opinion(cell, ([0, 0, 1, 1], "NEUROMUSCULAR", 0.96))
    assert cell["status"] == "review" and cell["alternatives"] == ["NEUROMUSCULAR"]
    exact = {"value": "ROUTINE VISIT", "status": "agreed", "alternatives": []}
    form_extractor._third_opinion(exact, ([0, 0, 1, 1], "ROUTINE VISIT", 1.0))
    assert exact["status"] == "agreed"
    absent = {"value": "SOMETHING LONG", "status": "agreed", "alternatives": []}
    form_extractor._third_opinion(absent, None)
    assert absent["status"] == "agreed"          # Tesseract not finding it is not evidence of an error
