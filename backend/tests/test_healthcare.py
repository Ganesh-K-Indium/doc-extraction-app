"""Healthcare documents seen in the field: an annotated lab report, a form of symbol-font check boxes, a claim explanation."""
import asyncio

import pymupdf as fitz

from app.services import pipeline
from app.services.documents import template_draft
from app.services.extraction import structure
from app.services.reading import pdf_pages


def _row(text, x0=0.1, y=0.1):
    return [(text, x0, y, x0 + 0.1, y + 0.01)]


# ---- check boxes ------------------------------------------------------------------------------------------------

def test_a_question_then_boxes_names_the_group_and_leaves_the_follow_up_out():
    items = structure._box_items("Flu Vaccine: ☐ Yes ☐ No ☐ Don't know If yes, when?")
    assert [i["label"] for i in items] == ["Yes", "No", "Don't know"]
    assert {i["group"] for i in items} == {"Flu Vaccine"}


def test_yes_no_after_the_text_still_reads_the_old_way():
    items = structure._box_items("Taken in the past 90 days. Yes ☒ No ☐")
    assert [(i["label"], i["checked"]) for i in items] == [("Yes", True), ("No", False)]


def test_a_ruled_grid_of_boxes_becomes_options_and_a_cell_without_a_box_continues_the_one_above():
    table = {"columns": ["MEDICAL HISTORY: (Please check all that apply)", "", ""], "rows": [
        ["☐ heart disease", "☐ emphysema", "☐ sexually transmitted"],
        ["☐ asthma", "☐ polio", "disease/herpes"]]}
    items = structure._box_table_items(table)
    assert [i["label"] for i in items] == ["heart disease", "emphysema", "sexually transmitted disease/herpes", "asthma", "polio"]
    assert {i["group"] for i in items} == {"MEDICAL HISTORY"}
    assert structure._box_table_items({"columns": ["a", "b"], "rows": [["Name", "Dose"], ["x", "y"], ["z", "w"]]}) == []


def test_a_symbol_font_letter_is_read_as_the_box_it_draws(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Heart disease", fontname="helv", fontsize=11)
    page.insert_text((50, 100), "¨", fontname="symb", fontsize=11)         # Symbol font: not a letter on the page
    path = tmp_path / "boxes.pdf"
    doc.save(path)
    got = pdf_pages.analyze_page(str(path), 1)
    assert any(w["text"] == "Heart" for w in got["words"])


def test_a_line_to_write_on_is_an_empty_value():
    page = structure.build_page([[("Pregnancies:", 0.1, 0.1, 0.3, 0.11), ("_______", 0.4, 0.1, 0.6, 0.11)]])
    items = [i for b in page["blocks"] if b["type"] == "key_value" for i in b["items"]]
    assert items and items[0]["label"] == "Pregnancies" and not items[0]["value"]


# ---- a long form beside a column of text -----------------------------------------------------------------------

def test_a_report_with_a_numbered_key_beside_it_reads_the_report_then_the_key():
    rows = []
    for n in range(30):
        y = 0.1 + n * 0.02
        rows.append([(f"Test {n}", 0.05, y, 0.12, y + 0.01), ("6.9", 0.2, y, 0.23, y + 0.01), ("K/mcL", 0.3, y, 0.36, y + 0.01),
                     (f"{n}. Explains the line of the report that this entry belongs to, in a sentence of its own" if n % 2 == 0
                      else "and carries on over the next line of the same note, in running words", 0.66, y, 0.97, y + 0.01)])
    ordered = structure._reading_order(rows)
    first_right = next(i for i, r in enumerate(ordered) if r[0][1] >= 0.6)
    assert first_right == 30 and all(r[0][1] < 0.6 for r in ordered[:30])


def test_a_table_with_a_description_column_keeps_its_rows_whole():
    rows = [[(f"PIN{n}", 0.1, 0.1 + n * 0.02, 0.16, 0.11 + n * 0.02), (f"Input {n}", 0.2, 0.1 + n * 0.02, 0.26, 0.11 + n * 0.02),
             ("Receives the signal and passes it to the stage that follows it", 0.3, 0.1 + n * 0.02, 0.8, 0.11 + n * 0.02)] for n in range(12)]
    assert structure._reading_order(rows) == rows


# ---- tables that run on, banners, template drafts ---------------------------------------------------------------

def test_a_table_ends_at_its_last_row_of_figures():
    words = [(10, 100 + 20 * i, 40, 110 + 20 * i, "50.00") for i in range(3)] + [(60, 100 + 20 * i, 90, 110 + 20 * i, "0.00") for i in range(3)] \
        + [(110, 100 + 20 * i, 140, 110 + 20 * i, "12.00") for i in range(3)]
    t = {"bbox": [0, 90, 200, 400], "headers": [], "method": "layout",
         "rows": [["a", "50.00", "0.00", "12.00"], ["b", "50.00", "0.00", "12.00"], ["c", "50.00", "0.00", "12.00"], ["a note under it", "", "", ""], ["another", "", "", ""]]}
    got = pdf_pages._trim_trailing(t, words)
    assert len(got["rows"]) == 3 and got["bbox"][3] < 200


def test_a_form_titled_in_its_banner_is_named_by_it_not_by_a_column_heading():
    def page(n, label):
        return {"page": n, "text": "", "classification": {"by": "layout", "label": label, "title": label, "kind": None},
                "structure": {"blocks": [{"type": "paragraph", "text": "x"}] * 3, "running": [{"text": "Outpatient Intake Form", "where": "top"}, {"text": "DEPARTMENT OF MEDICINE", "where": "top"}]}}
    assert pipeline._banner([page(1, "First"), page(2, "First"), page(3, "First")]) == "Outpatient Intake Form"
    assert pipeline._weak_label("First") and pipeline._weak_label("Name of Drug")
    assert not pipeline._weak_label("Electrical Characteristics")


def test_a_blank_form_draft_lists_a_header_repeated_on_every_page_once_and_a_question_with_boxes_as_a_choice():
    page1 = {"title": "Intake", "fields": [{"label": "Patient Name", "section": None, "type": "text", "required": False},
                                           {"label": "Smoker?", "section": None, "type": "text", "required": False}],
             "choice_groups": [{"label": "Smoker?", "section": None, "options": ["Yes", "No"], "multiple": False, "required": False}], "tables": []}
    page2 = {"title": "Intake", "fields": [{"label": "Patient Name", "section": None, "type": "text", "required": False},
                                           {"label": "Occupation", "section": None, "type": "text", "required": False}], "choice_groups": [], "tables": []}
    replies = iter([page1, page2])

    async def reader(model, jpeg, prompt):
        return next(replies)

    import pymupdf
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "blank.pdf")
        doc = pymupdf.open(); doc.new_page(); doc.new_page(); doc.save(path)
        drafted = asyncio.run(template_draft.draft_from_blank(path, ["m"], reader=reader))
    labels = [f["label"] for s in drafted["template"]["sections"] for f in s["fields"]]
    assert labels.count("Patient Name") == 1 and labels.count("Smoker?") == 1 and "Occupation" in labels


# ---- blank tables, stacked column labels, boxes that are not tables ---------------------------------------------

def _page_with_rules(tmp_path, header, rows=4):
    doc = fitz.open()
    page = doc.new_page()
    x = 50
    for label in header:
        page.insert_text((x, 100), label, fontname="helv", fontsize=10)
        x += 150
    y = 104
    for _ in range(rows + 1):
        page.draw_line((40, y), (560, y))
        y += 16
    path = tmp_path / "blank.pdf"
    doc.save(path)
    return str(path)


def test_column_labels_over_empty_ruled_lines_are_a_blank_table(tmp_path):
    got = pdf_pages.analyze_page(_page_with_rules(tmp_path, ["Name of Drug", "Dose", "Times/Day"]), 1)
    blank = [t for t in got["tables"] if t["method"] == "blank"]
    assert blank and blank[0]["headers"] == ["Name of Drug", "Dose", "Times/Day"] and len(blank[0]["rows"]) == 4


def test_a_label_with_a_colon_over_rules_is_not_a_blank_table(tmp_path):
    got = pdf_pages.analyze_page(_page_with_rules(tmp_path, ["Name:", "Date:"]), 1)
    assert not [t for t in got["tables"] if t["method"] == "blank"]


def test_labels_stacked_over_two_lines_make_the_columns_and_values_go_under_their_label():
    def w(x0, y, text):
        return (x0, y, x0 + 6 * len(text), y + 9, text)
    heads = [(10, "Service", "Code"), (110, "Not", "Covered"), (200, "Reason", "Code"), (300, "Total", "Amount"), (400, "Paid", "At"), (500, "Net", "Due")]
    words = [w(x, 100, a) for x, a, _ in heads] + [w(x, 111, b) for x, _, b in heads]
    for y, vals in ((140, ["MD", "336.00", "03", "400.00", "100%", "7.00"]), (160, ["MD", "24.55", "03", "100.00", "100%", "8.00"])):
        words += [w(x, y, v) for (x, _, _), v in zip(heads, vals)]
    rows = [["Service Total", "Not Reason", "Covered Code", "Paid", "Net"], ["Code Amount", "", "", "At", "Due"],
            ["MD", "336.00 03", "400.00", "100%", "7.00"], ["MD", "24.55 03", "100.00", "100%", "8.00"]]
    t = {"bbox": [5, 95, 560, 175], "headers": [], "rows": rows, "method": "layout"}
    got = pdf_pages._rebuild_by_header(t, words)
    assert got is not t
    assert got["headers"] == ["Service Code", "Not Covered", "Reason Code", "Total Amount", "Paid At", "Net Due"]
    assert got["rows"][1] == ["MD", "336.00", "03", "400.00", "100%", "7.00"]


def test_a_box_of_ticks_and_a_box_of_labels_are_not_tables():
    from app.services.extraction import digital
    ticks = {"headers": ["☐ heart disease", "☐ asthma"], "rows": [["☐ polio", "☐ gout"], ["☐ stroke", "☐ seizure"]]}
    labels = {"headers": ["Patient Name:", "MR#:"], "rows": [["DATE:", ""]]}
    notes = {"headers": ["The amount applied to the", "deductible on this claim"], "rows": [["off by the provider or a", "charge the patient is"]]}
    data = {"headers": ["Test", "Result"], "rows": [["WBC", "6.9"], ["RBC", "4.7"]]}
    assert digital._not_a_table(ticks) and digital._not_a_table(labels) and digital._not_a_table(notes)
    assert not digital._not_a_table(data)


def test_a_table_is_not_named_after_an_address_or_a_barcode():
    from app.services.extraction import digital
    lines = ["PO BOX 000", "IIIIIIIIIIIIIIIIIIIIII", "QUERIES: [Comments]", "Dates of Service  Total"]
    assert digital.table_title(lines, "Dates of Service") is None


def test_a_box_of_label_cells_gives_its_pairs_even_when_a_value_has_two_parts():
    from app.services.extraction import digital
    t = {"rows": [["SPEC #:", "223456", "", "Collection Date/Time:", "", "02/10/14", "14:30"], ["", "", "", "Received Date/Time:", "", "02/10/14", "15:00"],
                  ["SPECIMEN:", "Whole blood", "", "", "", "", ""]]}
    assert digital._box_pairs(t) == [("SPEC #", "223456"), ("Collection Date/Time", "02/10/14 14:30"), ("Received Date/Time", "02/10/14 15:00"), ("SPECIMEN", "Whole blood")]


def test_a_models_pick_of_a_type_must_be_named_by_the_page():
    from app.services.documents import classify
    assert not classify._names_the_page("Physical therapy initial examination", "Outpatient Intake Form. Do you have physical handicaps? How much pain?")
    assert classify._names_the_page("Physical therapy initial examination", "PHYSICAL THERAPY INITIAL EXAMINATION  Patient: ...")
    assert classify._names_the_page("Daily note", "Daily note for today")


def test_numbers_in_callout_circles_do_not_count_against_a_table(tmp_path):
    from app.services.extraction import digital
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 100), "Result 6.9", fontname="helv", fontsize=10)
    for n, y in ((13, 140), (14, 180)):
        page.draw_circle((200, y), 8, color=(0, 0.5, 0.3), fill=(0, 0.6, 0.4))
        page.insert_text((196, y + 3), str(n), fontname="helv", fontsize=8)
    path = tmp_path / "callouts.pdf"
    doc.save(path)
    words = digital._words_in(str(path), 1, [0, 0, 400, 300])
    assert "13" not in words and "14" not in words and "6.9" in words
