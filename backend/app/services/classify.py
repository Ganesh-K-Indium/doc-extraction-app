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
     "all": [r"\bfax\b", r"(legally privileged|confidential)"], "extractor": "skip", "match": "head"},
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


def _span(rule: Dict[str, Any], text: str) -> int:
    """Characters of `text` the rule's patterns actually matched (the title itself)."""
    if "all" in rule:
        return sum(len(m.group(0)) for p in rule["all"] if (m := re.search(p, text, re.I)))
    hits = [m for p in rule.get("any", []) if (m := re.search(p, text, re.I))]
    return max((len(m.group(0)) for m in hits), default=0)


def _title_position(rule: Dict[str, Any], lines: List[str]) -> Optional[int]:
    """Index of the first line where `rule` matches as a TITLE: one to three consecutive lines that are mostly the
    title and little else. Anywhere on the page, so a form below a letter is found; but a sentence that merely
    mentions the form's name ("please return the Prior Authorization Request Form within ten days") is not a title."""
    clean = [l.strip() for l in lines]
    for i in range(len(clean)):
        for size in (1, 2, 3):
            window = " ".join(x for x in clean[i:i + size] if x)
            if not window or not _matches(rule, window):
                continue
            if len(window) <= _span(rule, window) * 2.2 + 15:
                return i
    return None


def classify_text(text: str) -> Dict[str, Any]:
    """{'type', 'label', 'confidence'} for one page's content text (fax stamps already removed).

    A type whose title appears as a title anywhere on the page names the page; with several, the topmost wins (a page
    holding two different forms is classified by the first). Rules marked "match": "head" (a cover sheet has no title)
    look at the top of the page only."""
    text = text or ""
    if len(re.sub(r"\s+", "", text)) < MIN_CONTENT_CHARS:
        return {"type": "blank_or_logo", "label": "Blank or logo-only page", "confidence": 0.9}
    lines = text.splitlines()
    found = []
    for rule in all_types():
        if rule.get("match") == "head":
            if _matches(rule, text[:600]):
                found.append((len(lines), -rule.get("score", 1), rule))  # sorts after any real title
            continue
        pos = _title_position(rule, lines)
        if pos is not None:
            found.append((pos, -rule.get("score", 1), rule))
    if not found:
        return {"type": "unknown", "label": "Unclassified", "confidence": 0.0}
    found.sort(key=lambda f: (f[0], f[1]))
    best = found[0][2]
    return {"type": best["type"], "label": best["label"], "confidence": 0.9 if len(found) == 1 else 0.6}


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


def segment(pages: List[Dict[str, Any]], single_page_types: Optional[set] = None) -> List[Dict[str, Any]]:
    """Group consecutive pages into logical documents.

    A blank/logo page continues the document before it. An unclassified page continues it too (a continuation sheet with
    no title belongs to the form it follows), unless a model said it starts a new one, or the previous document is of a
    single-page type (its template never continues, so an untitled page after it is something else). Two consecutive
    pages of a single-page type are two copies of the form, not one document; of a multi-page type, one document.
    """
    single = (single_page_types or set()) | {"fax_cover"}
    docs: List[Dict[str, Any]] = []
    for p in pages:
        t = p["classification"]["type"]
        prev = docs[-1]["type"] if docs else None
        starts_new = t == "unknown" and (p["classification"].get("continuation") is False or prev in single)
        cont = t in ("blank_or_logo", "unknown") and docs and not starts_new
        if cont:
            docs[-1]["pages"].append(p["page"])
            continue
        if docs and prev == t and t not in single and t not in ("unknown",):
            docs[-1]["pages"].append(p["page"])  # a multi-page exam / note
            continue
        label = p["classification"]["label"]
        docs.append({"doc_index": len(docs), "type": t, "label": label, "pages": [p["page"]]})
    for i, d in enumerate(docs):
        d["doc_index"] = i
    return docs
