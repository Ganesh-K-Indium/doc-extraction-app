"""Shape the stored result into the two downloadable JSON files."""
from typing import Any, Dict


def pages_json(ex) -> Dict[str, Any]:
    r = ex.result or {}
    return {"extraction_id": ex.id, "filename": ex.filename, "page_count": len(r.get("pages", [])),
            "documents": r.get("documents", []), "pages": r.get("pages", [])}


def apply_corrections(form: Dict[str, Any], corrections: Dict[str, Any]) -> Dict[str, Any]:
    fields = {}
    for key, cell in form["fields"].items():
        c = dict(cell)
        ck = f"{form['doc_index']}:{key}"
        if ck in corrections:
            c.update({"original": cell.get("value"), "value": corrections[ck], "status": "corrected"})
        fields[key] = c
    return {**form, "fields": fields}


def _flat(form: Dict[str, Any]) -> Dict[str, Any]:
    values: Dict[str, Any] = {k: c.get("value") for k, c in form["fields"].items()}
    for tkey, rows in form["tables"].items():
        values[tkey] = [{col: cell.get("value") for col, cell in row.items()} for row in rows]
    return values


def fields_json(ex) -> Dict[str, Any]:
    r = ex.result or {}
    forms = []
    for f in r.get("forms", []):
        f = apply_corrections(f, ex.corrections or {})
        forms.append({**f, "values": _flat(f)})
    return {"extraction_id": ex.id, "filename": ex.filename, "forms": forms,
            "other_documents": r.get("other_documents", []), "validation": r.get("validation", []),
            "rest_checked": r.get("rest_checked", []),
            "stats": r.get("stats", {})}


def truth_json(ex) -> Dict[str, Any]:
    """Answer-key shape consumed by eval/score.py: one entry per extracted document, plain values only."""
    out = []
    for f in fields_json(ex)["forms"]:
        out.append({"doc_type": f["doc_type"] if not f.get("discovered") else (f.get("label") or f["doc_type"]),
                    "pages": f["pages"], "discovered": bool(f.get("discovered")),
                    "fields": {k: c.get("value") for k, c in f["fields"].items()},
                    "tables": {t: [{col: cell.get("value") for col, cell in row.items()} for row in rows] for t, rows in f["tables"].items()}})
    return {"note": f"Answer key from {ex.filename}; verify before trusting.", "documents": out}
