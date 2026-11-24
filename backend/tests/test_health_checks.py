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
