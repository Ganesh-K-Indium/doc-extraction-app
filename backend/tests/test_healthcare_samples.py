"""Real sample documents (sample_data/healthcare): each test runs on the file when it is present and is skipped when it is not."""
import os

import pytest

from app.services.extraction import digital
from app.services.reading import locate, pdf_pages

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "sample_data", "healthcare")


def sample(name: str) -> str:
    path = os.path.normpath(os.path.join(ROOT, name))
    if not os.path.exists(path):
        pytest.skip(f"{name} is not downloaded")
    return path


def test_two_column_label_table_keeps_its_first_row_as_data():
    a = pdf_pages.analyze_page(sample("claims/ub04_carepatron_example.pdf"), 1)
    t = a["tables"][0]
    assert t["header_rows"] == 1 and t["headers"] == ["Field", "Information"]
    assert t["rows"][1][0] == "Provider Name"


def test_field_in_a_value_column_is_named_by_the_label_in_the_column_to_its_left():
    a = pdf_pages.analyze_page(sample("claims/ub04_carepatron_example.pdf"), 1)
    fields, _ = digital.fields_from_widgets(a["widgets"], a["words"], a["size"])
    labels = [f["label"] for f in fields]
    assert labels[:4] == ["Provider Name", "Provider Address", "Provider Telephone Number", "Patient Control Number"]
    assert "Type of Bill" in labels and "Federal Tax Number" in labels


def test_label_set_over_two_lines_in_the_left_column_is_joined():
    a = pdf_pages.analyze_page(sample("clinical/discharge_summaries_example2_carepatron.pdf"), 1)
    fields, _ = digital.fields_from_widgets(a["widgets"], a["words"], a["size"])
    assert "Reason for Admission" in [f["label"] for f in fields]


def test_claim_table_without_rules_gets_its_captions_and_wrapped_cells():
    a = pdf_pages.analyze_page(sample("payer/eob_cms_sample.pdf"), 1)
    t = max(a["tables"], key=lambda t: len(t["headers"]))
    assert len(t["headers"]) == 12 and t["headers"][0] == "Line No." and t["headers"][-1] == "Remark Code"
    assert t["rows"][1][:4] == ["1", "3/20/22- 3/20/22", "Medical care", "Paid"]
    assert t["rows"][-1][3] == "Total" and t["rows"][-1][4] == "$406.60"


def test_cells_are_located_in_reading_order_so_repeats_do_not_collapse():
    path = sample("payer/eob_maryland_health_dept.pdf")
    boxes = locate.in_order(path, 1, [30, 300, 600, 420], ["50.00", "0.00", "0.00", "0.00"])
    assert all(boxes)
    xs = [b[0] for b in boxes[1:]]
    assert xs == sorted(xs) and len(set(xs)) == 3          # three different "0.00" cells, left to right


def test_symbol_only_cell_is_located():
    path = sample("clinical/lab_cbc_sample_report_testing_com.pdf")
    boxes = locate.in_order(path, 1, [0, 0, 612, 792], ["%"])
    assert boxes[0] is not None


def test_a_value_the_text_does_not_contain_is_pointed_at_beside_its_label():
    path = sample("clinical/lab_cbc_sample_report_testing_com.pdf")
    box = locate.beside(path, 1, "Patient ID:")
    label = locate.find(path, 1, "Patient ID")
    assert box and label and box[0] >= label[2] and abs(box[1] - label[1]) < 4          # to the right of the label, on its line
    assert locate.beside(path, 1, "A label that is not on the page") is None
