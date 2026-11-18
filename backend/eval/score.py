"""
Score extraction against a hand-made answer key.

    python eval/score.py <pdf> <truth.json> [--template auto|discover|<type>] [--out result.json]

Reports, per field and overall:
  accuracy        share of fields whose value equals the key (after normalisation)
  silent errors   wrong AND not flagged for review: the dangerous kind
  caught errors   wrong but flagged (status review / undetermined): a reviewer will see these
  flag rate       share of correct fields that were flagged anyway (review effort wasted)
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import normalize as N, pipeline  # noqa: E402

FLAGGED = ("review", "undetermined")


def norm(v):
    if isinstance(v, list):
        return sorted(str(x).strip().lower() for x in v)
    if isinstance(v, bool) or v is None:
        return v
    return N.normalize(v, "text")


def same(got, want):
    if want in (None, "", []) and got in (None, "", [], False):
        return True
    return norm(got) == norm(want)


def score_document(form, doc):
    rows = []
    for key, want in doc["fields"].items():
        cell = form["fields"].get(key, {"value": None, "status": "missing"})
        rows.append((key, same(cell.get("value"), want), cell.get("status") in FLAGGED, cell.get("value"), want, cell.get("status")))
    for tkey, trows in doc.get("tables", {}).items():
        got_rows = form["tables"].get(tkey, [])
        for i, trow in enumerate(trows):
            for col, want in trow.items():
                cell = got_rows[i][col] if i < len(got_rows) and col in got_rows[i] else {"value": None, "status": "missing"}
                rows.append((f"{tkey}[{i + 1}].{col}", same(cell.get("value"), want), cell.get("status") in FLAGGED,
                             cell.get("value"), want, cell.get("status")))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"), ap.add_argument("truth"), ap.add_argument("--out")
    ap.add_argument("--template", default="auto", help="auto | discover | a registered type")
    a = ap.parse_args()
    truth = json.loads(Path(a.truth).read_text())
    docs = truth["documents"] if "documents" in truth else [truth]  # one key, or an exported answer key with many
    result = asyncio.run(pipeline.process(a.pdf, template_choice=a.template))
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=1))

    rows, grounded, nonblank = [], 0, 0
    for doc in docs:
        form = next((f for f in result["forms"] if f["doc_type"] == doc["doc_type"] or f.get("label") == doc["doc_type"]), None)
        if not form:
            print(f"! no '{doc['doc_type']}' found; documents: {[d['type'] for d in result['documents']]}")
            rows += [(f"[{doc['doc_type']}] {k}", False, False, None, v, "missing") for k, v in doc["fields"].items()]
            continue
        rows += [(f"{r[0]}",) + r[1:] for r in score_document(form, doc)]
        grounded += sum(1 for c in form["fields"].values() if c.get("bbox"))
        nonblank += sum(1 for c in form["fields"].values() if c.get("value") not in (None, "", [], False))
    n = len(rows)
    right = sum(1 for r in rows if r[1])
    silent = [r for r in rows if not r[1] and not r[2]]
    caught = [r for r in rows if not r[1] and r[2]]
    wasted = [r for r in rows if r[1] and r[2]]
    print(f"\nfields scored: {n}")
    print(f"accuracy:      {right}/{n} = {right / max(n, 1):.1%}")
    print(f"silent errors: {len(silent)}   (wrong and NOT flagged)")
    print(f"caught errors: {len(caught)}   (wrong but flagged for review)")
    print(f"flagged right: {len(wasted)}   (correct but sent to review)")
    print(f"highlighted:   {grounded}/{nonblank} non-blank fields have a page location")
    for title, group in (("SILENT", silent), ("CAUGHT", caught), ("FLAGGED BUT RIGHT", wasted)):
        for key, _, _, got, want, status in group:
            print(f"  {title:18} {key:34} got={got!r} want={want!r} [{status}]")
    sys.exit(1 if silent else 0)


if __name__ == "__main__":
    main()
