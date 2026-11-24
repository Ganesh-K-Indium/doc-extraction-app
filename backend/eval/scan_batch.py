"""Run scan_eval over a fixed set of healthcare documents and print one line per document and profile.

    LLM_ENABLED=0 READING_STRATEGY=economy python eval/scan_batch.py [--profiles clean,scan,fax] [--only cbc,eob] [--json out.json]
"""
import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import scan_eval  # noqa: E402

H = Path(__file__).resolve().parent.parent.parent / "sample_data" / "healthcare"
SET = {
    "cbc": ("clinical/lab_cbc_sample_report_testing_com.pdf", [1]),
    "eob_md": ("payer/eob_maryland_health_dept.pdf", [1]),
    "eob_cms": ("payer/eob_cms_sample.pdf", [1]),
    "ub04": ("claims/ub04_carepatron_example.pdf", [1]),
    "discharge": ("clinical/discharge_summary_example_carepatron.pdf", [1]),
    "pathology": ("clinical/pathology_report_roswell_park.pdf", [1]),
    "immun_card": ("forms/immunization_card_washington.pdf", [2]),
    "stony_p1": ("forms/patient_intake_stony_brook.pdf", [1]),
}


async def one(name, profile):
    pdf, pages = SET[name]
    work = tempfile.mkdtemp()
    truth, got, res = await scan_eval.run(str(H / pdf), pages, profile, work, {})
    r = scan_eval.compare(truth, got)
    for f in Path(work).glob("*.work.pdf"):
        f.unlink()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="clean,scan,fax")
    ap.add_argument("--only", default="")
    ap.add_argument("--json")
    a = ap.parse_args()
    names = [n for n in SET if not a.only or n in a.only.split(",")]
    out = {}
    print(f"{'doc':11}{'profile':8}{'fields':>10}{'(other)':>8}{'silent':>7}{'extra':>6}{'cells':>11}{'rows':>9}{'tables k/g':>11}{'highlight':>11}")
    for n in names:
        for p in a.profiles.split(","):
            try:
                r = asyncio.run(one(n, p))
            except Exception as e:  # noqa: BLE001
                print(f"{n:11}{p:8} ERROR {str(e)[:80]}")
                continue
            out[f"{n}:{p}"] = r
            print(f"{n:11}{p:8}{str(r['field_same_label']) + '/' + str(r['fields']):>10}{r['field_other_label']:>8}{r['field_silent_wrong']:>7}{r['extra_fields']:>6}"
                  f"{str(r['cell_found']) + '/' + str(r['cell_total']):>11}{str(r['rows_exact']) + '/' + str(r['rows_total']):>9}"
                  f"{str(r['tables_key']) + '/' + str(r['tables_got']):>11}{r['highlightable']:>11}", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
