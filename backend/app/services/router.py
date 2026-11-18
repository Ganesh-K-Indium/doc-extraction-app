"""
Pipeline router: the decision layer that picks HOW each page and each document is processed, and records why.

Two decisions, both returned with human-readable reasons so a reviewer (or a future eval) can see the trace:

  decide_reader(profile)   -> how to get the page TEXT:
        text_layer             born-digital page, embedded text is exact
        text_layer_unverified  scan with only the scanner's own text layer, and no model available
        ocr_dual               scan / image-only page: two independent vision readers, lines cross-checked
  decide_extractor(doc)    -> how to get the document's DATA:
        template_form          fixed form with a field schema (templates/*.json)
        kv                     generic 'Label: value' pairs (clinical notes, letters, anything unmodelled)
        skip                   cover sheets and blank pages

Rules decide first because they are free, deterministic and explainable. For pages the rules cannot name,
classify.classify_with_model asks a small model to pick among the REGISTERED types only. Supporting a new document
kind is a registry entry (classify.DOC_TYPES) plus, for a fixed form, a template file; nothing here changes.
"""
from typing import Any, Dict, List

from app.services import classify, ocr

EXTRACTORS = {**{d["type"]: d["extractor"] for d in classify.DOC_TYPES}, "blank_or_logo": "skip"}


def profile_page(info: Dict[str, Any]) -> Dict[str, Any]:
    """Cheap signals from analyze_page() that drive the reader decision."""
    return {
        "chars": len(info["text"]),
        "scanned": info["scanned"],
        "widgets": len(info.get("widgets", [])),
        "tables": len(info["tables"]),
    }


def decide_reader(profile: Dict[str, Any], llm_available: bool, tesseract_available: bool = False) -> Dict[str, Any]:
    reasons: List[str] = []
    if profile["scanned"]:
        reasons.append("a picture covers most of the page, so any embedded text is a scanner's OCR layer")
    elif profile["chars"] < ocr.MIN_TEXT_LAYER_CHARS:
        reasons.append(f"only {profile['chars']} characters of embedded text")
    else:
        reasons.append(f"{profile['chars']} characters of embedded text and no page-sized picture")
        return {"reader": "text_layer", "reasons": reasons}
    if llm_available:
        return {"reader": "ocr_dual", "reasons": reasons + ["two vision readers transcribe the page and are compared"]}
    if tesseract_available:
        return {"reader": "ocr_local", "reasons": reasons + ["no model configured, so Tesseract reads the page on this machine (single reader, unverified)"]}
    return {"reader": "text_layer_unverified", "reasons": reasons + ["no model and no Tesseract available, using the embedded text as is"]}


def decide_extractor(doc_type: str) -> Dict[str, Any]:
    kind = EXTRACTORS.get(doc_type, "kv")
    out: Dict[str, Any] = {"extractor": kind, "reasons": [f"document type '{doc_type}' is registered for {kind}"]}
    if doc_type not in EXTRACTORS:
        out["reasons"] = [f"type '{doc_type}' is not registered, using generic label/value reading"]
    return out


READERS = [
    {"id": "text_layer", "label": "Embedded text", "summary": "Digital page: the PDF's own text is exact, no model needed."},
    {"id": "ocr_dual", "label": "Two vision readers", "summary": "Scan or image-only page: two models transcribe it and every line is compared."},
    {"id": "ocr_local", "label": "Tesseract on this machine", "summary": "Scan with no model configured: read locally, nothing leaves the server. Single reader, so unverified."},
    {"id": "text_layer_unverified", "label": "Scanner text, unverified", "summary": "Scan with no model configured: the scanner's own text is used and marked unverified."},
]
