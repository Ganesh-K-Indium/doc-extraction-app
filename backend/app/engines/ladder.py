"""
The escalation ladder for one scanned page: read it with the cheapest engine that can be trusted.

    1. the local OCR engine reads the page (free)
    2. its confidence and the look of the text are checked (local.assess)
    3. good enough -> keep it.  Doubtful -> two vision models read the page and are compared (the paid step)

Modes (see plan.py): "local" stops after step 2 and only flags what is doubtful; "escalate" does the whole ladder;
"vision" skips straight to step 3. A per-document token cap stops step 3 once the budget is spent: the page then keeps its
local reading, flagged for a person, rather than silently costing more.

A vision service that is down never fails a page that a local engine could read: the local reading is kept and the page
says why it was not escalated.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.engines import local
from app.services.reading import ocr
from app.services.usage_tracker import get_current_tracker

logger = logging.getLogger("app.engines.ladder")


@dataclass
class Scan:
    lines: List[ocr.OcrLine]
    source: str                      # "ocr" (vision models) | "ocr-local"
    verified: bool                   # two readers compared
    handwritten: bool
    reading: Dict[str, Any] = field(default_factory=dict)


def tokens_used() -> int:
    t = get_current_tracker()
    return sum(e.total_tokens for e in t.entries) if t else 0


def over_budget(cap: int) -> bool:
    return cap > 0 and tokens_used() >= cap


def _local_lines(r: local.Reading) -> List[ocr.OcrLine]:
    out = []
    for text, conf in zip(r.lines, r.line_conf):
        bad = conf is not None and conf < local.LOW_WORD
        out.append(ocr.OcrLine(text=text, status="review" if bad else "agreed", alternatives=[],
                               reason="the OCR engine was unsure of this line" if bad else None))
    return out


async def _reference(jpeg: bytes, tsv: Optional[str]) -> Optional[local.Reading]:
    """Tesseract's reading of the page, used to cross-check an engine whose confidence cannot be trusted. Free when the
    work-PDF pass already ran it."""
    tess_eng = local.get("tesseract")
    if tess_eng is None or not tess_eng.available():
        return None
    try:
        return local.build_reading(local.words_from_tsv(tsv), "tesseract") if tsv is not None else await tess_eng.read(jpeg)
    except Exception as e:
        logger.warning("Reference OCR failed: %s", e)
        return None


async def read_scanned(*, mode: str, engine_id: Optional[str], jpeg: bytes, models: List[str], reader=None, threshold: float = 0.85,
                       token_cap: int = 0, force_vision: bool = False, tsv: Optional[str] = None) -> Scan:
    """Read one scanned page. `mode` is the effective mode ("local", "escalate" or "vision")."""
    eng = local.get(engine_id)
    reading: Optional[local.Reading] = None
    local_error = ""
    if mode != "vision" and not force_vision and eng is not None:
        try:
            if eng.id == "tesseract" and tsv is not None:       # the work-PDF pass already ran Tesseract on this page
                reading = local.build_reading(local.words_from_tsv(tsv), eng.id)
            else:
                reading = await eng.read(jpeg)
        except Exception as e:
            logger.warning("Local OCR (%s) failed: %s", eng.id, e)
            local_error = f"{eng.label} could not read the page"

    info: Dict[str, Any] = {"engine": eng.id if reading else None, "confidence": reading.confidence if reading else None,
                            "escalated": False, "reasons": []}
    if reading is not None:
        if eng.calibrated:
            verdict = local.assess(reading, threshold, jpeg)
        else:                              # this engine's own confidence is not trustworthy: Tesseract has to agree with it
            reference = await _reference(jpeg, tsv)
            if reference is not None:
                reading = local.cross_check(reading, reference)
                verdict = local.assess_cross(reading, jpeg)
                info["agreement"] = reading.agreement
            else:
                verdict = local.assess(reading, max(threshold, 0.9), jpeg)      # its own number is all there is: be strict
                if not verdict.ok:
                    verdict.reasons.append("no second OCR engine is installed to cross-check it")
        info["confidence"] = reading.confidence
        info["reasons"] = list(verdict.reasons)
        if verdict.ok or mode == "local":
            return Scan(_local_lines(reading), "ocr-local", False, False, info)
        if over_budget(token_cap):
            info["cost_capped"] = True
            info["reasons"].append("the token cap for this document was reached, so a vision model was not used")
            return Scan(_local_lines(reading), "ocr-local", False, False, info)
    elif local_error:
        info["reasons"].append(local_error)
    elif force_vision:
        info["reasons"].append("you asked for this page to be re-read with the vision models")

    try:
        page = await ocr.read_page(jpeg, models, reader)
    except ocr.OcrError as e:
        if reading is not None:                                   # keep what the local engine got rather than fail the page
            info["reasons"].append("the vision models were unavailable, so the local reading was kept")
            return Scan(_local_lines(reading), "ocr-local", False, False, info)
        raise e
    info.update({"escalated": reading is not None or bool(local_error) or force_vision, "engine": "vision", "models": models[:2]})
    if reading is not None:
        info["local_confidence"] = reading.confidence
    return Scan(page.lines, "ocr", page.cross_checked, page.handwritten, info)
