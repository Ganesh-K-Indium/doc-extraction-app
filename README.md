# Document extraction

Turns a PDF (fax packet, scanned or digital form) into:

- **pages.json**: one entry per page (text, source, fax stamp metadata, classification, bounding-box blocks, tables, the routing decision), plus the logical documents the pages group into.
- **fields.json**: key–value output for each form that has a template (value, status, page, bounding box, alternative reading) plus a flat `values` object, the CPT table, and validation findings (required fields, formats, cross-document checks).

A review UI shows the source PDF next to the fields. Values both readers agree on are quiet; anything else goes in a review queue (`j`/`k` to move, `Enter` to confirm, or click the second reader's value).

## Run

```bash
# backend (venv lives at the project root, outside backend/)
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && cp .env.example .env   # add OPENAI_API_KEY; without it only text-layer pages and checkboxes are read
uvicorn app.main:app --reload
pytest -q                            # offline, no network

# frontend
cd frontend && npm install && cp .env.example .env && npm run dev
```

## How a page is processed

`router.py` is the decision layer. For every page it profiles the PDF (embedded text, page-sized picture, form widgets) and chooses a reader, then for every document it chooses an extractor. Each choice is stored with its reasons (`route` in pages.json) and shown in the UI.

| Decision | Options |
|---|---|
| Reader | `text_layer` (digital page) · `ocr_dual` (scan: two vision models, lines compared) · `text_layer_unverified` (scan, no model configured) |
| Extractor | `template_form` (field schema in `app/templates`) · `kv` (generic Label: value) · `skip` (cover, blank) |
| Page type | keyword rules first; a small model may break ties but can only choose **registered** types |

Checkbox groups are never read by a model: glyph in the text, then ink inside the box.

## Add another document kind

1. Add an entry to `DOC_TYPES` in `app/services/classify.py` (title patterns, `extractor`).
2. For a fixed form, add `app/templates/<name>.json` (sections, fields, types, required) and set `"template"` on the entry.
3. Add a test with a synthetic page. No pipeline code changes.

## Known limits

- Bounding boxes need an embedded text layer. Pure-image scans have values but no highlight.
- The form extractor reads one page per form; multi-page forms need a template with page anchors.
- Checkbox pixel thresholds and the field grounding were tested on synthetic pages only. Calibrate on real samples.
- Patient data: this app stores uploads and results on local disk and sends page images to the configured model provider. Use a provider agreement that covers PHI before real patient documents go through it.
