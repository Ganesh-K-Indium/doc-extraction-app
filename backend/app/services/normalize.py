"""Value normalisation by field type. Comparison and validation work on the normalised form; the raw text is kept."""
import re
from datetime import datetime
from typing import Any, Optional

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def parse_date(s: str) -> Optional[str]:
    s = re.sub(r"\s+", " ", (s or "").strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# Marks that change what a number means. Stripping them made ".2%" equal "2%" and "7-20" equal "720",
# so two readers that disagreed on a decimal point or a range counted as agreeing. Kept only where they touch a digit:
#   .5 and 9.5 (decimal point)   7-20 and 10/12 (range, date)   20% (percent)   $215 (currency)
# A sentence-ending "1992." or a bullet "- 1 min" is not one of these, so it still does not count as a difference.
_MARKS = {"-": "\ue000", "/": "\ue001", ".": "\ue002", "%": "\ue003", "$": "\ue004"}
_MARKS_BACK = {v: k for k, v in _MARKS.items()}
_MARK_RE = re.compile(r"(?<=\d)[-/](?=\d)|\.(?=\d)|(?<=\d)%|\$(?=\d)")


def text_form(s: str) -> str:
    """Comparison form of free text: lower case, letters and digits, plus the digit-bearing marks above."""
    s = _MARK_RE.sub(lambda m: _MARKS[m.group()], re.sub(r"\s+", "", s.lower()))
    s = re.sub(r"[^a-z0-9\ue000-\ue004]", "", s)
    return re.sub(r"[\ue000-\ue004]", lambda m: _MARKS_BACK[m.group()], s)


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def normalize(value: Any, ftype: str) -> Optional[str]:
    """Canonical string for comparison; None when there is no value."""
    if value is None:
        return None
    if isinstance(value, list):
        return "|".join(sorted(str(v).strip().lower() for v in value)) or None
    s = str(value).strip()
    if not s:
        return None
    if ftype == "date":
        return parse_date(s) or re.sub(r"[^a-z0-9]", "", s.lower())
    if ftype in ("phone", "npi", "tax_id", "zip"):
        return digits(s) or None
    if ftype in ("state", "icd10"):
        return re.sub(r"[^A-Z0-9]", "", s.upper()) or None
    return text_form(s) or None
