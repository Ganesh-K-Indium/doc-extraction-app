from app.services.quality import healthcare, validation


def F(label, value, **kw):
    return {"label": label, "value": value, "status": "agreed", **kw}


def rules(found):
    return {f["rule"] for f in found}


def test_npi_check_digit():
    assert healthcare.npi_valid("1234567893")          # the published example NPI
    assert not healthcare.npi_valid("1234567890") and not healthcare.npi_valid("12345")


def test_a_wrong_npi_icd10_cpt_and_dose_are_flagged_and_right_ones_are_not():
    fields = {"npi": F("Provider NPI", "1234567890"), "npi2": F("Billing NPI", "1234567893"),
              "dx": F("Diagnosis (ICD-10)", "E11.9, I10, 9999"), "cpt": F("CPT code", "99213, 1234"),
              "dose": F("Dose", "500"), "dose2": F("Dose (Strength)", "500 mg")}
    got = healthcare.check(fields, {})
    assert [f["field"] for f in got if f["rule"] == "npi_check_digit"] == ["npi"]
    assert [f["detail"] for f in got if f["rule"] == "icd10_format"] == ["'9999' does not look like an ICD-10 code."]
    assert [f["detail"] for f in got if f["rule"] == "cpt_format"] == ["'1234' does not look like a CPT or HCPCS code."]
    assert [f["field"] for f in got if f["rule"] == "dose_unit"] == ["dose"]


def test_birth_and_service_dates():
    fields = {"dob": F("Date of Birth", "01/01/2999"), "svc": F("Date of Service", "03/01/2000")}
    assert "dob" in rules(healthcare.check(fields, {}))
    fields = {"dob": F("Date of Birth", "01/01/1990"), "svc": F("Date of Service", "03/01/1985")}
    assert "date_order" in rules(healthcare.check(fields, {}))
    fields = {"dob": F("DOB", "01/01/1941"), "c": F("Collection Date/Time", "02/10/14 14:30")}
    assert not healthcare.check(fields, {})


def _row(**cells):
    return {k: {"label": k, "value": v, "status": "agreed"} for k, v in cells.items()}


def test_a_total_row_must_add_up():
    rows = [_row(code="MD", amount="50.00"), _row(code="MD", amount="400.00"), _row(code="Totals", amount="450.00")]
    assert not healthcare.check({}, {"claim": rows})
    rows[-1] = _row(code="Totals", amount="550.00")
    got = healthcare.check({}, {"claim": rows})
    assert rules(got) == {"totals_mismatch"} and "450.00" in got[0]["detail"]


def test_the_checks_reach_an_untemplated_extraction():
    notes = validation.review_notes({"npi": F("NPI", "1234567890")}, {})
    assert "npi_check_digit" in rules(notes)


def test_a_diagnosis_written_in_words_is_not_checked_as_a_code():
    assert not healthcare.check({"d": F("Final Diagnosis", "Pancreatic mass, one lymph node negative")}, {})
    assert rules(healthcare.check({"d": F("Diagnosis", "9999")}, {})) == {"icd10_format"}
    assert rules(healthcare.check({"d": F("ICD-10", "pancreatic mass")}, {})) == {"icd10_format"}


def test_code_with_a_description_in_brackets_is_judged_by_the_code_alone():
    from app.services.quality import healthcare
    fields = {"procedure_codes": {"label": "Procedure Codes", "value": "99223 (Hospital Inpatient Care)"},
              "diagnosis_codes": {"label": "Diagnosis Codes", "value": "I10 (Essential Hypertension)"}}
    assert healthcare.check(fields, {}) == []
    bad = {"procedure_codes": {"label": "Procedure Codes", "value": "9922 (Hospital Inpatient Care)"}}
    assert [f["rule"] for f in healthcare.check(bad, {})] == ["cpt_format"]


def test_a_disputed_npi_is_settled_by_its_check_digit_without_a_model():
    import asyncio
    from app.services.extraction import adjudicate
    cell = {"label": "Provider NPI", "value": "1234567891", "alternatives": ["1234567893"], "status": "review", "type": "text"}
    assert asyncio.run(adjudicate.settle(b"img", [("npi", cell, "text")], None)) == 1
    assert cell["value"] == "1234567893" and cell["status"] == "agreed" and cell["settled_by"] == "check digit"
    assert cell["alternatives"] == ["1234567891"]


def test_a_format_only_orders_the_readings_and_leaves_the_dispute_for_a_person():
    from app.services.extraction import adjudicate
    cell = {"label": "Diagnosis ICD-10", "value": "110", "alternatives": ["I10"], "status": "review", "type": "text"}
    assert adjudicate.settle_by_rule(cell) and cell["value"] == "I10" and cell["status"] == "review"
    assert "ICD-10" in cell["reason"]


def test_no_reading_fitting_is_said_and_nothing_is_changed():
    from app.services.extraction import adjudicate
    cell = {"label": "NPI", "value": "1234567891", "alternatives": ["1234567892"], "status": "review", "type": "text"}
    assert not adjudicate.settle_by_rule(cell) and cell["value"] == "1234567891" and "NPI" in cell["reason"]


def test_a_label_that_names_nothing_checkable_is_left_alone():
    from app.services.extraction import adjudicate
    cell = {"label": "Patient name", "value": "Jon", "alternatives": ["John"], "status": "review", "type": "text"}
    assert not adjudicate.settle_by_rule(cell) and cell["value"] == "Jon"
