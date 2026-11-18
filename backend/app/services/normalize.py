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
    return re.sub(r"[^a-z0-9]", "", s.lower()) or None
