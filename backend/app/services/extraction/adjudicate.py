"""
A third, focused reading of the values the two readers could not settle.

Two readers disagree (or one is unsure) about a handful of values on a page, and everything else is fine. Re-reading the
whole page with a third model would pay for the full image again to look at a few words. Instead one call per page,
and only for pages that have a dispute, shows the page and asks about just those values, listing the candidate readings.

Cost: pages where both readers agree on everything never reach this module. A page with disputes costs one more image
read, however many values are in dispute (they share one call), and the reply is a few words each.

Outcome per value:
    the third reading equals one of the candidates   -> that value, status "agreed" (two of three readers)
    the third reading differs from all of them       -> its value shown first, still "review", candidates kept
    the third reader is unsure ([?]) or silent       -> nothing changes

Never run without a model: with an injected reader (tests) or no model configured, disputes stay for a human.
"""
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app import config
from app.services.extraction import normalize as N

logger = logging.getLogger("app.services.adjudicate")

MAX_ITEMS = 25  # one page of handwriting rarely has more doubtful values than this; beyond it a human reads the page

PROMPT = """Two people transcribed this page and disagree about the values listed below. Look at the page and settle each one.

For each item give the text exactly as it is written at that place on the page.
- Choose one of the candidate readings if it is right, or write what you actually see if none is.
- Copy letter by letter and digit by digit. Keep a leading decimal point (.2% is not 2%), percent and currency signs, ranges (7-20), units.
- Do not correct spelling, complete a name, or calculate.
- Letters and digits can look alike in handwriting. Decide from what the entry is: a place or country code is letters (N.Z.), an identifier or a quantity is digits. Do not read a letter as a digit, or the reverse, only because the shapes are similar.
- A mark that is printed on the form (a degree or minute sign, a unit, a currency sign, a frame) is not what was written. If the blank holds only printed marks and nothing was written, answer "[blank]".
- A crossed-out word is not the answer: give what replaced it, or "[?]" if nothing did.
- If you cannot read it with certainty, answer "[?]". Never guess.

Items:
{items}

Return JSON only: {{"items": {{"<id>": "<text as written>"}}}}"""

Cell = Dict[str, Any]
Item = Tuple[str, Cell, str]  # (id, cell, comparison type)


def enabled() -> bool:
    return os.getenv("ADJUDICATE", "1").lower() not in ("0", "false", "no")


def candidates(cell: Cell) -> List[str]:
    out: List[str] = []
    for v in [cell.get("value")] + list(cell.get("alternatives") or []):
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
    return out


def is_disputed(cell: Cell) -> bool:
    """A text value a person would otherwise have to check. Ticks (pixel-read or boolean) are not read as text."""
    v = cell.get("value")
    return (cell.get("status") == "review" and isinstance(v, str) and bool(v.strip())
            and cell.get("type") != "checkbox" and cell.get("method") != "pixel")


def settle_by_rule(cell: Cell) -> bool:
    """Settle a dispute without a model when the label says what the value is and only one reading fits (an NPI whose check digit works,
    a code in the right format). A decisive check (the NPI check digit) settles it; a format only puts the fitting reading first and says so.
    True when the cell changed."""
    from app.services.quality import healthcare
    label = cell.get("label") or ""
    cands = candidates(cell)
    if len(cands) < 2:
        return False
    marks = [healthcare.check_reading(label, c) for c in cands]
    if any(m is None for m in marks):
        return False
    fits = [c for c, m in zip(cands, marks) if m[0]]
    what, decisive = marks[0][1], marks[0][2]
    if len(fits) == 1:
        cell.update({"value": fits[0], "alternatives": [c for c in cands if c != fits[0]], "status": "agreed" if decisive else "review"})
        if decisive:
            cell["settled_by"] = "check digit"
            cell.pop("reason", None)
        else:
            cell["reason"] = f"only this reading is shaped like {what}"
        return True
    if not fits:
        cell["reason"] = f"none of the readings is {what}"
    return False


def _same(a: str, b: str, ftype: str) -> bool:
    if "[?]" in a or "[?]" in b:
        return False  # N.normalize drops the marker, so "2[?]5" would otherwise equal "25"
    return N.normalize(a, ftype) == N.normalize(b, ftype)


def apply(cell: Cell, answer: Any, ftype: str = "text", shared: Optional[int] = None) -> bool:
    """Fold the third reading into the cell. True when the cell changed.

    `shared` is the position (0 = the value, 1 = the alternative) of the candidate that came from the same model as this third reading,
    or None. A third look that only repeats its own model's earlier answer is not a second opinion, so it settles nothing."""
    ans = str(answer).strip() if answer is not None else ""
    if ans.lower() == "[blank]":                  # nothing was written: the readers took a printed mark for a value
        cands = candidates(cell)
        cell.update({"value": None, "alternatives": cands, "status": "review", "reason": "a third look found nothing written here, only printed marks"})
        if "normalized" in cell:
            cell["normalized"] = None
        return True
    if not ans or "[?]" in ans:
        return False
    cands = candidates(cell)
    match = next((c for c in cands if _same(c, ans, ftype)), None)
    if match is not None:
        if shared is not None and cands.index(match) == shared:
            cell["reason"] = "a third look by the same model repeated its own answer, which is not a second opinion"
            return False
        cell.update({"value": match, "alternatives": [c for c in cands if not _same(c, match, ftype)], "status": "agreed",
                     "settled_by": "third reading"})
        cell.pop("reason", None)
    else:
        cell.update({"value": ans, "alternatives": cands, "status": "review", "reason": "a third reading differs from both"})
    if "normalized" in cell:
        cell["normalized"] = N.normalize(cell["value"], ftype)
    return True


def parse(raw: Any) -> Dict[str, str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()))
        except ValueError:
            return {}
    items = raw.get("items") if isinstance(raw, dict) else None
    return {str(k): str(v) for k, v in items.items() if v is not None} if isinstance(items, dict) else {}


def _describe(n: int, cell: Cell) -> str:
    cands = candidates(cell)
    label = cell.get("label") or "(no label)"
    where = f' under "{cell["section"]}"' if cell.get("section") else ""
    return f'{n}. "{label}"{where}: ' + " | ".join(json.dumps(c, ensure_ascii=False) for c in cands)


async def read(model: str, jpeg: bytes, prompt: str) -> Dict[str, str]:
    from app.engines.providers import llm
    return parse(await llm.complete(model, prompt, jpeg, stage="adjudicate"))


async def settle(jpeg: bytes, items: List[Item], reader: Optional[Callable] = None, readers: Sequence[str] = ()) -> int:
    """Settle the disputed cells among `items` with one call. Returns how many were changed.

    `reader` is None in production (the real model is used, if one is configured); tests pass their own. `readers` are the models that made
    the two readings, in order: when the third look is by one of them, siding with that model's own earlier answer does not settle a dispute."""
    disputed = [(i, c, t) for i, c, t in items if is_disputed(c)][:MAX_ITEMS]
    by_rule = sum(1 for _, c, _t in disputed if settle_by_rule(c))            # free: a check digit or a code format settles some disputes
    disputed = [(i, c, t) for i, c, t in disputed if is_disputed(c)]           # a value the rule settled as agreed is not sent to a model
    if not disputed or not enabled():
        return by_rule
    model = config.adjudicator_model()
    if reader is None:
        if not model:
            return 0
        reader = read
    model = model or "adjudicator"
    shared = next((k for k, m in enumerate(list(readers)[:2]) if m == model), None)
    prompt = PROMPT.format(items="\n".join(_describe(n, c) for n, (_, c, _) in enumerate(disputed, 1)))
    try:
        answers = await reader(model, jpeg, prompt)
    except Exception as e:  # a failed third look must never lose the extraction: the disputes just stay for a human
        logger.warning("Adjudication failed: %s", e)
        return by_rule
    if not isinstance(answers, dict):
        return by_rule
    return by_rule + sum(apply(c, answers.get(str(n)), t, shared) for n, (_, c, t) in enumerate(disputed, 1))
