# Document extraction

Turns any PDF (scanned or digital forms, fax packets, statements, applications) into:

- **pages.json**: one entry per page (text, source, fax stamp metadata, classification, bounding-box blocks, tables, the routing decision), plus the logical documents the pages group into.
- **fields.json**: key–value output for each document that has a template (value, status, page, bounding box, alternative reading) plus a flat `values` object, the CPT table, and validation findings (required fields, formats, cross-document checks).

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

## Workspaces

Everything lives inside a workspace: its documents, results, answer keys and **its own custom document types** (built-in types are shared). The app opens on the workspaces screen; you create one (or continue in the one you last used), then upload and review inside it. A switcher in the workspace bar moves between them.

- Workspace names are unique (ignoring case); rename and delete are on the workspaces screen. Deleting removes the workspace's documents, uploaded files and types, and asks first.
- API: everything is under `/api/workspaces/{id}/...` (`extractions`, `registry`, `templates`); `/api/workspaces` lists, creates, renames and deletes them. A document is never reachable through another workspace's URL.
- Uploading the same file twice reuses the result only inside the same workspace.
- Upgrading from a version without workspaces: existing documents and custom types are moved into a workspace called "My workspace" the first time the server starts. A fresh install starts empty.
- There are no user accounts yet: workspaces separate work, they do not restrict who can open them. Anyone who can reach the server (and has the API key, if one is set) sees every workspace.

## How a file is processed

1. **Work PDF.** Scanned pages get a Tesseract text layer (`tess.py`), laid over the original so page size and coordinates are unchanged. Every geometric step (highlighting, label search, checkbox pixels, table rebuild) runs on it; the viewer shows the original.
2. **Read.** `router.py` profiles each page and picks a reader, stored with its reasons (`route` in pages.json): embedded text, two vision models compared (`ocr_dual`), or Tesseract alone (`ocr_local`, nothing leaves the machine). Lines are compared by content, not line breaks, so layout differences are not disagreements but a different digit is.
3. **Sort.** Fax stamps are split off as metadata; pages are classified (keyword rules first, a small model only for unknown pages and only among registered types) and grouped into documents.
4. **Extract.** Each document with a template is read page by page by two models against the template's fields, and the best-supported reading per field wins. Checkboxes are read from the pixels (a hollow square beside the label, then the ink inside it), never from a model unless the box can't be located. Tables use the layout extractor ported from the SEC pipeline (`table_extractor.py`), with PyMuPDF's grid finder as fallback.
5. **Ground and cross-check.** Each value is located on the page. Tesseract is an independent third reader: if both models agree but Tesseract reads something similar and different at that spot, the field goes to review. When the models disagree, the reading that also appears in the page's own text is shown first.
6. **Validate.** Per-document rules from the template (required fields, formats, date order), then cross-document consistency from each template's `canonical` section.

| Decision | Options |
|---|---|
| Reader | `text_layer` · `ocr_dual` · `ocr_local` · `text_layer_unverified` |
| Extractor | `template_form` (field schema in `app/templates`) · `kv` (generic Label: value) · `skip` |

Uploading the same file twice reuses the first result (SHA-256), so you don't pay for the same OCR again.

## Forms inside other content

Real files mix things: a cover letter, a form, free-text notes, another form. How each case is handled:

| Layout | Result |
|---|---|
| A form on its own pages among other pages | The form's pages use its template; other pages are discovered (or use their own template). |
| A form lower down on a page that also has a letter or notes | Found anywhere on the page: a type matches when its title appears **as a title** (one to three lines of its own), not only at the top. The form's fields are extracted; the rest of the page needs the step below. |
| A page that only *mentions* a form's name in a sentence | Not a form: a sentence is not a title. |
| An untitled page after a one-page form | A new document, not the form's continuation. (Multi-page types, such as an exam, do absorb untitled continuation pages.) |
| Two copies of the same one-page form back to back | Two documents. |

**Read the rest.** A template extracts only its own fields, so text and structure around the form stay as plain text in `pages.json` unless you ask for more. Tick *Also read the rest of each page* at upload, or press *Read the rest of these pages* on a document afterwards. The pages are read with discovery and everything the template already covers is removed (same label, same place on the page, same long value, empty blanks). What is left appears as a separate **Other content** entry next to the form, never mixed into its fields. It is optional because it uses extra model calls. Printed boilerplate of the form itself (a header's phone numbers, a legend table) can appear there too; there is no rule that tells boilerplate from data without a blank copy of the form.

Limit: a single page holding **two different** forms is classified by the first title, so the second form's fields are not extracted against its template (the rest step will surface them as discovered fields).

## Templates are optional

At upload the user picks how the file is read:

| Choice | What happens |
|---|---|
| **Detect automatically** (default) | Pages are classified; known types use their template, everything else is **discovered**. |
| **A template** (built-in, drafted, or saved from an earlier extraction) | Every page is read with that template. Use it for a single form; for a packet of several documents use automatic detection. |
| **Read without a template** | The whole file is read as one document by discovery. |

**Discovery** (`discover.py`) needs no setup. Two vision models each list every labelled field, checkbox and table on a page; the lists are matched by label (tolerant of different section headings) and merged with the same trust model as templates. A grid that one reader returns as a table and the other as flat fields (`Flexion Right: 170°`) is reconciled, not flagged. Checkboxes are judged from pixels; every value is located on the page and checked against Tesseract. The output has the same shape as a templated extraction, so review, corrections and export are identical. Without a template there are no required fields or formats to enforce, so the findings are only the places the readers were unsure.

Three ways to get a type, none of which involves writing JSON:

1. **Upload a blank form** (Document types > Add a type from a blank form). The fields, types, choice groups, tables and required marks are drafted from it; you correct the draft (required marks especially) and save.
2. **Promote an extraction.** After reviewing a discovered document, "Save as document type" turns it into a type; the next file of that kind is recognised, validated and cross-checked.
3. **Hand-write a template** (below) for rules and cross-document checks the drafts cannot infer.

A type you add beats a built-in type with the same title in that workspace (someone who uploads their own template means to use it). Saving rejects built-in names, duplicate keys, unknown types, and user-supplied regex patterns (a ReDoS risk), which only hand-written, built-in templates may use.

A drafted template has **no links to other documents** yet (the `canonical` section below): the draft cannot know that a field is the same person's date of birth as in another document. Without links, cross-document checks (for example, a date of birth that differs between a form and a clinical note) are skipped for that type. Add them by hand until the screen can set them. The links are validated on save (kinds and field names are checked; regex patterns are refused).

Checkboxes on scans are judged from the pixels, never from the `☑`/`☐` characters in a model's transcript: those are the model's own guess. Only born-digital pages use text glyphs.

## Hand-written templates

1. Add an entry to `DOC_TYPES` in `app/services/classify.py`: title patterns, `"extractor": "template_form"`, `"template": "<name>"`.
2. Add `app/templates/<name>.json`: sections and fields (`type`, `required`, optional `pattern`), optional `tables`, optional `rules` (for example `date_order`), and a `canonical` section naming what other documents may also carry:

```json
"canonical": {
  "id.date": {"kind": "date", "label": "Issue date", "fields": ["issued"]},
  "line_codes": {"kind": "set", "label": "Item codes", "table": "items", "column": "sku", "pattern": "[A-Z]{3}\\d{4}"}
}
```

   Kinds: `name`, `date`, `text`, `set`, `mentioned`. Nothing in the pipeline knows what a patient, invoice or contract is.
3. Add a test with a synthetic page. No pipeline code changes.

## Measure accuracy

```bash
cd backend && python eval/score.py ../sample_data/<file>.pdf eval/magnacare_p3.truth.json
```

Reports accuracy, **silent errors** (wrong and not flagged: the number to drive to zero), caught errors, and how many correct fields were sent to review anyway. Keep truth as printed on the page, typos included.

To get an answer key without typing one: review an extraction in the UI (fix what is wrong), then **Download answer key**. That file works with `score.py` directly, including packets with several documents. Re-run the same PDF after changing the code to see whether accuracy moved.

On the sample prior-authorization form (50 values): 98% exact, 0 silent errors, the one wrong value flagged for review, 31 of 35 filled fields highlighted on the page.

## Setup notes

- Tesseract: `brew install tesseract` (macOS) or your package manager. Optional `TESSERACT_CMD`, `TESSERACT_LANG`. Without it scans have no highlighting.
- Without `OPENAI_API_KEY` the app still runs: digital pages use embedded text and scans use Tesseract (single reader, marked unverified).

## Known limits

- Rotated or skewed scans are not corrected before OCR.
- Pure handwriting is only as good as the vision models; Tesseract adds little there.
- Discovery reads one document per file when you force it (`Read without a template`); use automatic detection to split a packet. Labels that repeat within one section are suffixed `_2`, `_3` in order.
- A drafted template is a starting point: on the sample blank form it found 42 of the 43 fields I wrote by hand, with correct types, but it over-marked some fields as required and missed one choice group. Always check the required marks.
- When the two readers return a table in different shapes (one combined, one split in two), its cells are flagged rather than reconciled.
- Figures and charts are not analysed. The SEC pipeline's figure-description step (`image_data_prep.py`) is the model to port when a document type needs it.
- Checkbox labels Tesseract fails to read are settled by the model reading and flagged when they disagree.
- Uploads and results are stored on local disk and page images go to the configured model provider. Use a provider agreement that fits the sensitivity of the documents before processing real ones.
