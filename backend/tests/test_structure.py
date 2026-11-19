"""The structure of a page from its layout alone (services/extraction/structure.py)."""
from app.services.extraction import structure as st


def row(y, *cells, h=0.012):
    """One row: cells are (text, x0) or (text, x0, x1); y is the row's top as a fraction of the page."""
    return [(c[0], c[1], y, c[2] if len(c) > 2 else c[1] + 0.012 * len(c[0]) * 0.5, y + h) for c in cells]


def kinds(page):
    return [b["type"] for b in page["blocks"]]


def test_a_taller_line_is_a_heading_and_its_level_follows_its_size():
    page = st.build_page([row(0.05, ("Quarterly Report", 0.1), h=0.03), row(0.12, ("Revenue", 0.1), h=0.018),
                          row(0.16, ("Sales grew in the third quarter.", 0.1)), row(0.18, ("Costs were flat.", 0.1)), row(0.20, ("More text here.", 0.1))])
    heads = [b for b in page["blocks"] if b["type"] == "heading"]
    assert [h["text"] for h in heads] == ["Quarterly Report", "Revenue"] and heads[0]["level"] == 1 and heads[1]["level"] == 2


def test_consecutive_lines_form_one_paragraph_and_a_gap_starts_a_new_one():
    page = st.build_page([row(0.10, ("First line of text", 0.1)), row(0.115, ("second line of the same paragraph", 0.1)),
                          row(0.20, ("A new paragraph after a gap", 0.1)), row(0.30, ("Third", 0.1))])
    paras = [b["text"] for b in page["blocks"] if b["type"] == "paragraph"]
    assert paras[0] == "First line of text second line of the same paragraph" and paras[1].startswith("A new paragraph") and len(paras) == 3


def test_label_value_rows_group_and_a_wrapped_value_stays_with_its_label():
    page = st.build_page([row(0.10, ("Patient Name: Morgan Taylor", 0.1), ("Visit No.: 1", 0.6)),
                          row(0.125, ("History: pain started four weeks ago and", 0.1)),
                          row(0.14, ("has not stopped since", 0.1))])
    assert kinds(page) == ["key_value"]
    items = {i["label"]: i["value"] for i in page["blocks"][0]["items"]}
    assert items["Patient Name"] == "Morgan Taylor" and items["Visit No."] == "1"
    assert items["History"] == "pain started four weeks ago and has not stopped since"


def test_aligned_cells_become_a_table_and_a_header_row_names_the_columns():
    page = st.build_page([row(0.10, ("Code", 0.1), ("Service", 0.3), ("Units", 0.7)),
                          row(0.12, ("97110", 0.1), ("Therapeutic exercise", 0.3), ("2", 0.7)),
                          row(0.14, ("97140", 0.1), ("Manual therapy", 0.3), ("1", 0.7))])
    (tbl,) = page["blocks"]
    assert tbl["type"] == "table" and tbl["header"] and tbl["columns"] == ["Code", "Service", "Units"]
    assert tbl["rows"] == [["97110", "Therapeutic exercise", "2"], ["97140", "Manual therapy", "1"]]


def test_a_table_without_a_header_gets_numbered_columns_and_a_missing_cell_stays_empty():
    page = st.build_page([row(0.10, ("Rent", 0.1), ("1,200.00", 0.6)), row(0.12, ("Utilities", 0.1), ("85.50", 0.6)), row(0.14, ("Notes", 0.1))])
    tbl = page["blocks"][0]
    assert tbl["type"] == "table" and not tbl["header"] and tbl["columns"] == ["Column 1", "Column 2"] and tbl["rows"][0] == ["Rent", "1,200.00"]


def test_long_text_set_in_two_columns_is_not_taken_for_a_table():
    long = "this is a long sentence of running text that goes on and on across the column"
    page = st.build_page([row(0.10, (long, 0.1), (long, 0.55)), row(0.12, (long, 0.1), (long, 0.55)), row(0.14, (long, 0.1), (long, 0.55))])
    assert "table" not in kinds(page)


def test_list_items_are_grouped_and_ordered_lists_are_told_apart():
    bullets = st.build_page([row(0.10, ("• apples", 0.1)), row(0.12, ("• pears", 0.1))])["blocks"][0]
    numbered = st.build_page([row(0.10, ("1. first", 0.1)), row(0.12, ("2. second", 0.1))])["blocks"][0]
    assert bullets["type"] == "list" and bullets["items"] == ["apples", "pears"] and not bullets["ordered"]
    assert numbered["items"] == ["first", "second"] and numbered["ordered"]


def test_dates_amounts_phones_and_emails_are_listed_with_their_block():
    page = st.build_page([row(0.10, ("Invoice date: 08/12/2026", 0.1)), row(0.20, ("Total due $1,250.00 by 5%", 0.1)),
                          row(0.30, ("Call (201) 447-5757 or write to ap@example.com", 0.1))])
    found = {(e["type"], e["value"]) for e in page["entities"]}
    assert {("date", "08/12/2026"), ("amount", "$1,250.00"), ("percent", "5%"), ("phone", "(201) 447-5757"), ("email", "ap@example.com")} <= found


def test_fax_stamps_are_left_out_of_the_structure():
    page = st.build_page([row(0.01, ("From Sample 1.201.555.0121 Wed Nov 11 2026 MST Page 4 of 9", 0.1)), row(0.10, ("Real content here", 0.1))])
    assert [b.get("text") for b in page["blocks"]] == ["Real content here"]


def test_a_page_with_no_layout_is_built_from_its_lines_and_says_so():
    page = st.build_from_lines(["INVOICE", "Patient Name: Morgan Taylor | Visit No.: 1", "Code | Service | Units", "97110 | Exercise | 2", "97140 | Manual | 1",
                                "the sentence starts here and", "continues on the next line"])
    assert page["layout"] is False and all("bbox" not in b for b in page["blocks"])
    assert kinds(page)[:3] == ["heading", "key_value", "table"]
    assert page["blocks"][-1]["text"] == "the sentence starts here and continues on the next line"


def test_an_empty_page_gives_no_blocks():
    assert st.build_page([]) == {"blocks": [], "entities": [], "layout": True}


def test_the_pipeline_gives_every_page_a_structure_and_the_export_groups_it_by_document():
    import asyncio
    import tempfile
    from types import SimpleNamespace
    from app.services import export, pipeline
    from tests.make_packet import build
    path = tempfile.mkdtemp() + "/packet.pdf"
    build(path)
    result = asyncio.run(pipeline.process(path))
    assert all("structure" in p for p in result["pages"])
    digital = [p for p in result["pages"] if p["source"] == "text-layer" and p["text"].strip()]
    assert digital and any(b["type"] in ("heading", "key_value", "paragraph") for p in digital for b in p["structure"]["blocks"])
    ex = SimpleNamespace(id="x", filename="packet.pdf", result=result)
    out = export.structure_json(ex)
    assert [d["doc_index"] for d in out["documents"]] == [d["doc_index"] for d in result["documents"]]
    assert all("structure" in p for p in export.pages_json(ex)["pages"])             # pages.json is the full per-page record


def test_a_table_found_by_another_extractor_replaces_its_rows_but_not_the_heading_in_its_box():
    rows = [row(0.05, ("INCOME STATEMENTS", 0.1), h=0.02), row(0.12, ("Product", 0.1), ("15,089", 0.6)), row(0.14, ("Service", 0.1), ("67,797", 0.6)), row(0.30, ("Refer to the notes.", 0.1))]
    given = [{"bbox": [0.05, 0.03, 0.9, 0.2], "columns": ["Line item", "Col 1"], "rows": [["Product", "15,089"], ["Service", "67,797"]]}]
    page = st.build_page(rows, tables=given)
    assert kinds(page) == ["heading", "table", "paragraph"]
    assert page["blocks"][1]["columns"] == ["Line item", "Column 1"] and page["blocks"][1]["rows"][1] == ["Service", "67,797"]
