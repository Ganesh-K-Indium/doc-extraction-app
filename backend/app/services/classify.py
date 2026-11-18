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


def custom_types() -> List[Dict[str, Any]]:
    """The custom document types of the workspace in force (see workspace_types)."""
    from app.services import workspace_types
    return [d for d in workspace_types.entries() if isinstance(d, dict) and d.get("type")]


def all_types() -> List[Dict[str, Any]]:
    built_in = {d["type"] for d in DOC_TYPES}
    return DOC_TYPES + [dict(d, custom=True) for d in custom_types() if d["type"] not in built_in]


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
    hits = [r for r in all_types() if _matches(r, head)]
    if not hits:
        return {"type": "unknown", "label": "Unclassified", "confidence": 0.0}
    best = max(hits, key=lambda r: r["score"])
    return {"type": best["type"], "label": best["label"], "confidence": 0.9 if len(hits) == 1 else 0.6}


async def classify_with_model(text: str, models: List[str], ask=None, previous_text: str = "") -> Dict[str, Any]:
    """Second opinion for a page the rules could not name. The model may only choose a REGISTERED type (or 'unknown'),
    so its answer is always routable, and it says whether the page continues the previous page's document or starts a
    new one (with a short title). `ask(model, prompt) -> str` is injectable for tests."""
    import json
    from app.services import ocr
    choices = {d["type"]: d["label"] for d in all_types()}
    prompt = ("Classify one page from a PDF that may hold several documents. Answer with JSON "
              '{"type": <one of ' + ", ".join(f'"{t}" ({l})' for t, l in choices.items())
              + ' or "unknown">, "title": "<short title of this page\'s document, or null>", '
              '"continues_previous": <true if this page is a continuation of the previous page\'s document, else false>}.\n\n'
              + (f"Previous page (top):\n{previous_text[:400]}\n\n" if previous_text else "")
              + "This page (top):\n" + (text or "")[:1200])

    async def default_ask(model: str, prompt: str) -> str:
        resp = await ocr._get_client().chat.completions.create(
            model=model, temperature=0, response_format={"type": "json_object"}, messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content

    ask = ask or default_ask
    unknown = {"type": "unknown", "label": "Unclassified", "confidence": 0.0}
    try:
        data = json.loads(await ask(models[-1], prompt))  # the smaller model: this is a cheap, short call
    except Exception:
        return unknown
    if not isinstance(data, dict):
        return unknown
    t = data.get("type")
    title = data.get("title") if isinstance(data.get("title"), str) and data["title"].strip() else None
    if t in choices:
        return {"type": t, "label": choices[t], "confidence": 0.7, "by": "model"}
    return {**unknown, "label": title or "Unclassified", "title": title, "by": "model",
            "continuation": bool(data.get("continues_previous"))}


def segment(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group consecutive pages into logical documents.

    A blank/logo page and an unclassified page continue the document before them (a continuation sheet with no title
    belongs to the form it follows); with no document yet they start an 'unknown' one.
    """
    docs: List[Dict[str, Any]] = []
    for p in pages:
        t = p["classification"]["type"]
        # An unknown page continues the document before it, unless a model said it starts a new one.
        starts_new = t == "unknown" and p["classification"].get("continuation") is False
        cont = t in ("blank_or_logo", "unknown") and docs and not starts_new
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
