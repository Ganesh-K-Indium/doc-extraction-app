"""
Checks that only make sense for health records: identifiers with a check digit, code formats, birth and service dates, doses,
and claim totals. They run on any extraction, templated or not, and look at what the labels say (an "NPI" field, a "Date of
Birth", a column of "Diagnosis" codes), because a discovered form has no template to say so.
Findings are warnings: a person decides. Each: {rule, severity, detail, field?}.
"""
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from app.services.extraction import normalize as N

_ICD10 = re.compile(r"^[A-TV-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$")
_CPT = re.compile(r"^(\d{5}|[A-V]\d{4})(-[A-Z0-9]{2})?$")
_UNITS = re.compile(r"\b(mg|mcg|µg|ug|g|gm|kg|ml|mL|l|iu|units?|u|meq|mmol|%|tabs?|tablets?|caps?|capsules?|drops?|puffs?|patch(?:es)?|tsp|tbsp|cc)\b", re.I)
MAX_AGE = 120
TOTAL_TOLERANCE = 0.011


def _f(rule: str, detail: str, field: Optional[str] = None) -> Dict[str, Any]:
    out = {"rule": rule, "severity": "warn", "detail": detail}
    if field:
        out["field"] = field
    return out


def npi_valid(value: str) -> bool:
    """An NPI is ten digits whose last is a Luhn check digit computed over "80840" + the first nine."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 10:
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def _label(c: Dict[str, Any], key: str) -> str:
    return f"{c.get('label') or key} {c.get('section') or ''}".lower()


def _amount(v: Any) -> Optional[float]:
    s = str(v or "").strip()
    if not re.fullmatch(r"[($\-]*\d[\d,]*(?:\.\d+)?\)?", s):
        return None
    neg = s.startswith("(") or s.startswith("-")
    n = float(re.sub(r"[^\d.]", "", s))
    return -n if neg else n


def _dates(fields: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    birth: Optional[Tuple[date, str]] = None
    for key, c in fields.items():
        lab = _label(c, key)
        v = c.get("value")
        if isinstance(v, str) and re.search(r"date of birth|\bdob\b|birth ?date|born", lab):
            d = N.parse_date(v)
            if d and birth is None:
                birth = (d, key)
            if d:
                dd = date.fromisoformat(d) if isinstance(d, str) else d
                if dd > date.today():
                    out.append(_f("dob", f"Date of birth {v} is in the future.", key))
                elif (date.today() - dd).days > MAX_AGE * 366:
                    out.append(_f("dob", f"Date of birth {v} would make the patient over {MAX_AGE}.", key))
    if birth:
        b = date.fromisoformat(birth[0]) if isinstance(birth[0], str) else birth[0]
        for key, c in fields.items():
            lab = _label(c, key)
            v = c.get("value")
            if isinstance(v, str) and re.search(r"date of service|service date|admission|admit|discharge|visit date|collection date|received date|date administered", lab):
                d = N.parse_date(v.split()[0] if v.split() else v)
                if d:
                    dd = date.fromisoformat(d) if isinstance(d, str) else d
                    if dd < b:
                        out.append(_f("date_order", f"{c.get('label') or key}: {v} is before the date of birth.", key))
    return out


def _codes(fields: Dict[str, Dict[str, Any]], tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def check(label: str, value: Any, where: str) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        v = value.strip().upper()
        if re.search(r"\bnpi\b", label):
            if not npi_valid(v):
                out.append(_f("npi_check_digit", f"'{value}' is not a valid NPI (ten digits ending in a correct check digit).", where))
        elif re.search(r"icd|diagnos", label):
            tokens = [t for t in re.split(r"[,;\s]+", v) if t]
            if not re.search(r"icd", label) and not all(len(t) <= 8 and re.search(r"\d", t) for t in tokens):
                return                                  # a "Diagnosis" field holding words ("pancreatic mass") is not a code field
            for code in re.split(r"[,;\s]+", v):
                if code and not _ICD10.match(code):
                    out.append(_f("icd10_format", f"'{code}' does not look like an ICD-10 code.", where))
        elif re.search(r"\bcpt\b|hcpcs|procedure code", label):
            for code in re.split(r"[,;\s]+", v):
                if code and not _CPT.match(code):
                    out.append(_f("cpt_format", f"'{code}' does not look like a CPT or HCPCS code.", where))
        elif re.search(r"\bdose\b|dosage|strength", label):
            if re.search(r"\d", v) and not _UNITS.search(v):
                out.append(_f("dose_unit", f"Dose '{value}' has a number but no unit.", where))

    for key, c in fields.items():
        if c.get("type") == "checkbox":
            continue
        check(_label(c, key), c.get("value"), key)
    for tkey, rows in tables.items():
        for i, row in enumerate(rows, 1):
            for ck, c in row.items():
                check((c.get("label") or ck).lower(), c.get("value"), f"{tkey}[{i}].{ck}")
    return out


def _totals(tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """A row called Total(s) must equal the sum of the rows above it, column by column (claim lines, statements)."""
    out: List[Dict[str, Any]] = []
    for tkey, rows in tables.items():
        for idx, row in enumerate(rows):
            cells = list(row.items())
            if not cells:
                continue
            first = " ".join(str(c.get("value") or "") for _, c in cells[:2]).lower()
            if not re.search(r"\btotals?\b", first):
                continue
            above = rows[:idx]
            if len(above) < 2:
                continue
            for ck, c in cells:
                total = _amount(c.get("value"))
                parts = [_amount(r.get(ck, {}).get("value")) for r in above]
                if total is None or any(p is None for p in parts if p is not None) or sum(1 for p in parts if p is not None) < 2:
                    continue
                s = sum(p for p in parts if p is not None)
                if abs(s - total) > TOTAL_TOLERANCE:
                    out.append(_f("totals_mismatch", f"{c.get('label') or ck}: the rows add up to {s:,.2f} but the total says {c.get('value')}.", f"{tkey}[{idx + 1}].{ck}"))
    return out


def check(fields: Dict[str, Dict[str, Any]], tables: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return _dates(fields) + _codes(fields, tables) + _totals(tables)
