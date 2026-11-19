# Document extraction

Turns any PDF (scanned or digital forms, fax packets, statements, applications) into:

- **pages.json**: one entry per page (text, source, fax stamp metadata, classification, bounding-box blocks, tables, the routing decision), plus the logical documents the pages group into.
- **fields.json**: key–value output for each document that has a template (value, status, page, bounding box, alternative reading) plus a flat `values` object, the CPT table, and validation findings (required fields, formats, cross-document checks).

A review UI shows the source PDF next to the fields. Values both readers agree on are quiet; anything else goes in a review queue (`j`/`k` to move, `Enter` to confirm, or click the second reader's value).

## Install and run

Needs Python 3.11 or newer (tested on 3.13), Node 18 or newer, and Tesseract. Digital PDFs work with nothing else; scans, photos and handwriting use the OCR engines and models below.

**1. Tesseract** (the built-in local OCR engine; it also gives scanned pages the text layer used for highlighting)

```bash
brew install tesseract                      # macOS
sudo apt install tesseract-ocr              # Debian / Ubuntu
# Windows: install from https://github.com/UB-Mannheim/tesseract/wiki and set TESSERACT_CMD to tesseract.exe
tesseract --version                         # check it is on the PATH
```

Other languages: install the language pack (`sudo apt install tesseract-ocr-deu`) and set `TESSERACT_LANG=eng+deu`.

**2. Backend**

```bash
# the venv lives at the project root, outside backend/
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && cp .env.example .env          # optional: models can also be connected on the Settings page
uvicorn app.main:app --reload
```

**3. Frontend**

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

**4. Optional: more local OCR engines.** Tesseract is enough to start. Each of these appears on the *Reading engines* page once installed, and you can install any subset (or all with `pip install -r backend/requirements-ocr.txt`):

| Engine | Install | Size | First use |
|---|---|---|---|
| RapidOCR | `pip install rapidocr-onnxruntime` | about 100 MB | none: its models ship inside the package |
| PaddleOCR | `pip install paddlepaddle paddleocr` | about 430 MB | downloads about 130 MB of models |
| docTR | `pip install "python-doctr[torch]"` | about 630 MB (PyTorch) | downloads about 125 MB of models |

`pip` installs the code only. PaddleOCR and docTR fetch their models the first time they run, so "requirement already satisfied" says nothing about them. To see whether the models are on disk (this reads nothing and downloads nothing):

```bash
cd backend && python -m app.engines.warmup --status
```

Install the engines first, then **check them** (this also downloads the models now, instead of during your first upload):

```bash
cd backend
python -m app.engines.warmup                # every installed engine
python -m app.engines.warmup doctr          # or just one; exits 1 if it fails or is missing
```

```
  OK    Tesseract  found 100% of the sample values; first page 0.2s (includes loading the model), then 0.2s
  --    RapidOCR   not installed. pip install rapidocr-onnxruntime
  OK    PaddleOCR  found 100% of the sample values; first page 6.3s (includes loading the model), then 2.6s
  OK    docTR      found 100% of the sample values; first page 7.2s (includes loading the model), then 2.0s
```

The same check is the **Test** button next to each engine on the Reading engines page, and the page also has a **Download models** button per engine, so a client can do this step without a terminal (it is blocked in local-only mode, and when `LOCK_SETTINGS=1`).

**Where the models live.** Inside the app's own data folder, `backend/data/models` (so they travel with the app and no hidden `~/.cache` is involved). Change it with `MODELS_DIR`; `DOCTR_CACHE_DIR` and `PADDLE_PDX_CACHE_HOME` still override each engine individually. For a server with no internet, run the check on a connected machine and copy `data/models` across. Without a GPU the engines run on the CPU. PaddleOCR and docTR each run in a small process of their own, started on first use: PaddlePaddle and PyTorch cannot share a process (once Paddle is loaded, PyTorch's own weight setup fails inside it), and a crash in one engine then cannot take the server down. Their output is kept in `data/logs/ocr-<engine>.log`, which is the first place to look if one misbehaves.

**If an engine fails with `Permission denied` under `~/.cache`:** that folder is owned by another user, usually `root` after a `sudo pip install`. The app no longer needs it (PaddleOCR is loaded with its home folder inside `data/models`, and docTR is pointed there too), but other tools will keep failing until you fix it: `sudo chown -R $(whoami) ~/.cache`.

The Python packages themselves are installed with `pip` (or the Dockerfile), not from the web page: letting a page change the server's own software would be a risk.

**Optional: everything in Docker.** See *Run it all with Docker Compose* below.

**5. Tests** (offline, no network): `cd backend && python -m pytest -q`

## Run it all with Docker Compose (optional)

One command starts the web app and the backend, with Tesseract, every OCR engine and their models already inside the backend image:

```bash
cp .env.example .env          # optional: keys and options (provider keys can also be entered on the Settings page)
docker compose up --build     # first build is large (PyTorch, Paddle) and downloads the models once
# then open http://localhost:8080
```

- **One address.** nginx serves the web app and forwards `/api` to the backend over the internal network. Only the web app's port is published (`WEB_PORT`, default 8080); the backend is not reachable from outside.
- **One Dockerfile.** The root `Dockerfile` has a `backend` target (the API with every OCR engine) and a `frontend` target (the built web app behind nginx); compose builds one of each.
- **Data.** Uploads, the database and saved settings live in the `pagewise-data` volume. The OCR models are baked into the image (`/opt/models`), so the containers download nothing when they start and work with no internet.
- **`APP_API_KEY`.** If set, nginx adds it to every API call on the server side, so it is not inside the JavaScript the browser downloads. That also means anyone who can open the web app can use the API: put the web app behind your own login or VPN if that matters. Set `APP_SECRET_KEY` too, so saved provider keys are encrypted with a key that is not stored in the data volume.
- **Models on your own machine.** From inside a container, reach Ollama at `http://host.docker.internal:11434`.
- **Status.** These files (`docker-compose.yml`, the single root `Dockerfile` with its `backend` and `frontend` targets, `.dockerignore`, `frontend/nginx.conf.template`) were written and checked for consistency by tests, but **never built or run**, so expect to adjust them on the first real build. Running the app without Docker, as described above, is what has been exercised.

## Reviewing a document

The review screen puts the source PDF on the left (zoom, fit width, page controls; opens fitted to the pane) and the extraction on the right, with a draggable divider whose position is remembered. Four tabs: **Review**, **Pages**, **Findings**, **JSON**; the tab you are on is kept in the address (`?tab=pages`), so a refresh or a shared link lands in the same place.

- **At a glance.** The header says what is left: *verified*, *to check* and *errors* chips (the last two jump to the first value to check, or to the findings), and one line on how the file was read ("5 digital · 1 local OCR · no model calls"). *Export* and *Read again* are menus beside the file name.
- **Skim quickly.** A value that is fine takes one line with a small tick; only values that need a person open up, showing why, the other reading (*use “…”*), *Confirm*, and the source page. Click a value to see where it came from. A file with several documents switches between them with compact tabs (a drop-down beyond four), each with its count to check; a long document gets a *Jump to…* menu.
- **Work through what needs checking.** Filters (All, To check, Blank, Edited) and a search box narrow the list. A bar pinned to the bottom steps through every flagged value (`j` / `k`), fields and table cells alike, highlights each on the page, and confirms with `Enter`.
- **Edit with the right control.** Yes/no values are tick boxes, choices are drop-downs, multi-choice values are checklists, long text grows as you type, and every table cell is editable in place. Edits appear immediately and are saved in the background; the workspace's "to check" count follows.
- **Pages.** Every page, grouped by document: what it is, how it was read (Digital, Tesseract 93%, Tesseract + 2 regions by vision, Vision…), and why. Open a page to see the reasons, the lines the reader was unsure of, and a button to send it to the vision models.
- **Document menu.** Save an untemplated document as a document type, or read the rest of a templated one. *How these were read* explains where a document's values came from.
- **See the JSON.** The JSON tab shows `fields.json` and `pages.json` as a collapsible tree or raw text, with your edits applied, and can copy or download either.

## The Documents page

Built for many different files at once:

- **Upload many PDFs at once** (drop or choose several); each is read in turn, and a failure names the file and the reason.
- **Search, filter, sort.** Filters (All, To check, Reading, Failed, Clean) show counts; search matches the file name and what the file turned out to be; sort by newest, most to check, or name. Long lists page in blocks of 50.
- **How each file was read**: *Digital* (read by code), *Scanned* (vision models), *Handwriting*, plus **model use** per file (`None`, or tokens, with a per-stage breakdown on hover). The review screen repeats it ("68 digital pages read by code · no model calls") and says how each document's values were obtained.
- **Recurring layouts are suggested as document types** (the same file uploaded twice, and long filings, are not counted). One click saves it; the same suggestions appear under *Document types*.
- A notice appears when no model key is configured, saying what still works (digital PDFs) and what does not (scans and handwriting).
- On the review screen a file with many tables gets a *Jump to* menu; long tables scroll inside themselves with column headings and row labels kept in view, and a label repeated on a later page shows its page number.

## Checking and editing a template

Uploading a blank form opens the form beside what was read from it. Click a field to see where it was found on the form. Everything is editable: labels, types, required marks, choices, tables and their columns, links to other documents, date rules, and section headings; *View template JSON* shows the raw template. Your own types can be reopened later with *Edit* (changes apply to files uploaded afterwards); built-in types open read-only, with *Make an editable copy*.

## Workspaces

Everything lives inside a workspace: its documents, results, answer keys and **its own custom document types** (built-in types are shared). The app opens on the workspaces screen; you create one (or continue in the one you last used), then upload and review inside it. A switcher in the workspace bar moves between them.

- Workspace names are unique (ignoring case); rename and delete are on the workspaces screen. Deleting removes the workspace's documents, uploaded files and types, and asks first.
- API: everything is under `/api/workspaces/{id}/...` (`extractions`, `registry`, `templates`); `/api/workspaces` lists, creates, renames and deletes them. A document is never reachable through another workspace's URL.
- Uploading the same file twice reuses the result only inside the same workspace.
- Upgrading from a version without workspaces: existing documents and custom types are moved into a workspace called "My workspace" the first time the server starts. A fresh install starts empty.
- There are no user accounts yet: workspaces separate work, they do not restrict who can open them. Anyone who can reach the server (and has the API key, if one is set) sees every workspace.

## How a file is processed

1. **Work PDF.** Scanned pages get a Tesseract text layer (`reading/tess.py`), laid over the original so page size and coordinates are unchanged. Every geometric step (highlighting, label search, checkbox pixels, table rebuild) runs on it; the viewer shows the original.
2. **Read.** `reading/router.py` profiles each page and picks a reader, stored with its reasons (`route` in pages.json): embedded text, two vision models compared (`ocr_dual`), or Tesseract alone (`ocr_local`, nothing leaves the machine). Lines are compared by content, not line breaks, so layout differences are not disagreements but a different digit is.
3. **Sort.** Fax stamps are split off as metadata; pages are classified (keyword rules first, a small model only for unknown pages and only among registered types) and grouped into documents.
4. **Extract.** Each document with a template is read page by page by two models against the template's fields, and the best-supported reading per field wins. Checkboxes are read from the pixels (a hollow square beside the label, then the ink inside it), never from a model unless the box can't be located. Tables use the layout extractor ported from the SEC pipeline (`reading/table_extractor.py`), with PyMuPDF's grid finder as fallback.
5. **Ground and cross-check.** Each value is located on the page. Tesseract is an independent third reader: if both models agree but Tesseract reads something similar and different at that spot, the field goes to review. When the models disagree, the reading that also appears in the page's own text is shown first.
6. **Validate.** Per-document rules from the template (required fields, formats, date order), then cross-document consistency from each template's `canonical` section.

| Decision | Options |
|---|---|
| Reader | `text_layer` · `ocr_dual` · `ocr_local` · `text_layer_unverified` |
| Extractor | `template_form` (field schema in `app/templates`) · `kv` (generic Label: value) · `skip` |

Uploading the same file twice reuses the first result (SHA-256), so you don't pay for the same OCR again.

## Reading engines and settings

Scanned pages and handwriting can be read three ways, and each workspace chooses (**Reading engines** tab). Digital pages never cost anything: code reads them under every setting.

| Strategy | What happens to a scanned page | Models called |
|---|---|---|
| **Economy** | A local OCR engine reads it. Doubtful lines are flagged. | never |
| **Balanced** (default) | The local engine reads it first. Only if its reading is doubtful do two vision models read the page and compare. Clean pages are structured from their text. | only for doubtful pages |
| **Accuracy** | Two vision models read every scanned page and are compared. | every scanned page |
| **Custom** | The same knobs, set by hand: when to use a model, the confidence needed, a token cap per document. | as set |

**How "doubtful" is decided.** Tesseract reports a confidence per word: clean print scores about 90 to 95%, handwriting 40 to 50%, a badly degraded scan about 40%. A page is escalated when its confidence is below the threshold (85% by default), many words or numbers were hard to read, nothing was recognised on a page that has marks, or the text is garbled. Other engines (RapidOCR, PaddleOCR, docTR) report confidences that look alike on clean print and handwriting, so their pages are accepted only when Tesseract's reading, which the preparation step already produces, agrees with them (75% word overlap; clean pages score 80 to 90%, handwriting under 35%). The lines they disagree on are the ones flagged. Every decision and its reason is stored per page and shown on the review screen, where any page can also be sent to the vision models by hand, or the whole file read again under another strategy (this makes a second copy; the first is kept).

**Local OCR engines.** Tesseract is built in. RapidOCR, PaddleOCR and docTR appear on the page once installed (see *Install and run*). All four were run here on a sample page and on real scans: they read the sample's values correctly (about 1 to 2 seconds a page warm; the first page also loads the model, 15 to 20 seconds) and their cross-checks separated clean print (agreement 85 to 99%) from handwriting (6 to 34%). The neural engines run one page at a time, each in its own process (see below). Their models download on first use into `backend/data/models`; `python -m app.engines.warmup`, or the *Download models* button, fetches them in advance (see *Install and run*).

**Region-level re-reads.** Doubtfulness is judged line by line, because a page average hides one bad line. When only a few lines are doubtful (an engine unsure of the line or of a number in it, or a second engine disagreeing), just those regions are cropped and read by the two vision models, and their lines replace the local ones; the rest of the page keeps its local reading. That costs a couple of small images instead of a full page. If the doubt is scattered (more than three separate regions, more than half the page, or more than 40% of the lines), the page is poor as a whole and is read whole. A failed region read keeps the local reading, flagged, when the page otherwise passed.

**Vision models.** Pick up to two per workspace, from different providers if you like: `openai:gpt-4.1`, `anthropic:claude-sonnet-5-5`, `gemini:gemini-2.5-flash`, `ollama:qwen2.5vl:7b` (your own hardware), `custom:<model>` (any OpenAI-compatible server such as vLLM). The default pair follows whichever provider is connected (OpenAI's `gpt-4.1` and `gpt-4.1-mini` if it is). A **token cap** per document stops escalation once a budget is spent; remaining doubtful pages keep their local reading, flagged.

**Settings page.** Provider keys and addresses can be entered in the app (top bar, **Settings**). They are encrypted with Fernet before they are written to the database, are never sent back to the browser (only the last four characters), never logged, and a key saved there takes precedence over the same environment variable; removing it falls back to the environment. The encryption key is `APP_SECRET_KEY` if the server sets one (recommended: keep it outside the data folder), otherwise a random key in `DATA_DIR/secret.key` with owner-only permissions. Because access to Settings equals access to the keys, set `APP_API_KEY` when the server is reachable by anyone you do not trust.

| Environment variable | Effect |
|---|---|
| `READING_STRATEGY`, `LOCAL_OCR_ENGINE`, `ESCALATE_BELOW`, `TOKEN_CAP` | Server defaults for workspaces that have not chosen |
| `OPENAI_API_KEY` (`OPENAI_BASE_URL`), `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_BASE_URL`, `LLM_CUSTOM_BASE_URL` (`LLM_CUSTOM_API_KEY`, `LLM_CUSTOM_MODEL`) | Provider credentials, if you prefer the environment to the Settings page |
| `LOCAL_ONLY=1` | Cloud providers are switched off entirely: nothing can leave the machine. Local OCR and your own models still work |
| `LOCK_SETTINGS=1` | The Settings page is read-only, for deployments managed through the environment |
| `APP_SECRET_KEY` | Encryption key for saved credentials |

## Code map

```
backend/app
  main.py, config.py, db.py          app wiring, settings from the environment, tables
  api/                               HTTP: workspaces, extractions, templates, registry, engines (strategies, tests), settings (provider keys)
  engines/                           how pages get read, and by whom
    llm.py                           one call to any model provider (OpenAI, Anthropic, Gemini, Ollama, custom)
    local.py                         local OCR engines, word confidence, "is this reading good enough"
    isolated.py, worker.py           run PaddleOCR / docTR each in a process of their own (they cannot share one)
    ladder.py                        escalation for one scanned page: local first, vision models if doubtful, token cap
    plan.py                          strategies and the per-workspace reading plan
    credentials.py                   provider keys saved in the app, encrypted
  services/
    pipeline.py                      orchestrates one upload end to end;  export.py, usage_tracker.py
    reading/                         PDF to page text: pdf_pages, tess (text layer for scans), ocr (two-reader transcription),
                                     router (which reader), locate (find a value on the page), table_extractor
    extraction/                      page text to values: form_extractor (templates), discover (no template), digital (code reads
                                     digital pages), kv, remainder, checkboxes, adjudicate (third look), normalize, labels
    documents/                       what a document is: classify, template_draft, suggest (recurring layouts), workspace_types
    quality/                         validation (per-document rules), cross (consistency across documents)
  templates/                         built-in document templates
docker-compose.yml, Dockerfile, .env.example   run everything with Docker Compose (see above); frontend/nginx.conf.template
frontend/src
  pages/                             Documents, review, Document types, Reading engines, Settings, Landing
  components/, review/               shared pieces; the review screen's field rows, tables and PDF pane
```

## Any document, no template

A file that matches no template is still extracted, and the cost depends on what kind of pages it has.

| Page | Read by | Model use |
|---|---|---|
| Digital (real text layer): statements, filings, reports | **Code** (`extraction/digital.py`): table cells and `Label: value` pairs copied exactly from the PDF | none, except a few lines to name a column header that spans rows (once per distinct header) |
| Digital but **unproven** or form-like with nothing code could read | Two models on the page *text* (no image), second reader reads against the first's labels | text only, only for those pages |
| Scan or handwriting | Two vision models, first proposes the fields, second reads against its labels; one focused third look for disputed values | image tokens |

**Code proves it read a digital page completely.** Every number printed inside a table's region must appear in the extracted cells (footnote markers and "Note 7" headings excluded). If not, the page tries PyMuPDF's grid finder, then the table's cells are marked `review` with what was missed, and (when a model is configured) the page goes to the text-only model path. A text layer that is not text (`(cid:12)`, replacement characters) is treated as a scan. On a 68-page 10-Q this reads 41 tables / 2,200 cells with no model calls and flags exactly one table (a mangled dividends table), which the model path then reads correctly.

**Stable output.** Field keys are canonical (`extraction/labels.py`: "Invoice No." / "Inv #" / "Invoice Number" all become `invoice_number`; the section only joins a key when the same label occurs twice). A label with a different value on another page becomes `label_p<page>` instead of overwriting; rows of two readers' tables are paired by row label, not position.

**Recurring shapes.** `GET /api/workspaces/{id}/templates/suggestions` lists document shapes that keep recurring among untemplated files (same canonical keys, at least twice); promote one example to save it as a template.

Knobs: `DISCOVER_DIGITAL_MODEL=auto|never|always` (default `auto` as above), `DISCOVER_LONG_DOC_PAGES` (digital documents longer than this use one reader per page, default 25), `CLASSIFY_UNKNOWN_STREAK` (stop asking the classifier model after this many unknown pages in a row, default 3). Results are cached by file hash **and pipeline version**, so an upgrade never serves a stale extraction.

## Handwriting and poor scans

Handwriting goes through the same two-reader path as any scan; these rules exist because two models can share a misread.

- **The readers report handwriting** (in the same reply, no extra call). On such a page Tesseract is not used as a tie-break or "second opinion": it cannot read handwriting and would outvote the models with a wrong reading.
- **Numbers are compared strictly.** A leading decimal point (`.2%` vs `2%`), a range (`7-20` vs `720`), `%` and `$` are differences, not noise.
- **One focused third look per page, only when something is disputed** (`extraction/adjudicate.py`). The page is shown once with just the disputed values and their candidate readings. A third reading that matches a candidate settles it (two of three); a new reading stays in review; an unsure reading changes nothing. Pages where the readers agree on everything never pay for it.
- **Fields are paired by value as well as label**, since handwriting has no fixed labels; repeats of one value (same place, or one label inside the other) and empty "fields" that are really the page title or a sentence are dropped.

Cost: vision calls dominate (roughly 3 to 4k tokens per page image per call). A scanned page costs two reads for the transcript, two for the fields, and one more only if a value is disputed (about 10% extra on the samples tried). Knobs: `ADJUDICATE=0` turns the third look off; `ADJUDICATION_MODEL` picks its model (default: the first of `EXTRACTION_MODELS`); `HANDWRITING_OCR_MODELS` set to one model halves the transcript cost at the price of an unverified transcript. Pages with a real text layer cost nothing, and an identical file is never read twice.

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

**Discovery** (`extraction/discover.py`) needs no setup. Two vision models each list every labelled field, checkbox and table on a page; the lists are matched by label (tolerant of different section headings) and merged with the same trust model as templates. A grid that one reader returns as a table and the other as flat fields (`Flexion Right: 170°`) is reconciled, not flagged. Checkboxes are judged from pixels; every value is located on the page and checked against Tesseract. The output has the same shape as a templated extraction, so review, corrections and export are identical. Without a template there are no required fields or formats to enforce, so the findings are only the places the readers were unsure.

Three ways to get a type, none of which involves writing JSON:

1. **Upload a blank form** (Document types > Add a type from a blank form). The fields, types, choice groups, tables and required marks are drafted from it; you correct the draft (required marks especially) and save.
2. **Promote an extraction.** After reviewing a discovered document, "Save as document type" turns it into a type; the next file of that kind is recognised, validated and cross-checked.
3. **Hand-write a template** (below) for rules and cross-document checks the drafts cannot infer.

A type you add beats a built-in type with the same title in that workspace (someone who uploads their own template means to use it). Saving rejects built-in names, duplicate keys, unknown types, and user-supplied regex patterns (a ReDoS risk), which only hand-written, built-in templates may use.

A drafted template has **no links to other documents** yet (the `canonical` section below): the draft cannot know that a field is the same person's date of birth as in another document. Without links, cross-document checks (for example, a date of birth that differs between a form and a clinical note) are skipped for that type. Add them by hand until the screen can set them. The links are validated on save (kinds and field names are checked; regex patterns are refused).

Checkboxes on scans are judged from the pixels, never from the `☑`/`☐` characters in a model's transcript: those are the model's own guess. Only born-digital pages use text glyphs.

## Hand-written templates

1. Add an entry to `DOC_TYPES` in `app/services/documents/classify.py`: title patterns, `"extractor": "template_form"`, `"template": "<name>"`.
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

- Tesseract is covered under *Install and run*. Without it scans have no highlighting and there is no default local OCR engine.
- Without any model provider the app still runs: digital pages use embedded text and scans use a local OCR engine (single reader, marked unverified). Connect a provider on the **Settings** page, or with an environment variable, to read handwriting and poor scans.

## Known limits

- Rotated or skewed scans are not corrected before OCR.
- Pure handwriting is only as good as the vision models; Tesseract adds little there.
- Discovery reads one document per file when you force it (`Read without a template`); use automatic detection to split a packet. Labels that repeat within one section are suffixed `_2`, `_3` in order.
- A drafted template is a starting point: on the sample blank form it found 42 of the 43 fields I wrote by hand, with correct types, but it over-marked some fields as required and missed one choice group. Always check the required marks.
- When the two readers return a table in different shapes (one combined, one split in two), its cells are flagged rather than reconciled.
- Figures and charts are not analysed. The SEC pipeline's figure-description step (`image_data_prep.py`) is the model to port when a document type needs it.
- Checkbox labels Tesseract fails to read are settled by the model reading and flagged when they disagree.
- Uploads and results are stored on local disk and page images go to the configured model provider. Use a provider agreement that fits the sensitivity of the documents before processing real ones.
