"""
Page classification and document segmentation.

Rule-based on purpose: the document types are few and have stable titles, a rule is explainable to reviewers, and it
costs nothing. Rules are data (DOC_TYPES) so a new form is one more entry, not new code.
"""
import re
from typing import Any, Dict, List, Optional

# type -> (all-of regexes, score). First type with a hit wins; ties go to the higher score.
DOC_TYPES: List[Dict[str, Any]] = [
    {"type": "prior_auth_form", "label": "Prior authorization request form", "score": 3,
     "any": [r"prior\s+authorization\s+request\s+form"], "template": "magnacare_prior_auth", "extractor": "template_form"},
    {"type": "pt_initial_exam", "label": "Physical therapy initial examination", "score": 3,
     "all": [r"physical\s+therapy", r"initial\s+exam"], "template": "pt_initial_exam", "extractor": "template_form"},
    {"type": "daily_note", "label": "Daily note / billing sheet", "score": 3,
     "any": [r"daily\s+note\s*/?\s*billing\s+sheet", r"daily\s+note"], "template": "daily_note", "extractor": "template_form"},
    {"type": "fax_cover", "label": "Fax cover sheet", "score": 2,
     "all": [r"\bfax\b", r"(legally privileged|confidential)"], "extractor": "skip"},
]
MIN_CONTENT_CHARS = 40


def _matches(rule: Dict[str, Any], text: str) -> bool:
    if "all" in rule and not all(re.search(p, text, re.I) for p in rule["all"]):
        return False
    if "any" in rule and not any(re.search(p, text, re.I) for p in rule["any"]):
        return False
    return True


def classify_text(text: str) -> Dict[str, Any]:
    """{'type', 'label', 'confidence'} for one page's content text (fax stamps already removed)."""
    text = text or ""
    if len(re.sub(r"\s+", "", text)) < MIN_CONTENT_CHARS:
        return {"type": "blank_or_logo", "label": "Blank or logo-only page", "confidence": 0.9}
    # Only the top of the page names its form; a mention further down must not reclassify a continuation page.
    head = text[:600]
    hits = [r for r in DOC_TYPES if _matches(r, head)]
    if not hits:
        return {"type": "unknown", "label": "Unclassified", "confidence": 0.0}
    best = max(hits, key=lambda r: r["score"])
    return {"type": best["type"], "label": best["label"], "confidence": 0.9 if len(hits) == 1 else 0.6}


async def classify_with_model(text: str, models: List[str], ask=None) -> Dict[str, Any]:
    """Second opinion for a page the rules could not name. The model may only choose a REGISTERED type (or 'unknown'),
    so its answer is always routable. `ask(model, prompt) -> str` is injectable for tests."""
    import json
    from app.services import ocr
    choices = {d["type"]: d["label"] for d in DOC_TYPES}
    prompt = ("Classify this page from a fax packet. Answer with JSON {\"type\": <one of "
              + ", ".join(f'"{t}" ({l})' for t, l in choices.items())
              + ' or "unknown">}.\n\nPage text (top):\n' + (text or "")[:1200])

    async def default_ask(model: str, prompt: str) -> str:
        resp = await ocr._get_client().chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"}, messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content

    ask = ask or default_ask
    try:
        raw = await ask(models[-1], prompt)  # the smaller model: this is a cheap, short call
        t = json.loads(raw).get("type")
    except Exception:
        return {"type": "unknown", "label": "Unclassified", "confidence": 0.0}
    if t in choices:
        return {"type": t, "label": choices[t], "confidence": 0.7, "by": "model"}
    return {"type": "unknown", "label": "Unclassified", "confidence": 0.0}


def segment(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group consecutive pages into logical documents.

    A blank/logo page and an unclassified page continue the document before them (a continuation sheet with no title
    belongs to the form it follows); with no document yet they start an 'unknown' one.
    """
    docs: List[Dict[str, Any]] = []
    for p in pages:
        t = p["classification"]["type"]
        cont = t in ("blank_or_logo", "unknown") and docs
        if cont:
            docs[-1]["pages"].append(p["page"])
            continue
        if docs and docs[-1]["type"] == t and t not in ("prior_auth_form", "fax_cover"):
            docs[-1]["pages"].append(p["page"])  # multi-page exam / note
            continue
        docs.append({"doc_index": len(docs), "type": t, "label": p["classification"]["label"], "pages": [p["page"]]})
    for i, d in enumerate(docs):
        d["doc_index"] = i
    return docs
