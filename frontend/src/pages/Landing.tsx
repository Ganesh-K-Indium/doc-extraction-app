import { Link } from 'react-router-dom';
import { APP_NAME } from '../brand';
import { ThemeToggle } from '../components/ThemeToggle';
import './landing.css';

type Kind = 'cover' | 'blank' | 'form' | 'text' | 'bill';
// The sample packet: a 9-page fax holding four documents.
const PAGES: { n: number; kind: Kind }[] = [
    { n: 1, kind: 'cover' }, { n: 2, kind: 'blank' }, { n: 3, kind: 'form' },
    { n: 4, kind: 'text' }, { n: 5, kind: 'text' }, { n: 6, kind: 'text' }, { n: 7, kind: 'text' },
    { n: 8, kind: 'bill' }, { n: 9, kind: 'text' },
];
const GROUPS = [
    { label: 'Fax cover', pages: '1–2', span: 2, extract: false },
    { label: 'Prior authorization form', pages: '3', span: 1, extract: true },
    { label: 'PT initial exam', pages: '4–7', span: 4, extract: false },
    { label: 'Daily note', pages: '8–9', span: 2, extract: false },
];

function Sheet({ kind, n }: { kind: Kind; n: number }) {
    return (
        <div className={`lp-sheet lp-sheet--${kind}`} style={{ ['--i' as string]: n - 1 }} aria-hidden="true">
            <i className="lp-sheet__stamp" />
            {kind === 'cover' && <><b className="lp-sheet__title" /><i /><i /><i className="s" /></>}
            {kind === 'blank' && <span className="lp-sheet__logo" />}
            {kind === 'form' && <>
                <b className="lp-sheet__title" />
                <div className="lp-sheet__boxes"><span className="on" /><span /><span /></div>
                <div className="lp-sheet__cells"><i /><i /><i /><i /><i /><i /></div>
            </>}
            {kind === 'text' && <><b className="lp-sheet__title s" /><i /><i /><i className="s" /><i /><i /><i className="s" /><i /></>}
            {kind === 'bill' && <><b className="lp-sheet__title s" /><i /><i className="s" /><div className="lp-sheet__cells"><i /><i /><i /><i /></div><i /></>}
            <span className="lp-sheet__n">{n}</span>
        </div>
    );
}

const MODES = [
    { t: 'Economy', cost: 'No model calls', d: 'Local OCR only. Free and private, fine for clean printed scans. Doubtful lines are flagged for you.', rec: false },
    { t: 'Balanced', cost: 'Models only when doubtful', d: 'Local OCR first. Only weak lines or pages go to the vision models. Best cost for most documents.', rec: true },
    { t: 'Accuracy', cost: 'Models on every scan', d: 'Two vision models read every scanned page and are compared. Highest cost.', rec: false },
    { t: 'Custom', cost: 'You decide', d: 'Pick the engine, the models, the confidence needed and a token cap.', rec: false },
];

const STEPS = [
    { t: 'Profile each page', d: 'Real text or a picture? Readable text layer? Handwriting? Each page is routed on what it is.', note: 'Decides the reader' },
    { t: 'Read it', d: 'Digital pages are copied by code and verified against the page. Scans go to a local OCR engine first; where it is unsure, two vision models read just those lines or the whole page and are compared, with a third look at disputed values.', note: 'Disagreements are kept, not hidden' },
    { t: 'Sort into documents', d: 'Fax stamps become metadata. Pages are classified and grouped, so a 9-page packet becomes four documents and a 68-page filing stays one.', note: 'Blank and cover pages are kept, not dropped' },
    { t: 'Extract and check', d: 'Each document is read against its template, or its fields are found from the page when it has none. Rules then compare documents with each other.', note: 'Required fields, formats, cross-document facts' },
];

export default function Landing() {
    return (
        <div className="lp">
            <header className="lp-head">
                <div className="lp-wrap lp-head__in">
                    <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                    <nav className="lp-nav" aria-label="Page sections">
                        <a href="#kinds">Any document</a><a href="#scans">Scans</a><a href="#engines">Engines</a><a href="#how">How it works</a><a href="#output">Output</a><a href="#review">Review</a><a href="#types">Document types</a>
                    </nav>
                    <ThemeToggle />
                    <Link to="/app" className="btn btn--primary">Open workspaces</Link>
                </div>
            </header>

            <main>
                <section className="lp-hero">
                    <div className="lp-wrap">
                        <h1>Read the whole packet. Check only what’s in doubt.</h1>
                        <p className="lp-lede">Upload any PDF: a financial filing, a scanned form, a fax, a handwritten note. {APP_NAME} reads every page the cheapest reliable way, sorts the file into its documents, and flags only the values it could not prove.</p>
                        <div className="lp-cta">
                            <Link to="/app" className="btn btn--primary btn--lg">Open workspaces</Link>
                            <a href="#output" className="btn btn--lg">See the output</a>
                        </div>

                        <figure className="lp-packet">
                            <div className="lp-strip">{PAGES.map(p => <Sheet key={p.n} kind={p.kind} n={p.n} />)}</div>
                            <div className="lp-groups">{GROUPS.map(g => (
                                <div key={g.label} className={g.extract ? 'lp-group lp-group--x' : 'lp-group'} style={{ gridColumn: `span ${g.span}` }}>
                                    <span>{g.label}</span><small>{g.extract ? `Page ${g.pages}, fields extracted` : `Pages ${g.pages}`}</small>
                                </div>))}
                            </div>
                            <figcaption>One 9-page fax packet, read as four documents. Your own document types work the same way.</figcaption>
                        </figure>
                    </div>
                </section>

                <section id="kinds" className="lp-sec">
                    <div className="lp-wrap">
                        <h2>Any document, read the right way</h2>
                        <p className="lp-sub">No template to write first. You never pay model prices for text the PDF already holds.</p>
                        <div className="lp-points lp-points--cols lp-points--quad">
                            <div><h3>Digital PDFs: read by code</h3><p>Real text and table cells are copied exactly, and every number in a table is checked against the page. No model calls, unless a form-like page cannot be proven complete.</p></div>
                            <div><h3>Scans and handwriting: local first, models when needed</h3><p>Clean pages stay local and free. Doubtful lines or pages go to two vision models that read independently and are compared; what is still in doubt goes to the review queue.</p></div>
                            <div><h3>Anything else: structured, then remembered</h3><p>Every page comes out as headings, paragraphs, label and value groups, tables and lists, with dates, amounts and contacts found. Fields get stable names ("Invoice No." and "Inv #" are one key). A layout that keeps recurring can be saved as a document type in one click.</p></div>
                            <div><h3>Charts, diagrams and drawings: found free, read when you ask</h3><p>Figures are found on every page at no cost, with their captions and printed labels. Reading one is a single model call on a small crop, only when you click: a chart comes back as axes and values, a diagram as parts and connections. A value worked out from the picture is marked as an estimate. If one is off, type the right value over it: no model call, and it is marked as manually corrected.</p></div>
                        </div>
                    </div>
                </section>

                <section id="health" className="lp-sec">
                    <div className="lp-wrap">
                        <h2>Health records and forms, read as they are laid out</h2>
                        <p className="lp-sub">Claims, explanations of benefits, lab reports and intake forms are mostly boxes, ticks and half-empty tables.</p>
                        <div className="lp-points lp-points--cols">
                            <div><h3>Boxes are not tables</h3><p>A grid of check boxes becomes a list of options, grouped under its question. A box of &ldquo;Label: value&rdquo; cells becomes fields. A watermark or a numbered key beside a report is set aside, so it does not end up in a cell.</p></div>
                            <div><h3>Headers set over two lines</h3><p>Stacked labels make the columns, and each value goes under its own label. Column labels over empty lines are a blank table to fill in.</p></div>
                            <div><h3>Checks that know health records</h3><p>NPI check digits, ICD-10 and CPT formats, birth and service dates, doses without a unit, and totals that do not add up. They raise a flag with the reason; a person decides.</p></div>
                                                    </div>
                    </div>
                </section>

                <section id="scans" className="lp-sec">
                    <div className="lp-wrap">
                        <h2>Scans keep their tables</h2>
                        <p className="lp-sub">A scan has only pixels, so its table rules are found in the picture and the tables are rebuilt from them the way they are for a digital page.</p>
                        <div className="lp-points lp-points--cols">
                            <div><h3>Straightened, then read</h3><p>The tilt of a scan is measured from its text lines and taken out before OCR, so rows stop sloping across the page. A level page is never touched.</p></div>
                            <div><h3>Rules found in the picture</h3><p>Long printed lines become cells, spanning headers and stacked tables. A chart bar or a tall letter is not mistaken for a table line.</p></div>
                            <div><h3>The checks help each other</h3><p>If a model gives up after a few rows of a long table, the table read from the rules fills in, marked for review. A disputed NPI or code is settled by its check digit or format, with no model call.</p></div>
                        </div>
                        <p className="lp-sub">On degraded copies of our healthcare samples, with the digital reading as the answer key and no model calls, table cells found rose from 11% to 69% and values found from 74% to 83%. Real faxes and handwriting are not yet measured.</p>
                    </div>
                </section>

                <section id="engines" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap">
                        <h2>You choose how scans are read</h2>
                        <p className="lp-sub">Set it once per workspace, or per upload. Digital PDFs cost nothing under any choice.</p>
                        <div className="lp-modes">{MODES.map(m => (
                            <div key={m.t} className={m.rec ? 'lp-mode lp-mode--rec' : 'lp-mode'}>
                                <h3>{m.t}{m.rec && <em> recommended</em>}</h3><small>{m.cost}</small><p>{m.d}</p>
                            </div>))}
                        </div>
                        <div className="lp-points lp-points--cols">
                            <div><h3>Local OCR engines</h3><p>Tesseract, RapidOCR, PaddleOCR and docTR, free and on your server. By default Economy uses RapidOCR (most values read correctly in our tests) and Balanced uses PaddleOCR (fewest pages sent on to a model). The newer engines are checked against Tesseract, because their own confidence can’t tell print from handwriting.</p></div>
                            <div><h3>Vision models you pick</h3><p>OpenAI, Claude, Gemini, Ollama on your own hardware, or any OpenAI-compatible server. Choose two, from different providers if you like, and connect them on the Settings page.</p></div>
                            <div><h3>Pay for the line, not the page</h3><p>When only a few lines are doubtful, only those regions are cropped and sent. A token cap per document stops the spend.</p></div>
                        </div>
                    </div>
                </section>

                <section id="how" className="lp-sec">
                    <div className="lp-wrap">
                        <h2>From any PDF to checked values</h2>
                        <ol className="lp-steps">{STEPS.map((s, i) => (
                            <li key={s.t}><span className="lp-steps__n">{i + 1}</span><h3>{s.t}</h3><p>{s.d}</p><small>{s.note}</small></li>))}
                        </ol>
                    </div>
                </section>

                <section id="output" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap">
                        <h2>Three files, built to be loaded</h2>
                        <p className="lp-sub">Page content and how it was read, each document’s key–value data, and its structure as headings, text, tables and lists. Download any of them from an extraction, or a reviewed.csv of every value and table cell with your corrections.</p>
                        <div className="lp-code2">
                            <figure className="lp-code">
                                <figcaption>pages.json</figcaption>
                                <pre>{`{
  "page": 3,
  "classification": { "type": "prior_auth_form" },
  "route": {
    "reader": "ocr_dual",
    "reasons": ["a picture covers most of the page"]
  },
  "page_meta": { "fax_page": 3, "fax_pages": 9 },
  "source": "ocr-local",
  "reading": { "engine": "doctr", "confidence": 0.94 },
  "text": "Provider Prior Authorization…",
  "structure": { "blocks": [ … ], "entities": [ … ] }
}`}</pre>
                            </figure>
                            <figure className="lp-code">
                                <figcaption>fields.json</figcaption>
                                <pre>{`"review_type": {
  "value": "ROUTINE",
  "method": "pixel",
  "status": "agreed"
},
"facility.npi": {
  "value": "199999999",
  "status": "review",
  "alternatives": ["1999999990"],
  "page": 3,
  "bbox": [412.1, 291.4, 480.9, 303.2]
}`}</pre>
                            </figure>
                            <figure className="lp-code">
                                <figcaption>structure.json</figcaption>
                                <pre>{`{ "type": "heading", "level": 2,
  "text": "INCOME STATEMENTS" },
{ "type": "key_value", "items": [
  { "label": "Patient Name",
    "value": "Morgan Taylor" } ] },
{ "type": "table",
  "columns": ["Code", "Service", "Units"],
  "rows": [["97110", "Exercise", "2"]] },
{ "type": "figure", "kind": "chart",
  "caption": "Figure 2: Revenue by quarter",
  "reading": { "chart": { "series": [ { "points": [
    { "x": "Q2", "y": "62", "estimated": false },
    { "x": "Q3", "y": "about 48", "value": 48,
      "estimated": true } ] } ] } } }`}</pre>
                            </figure>
                        </div>
                    </div>
                </section>

                <section id="review" className="lp-sec">
                    <div className="lp-wrap lp-split">
                        <div>
                            <h2>Reviewers see the doubtful values first</h2>
                            <div className="lp-points">
                                <div><h3>Know how every value was read</h3><p>Each value says where it came from: the PDF’s text, two readers that agreed, a third reading, or you. Each file shows how many model calls it cost.</p></div>
                                <div><h3>Disagreements keep both readings</h3><p>One click takes the other. Not happy with a page? Send it to the vision models, or read the whole file again under another strategy and compare.</p></div>
                                <div><h3>A queue, not a hunt</h3><p>Filter to what needs checking, edit values and table cells in place, and step through flagged values with <kbd>j</kbd> and <kbd>k</kbd>, each highlighted on the source page. Finish a file and jump to the next one that still has something to check.</p></div>
                                <div><h3>Rules that read across documents</h3><p>If one document says one date and another a different one, that becomes a finding, not something a person has to notice.</p></div>
                            </div>
                        </div>
                        <figure className="lp-spec" aria-label="Example of the review panel">
                            <div className="tally"><span className="tally__item"><b>31</b> verified</span><span className="tally__item tally__item--flag"><b>2</b> to check</span><span className="tally__item tally__item--flag"><b>2</b> errors</span></div>
                            <div className="field field--done"><label className="field__label">member id</label><div className="field__control"><span className="field__input">9000001234</span></div><div className="field__meta"><span className="field__state">Both readers agree</span></div></div>
                            <div className="field field--flag"><label className="field__label">npi</label><div className="field__control"><span className="field__input">199999999</span></div><div className="field__meta"><span className="field__state">Check</span>
                                <span className="field__alt">The second reader saw <span className="link">use “1999999990”</span></span></div></div>
                            <div className="field field--done"><label className="field__label">review type</label><div className="field__control"><span className="field__input">ROUTINE</span></div><div className="field__meta"><span className="field__state">Read from checkbox</span></div></div>
                            <div className="field field--done"><label className="field__label">total revenue</label><div className="field__control"><span className="field__input">82,886</span></div><div className="field__meta"><span className="field__state">Read from the PDF text</span></div></div>
                            <div className="finding finding--error"><span className="finding__sev">Error</span><span>Date of birth is 1970-07-01 in the form but 1975-01-15 in the daily note.</span></div>
                            <div className="finding finding--warn"><span className="finding__sev">Warning</span><span>Requested on the form but not in the daily note: 97112.</span></div>
                        </figure>
                    </div>
                </section>

                <section id="types" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap lp-split">
                        <div>
                            <h2>One pipeline, chosen per page and per document</h2>
                            <p className="lp-sub">Every choice of reader and extraction is recorded with its reason. You never have to define a type up front: a document with no template is read by discovery, recurring layouts are suggested as types, and a blank form can be uploaded to draft one. Types belong to a workspace, and a form inside a longer document is found wherever its title appears.</p>
                            <Link to="/app" className="btn">Open workspaces</Link>
                        </div>
                        <ul className="lp-types">
                            <li><span>Prior authorization form</span><small>Field template</small></li>
                            <li><span>PT initial exam</span><small>Field template</small></li>
                            <li><span>Daily note and billing sheet</span><small>Field template</small></li>
                            <li><span>Fax cover sheet</span><small>Not extracted</small></li>
                            <li><span>Financial statements and reports</span><small>Read by code, no template</small></li>
                            <li><span>Handwritten notes</span><small>Local OCR, then vision models</small></li>
                            <li className="lp-types__next"><span>Any other document</span><small>Structured, then saved as a type</small></li>
                        </ul>
                    </div>
                </section>

                <section className="lp-close">
                    <div className="lp-wrap">
                        <h2>Start with the files you already have</h2>
                        <Link to="/app" className="btn btn--lg lp-close__btn">Open workspaces</Link>
                    </div>
                </section>
            </main>

            <footer className="lp-foot">
                <div className="lp-wrap">
                    <span>{APP_NAME}</span>
                    <p>Uploaded files and results are stored on the server running this app, and digital pages are read there by code. Under the Economy strategy, or with local-only mode on, nothing leaves the server. Otherwise the model provider you connect receives only the page images (or cropped regions) of scans that local OCR could not read well, page text for form-like digital pages code cannot fully read, and one cropped image for a figure you ask to be read. Provider keys are stored encrypted and never shown again. Use a provider agreement that fits the sensitivity of your documents before processing real ones.</p>
                </div>
            </footer>
        </div>
    );
}
