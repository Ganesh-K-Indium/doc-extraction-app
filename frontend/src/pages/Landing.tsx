import { Link } from 'react-router-dom';
import { APP_NAME } from '../brand';
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
    { t: 'Economy', cost: 'No model calls', d: 'Local OCR only. Free, private, fine for clean printed scans. Doubtful lines are flagged for you, and a template’s fields and tables are still filled from the text.', rec: false },
    { t: 'Balanced', cost: 'Models only when doubtful', d: 'Local OCR first. Weak lines, or weak pages, go to the vision models. Best cost for most documents.', rec: true },
    { t: 'Accuracy', cost: 'Models on every scan', d: 'Two vision models read every scanned page and are compared. Highest accuracy, highest cost.', rec: false },
    { t: 'Custom', cost: 'You decide', d: 'Pick the engine, the models, the confidence needed and a token cap.', rec: false },
];

const STEPS = [
    { t: 'Profile each page', d: 'Does it have real text, or is it a picture? Is the text layer readable? Is there handwriting? Each page is routed on what it actually is.', note: 'Decides the reader' },
    { t: 'Read it', d: 'Digital pages: text and table cells copied by code and verified against the page. Scans and handwriting: a local OCR engine first; where it is unsure, two vision models read just those lines or the whole page and are compared, with a third look at disputed values.', note: 'Disagreements are kept, not hidden' },
    { t: 'Sort into documents', d: 'Fax stamps are split off as metadata. Pages are classified and grouped, so a 9-page packet becomes four documents and a 68-page filing stays one.', note: 'Blank and cover pages are kept, not dropped' },
    { t: 'Extract and check', d: 'Each document is read against its template, or its structure and fields are found from the page when it has none. Rules then compare documents with each other.', note: 'Required fields, formats, cross-document facts' },
];

export default function Landing() {
    return (
        <div className="lp">
            <header className="lp-head">
                <div className="lp-wrap lp-head__in">
                    <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                    <nav className="lp-nav" aria-label="Page sections">
                        <a href="#kinds">Any document</a><a href="#engines">Engines</a><a href="#how">How it works</a><a href="#output">Output</a><a href="#review">Review</a><a href="#types">Document types</a>
                    </nav>
                    <Link to="/app" className="btn btn--primary">Open workspaces</Link>
                </div>
            </header>

            <main>
                <section className="lp-hero">
                    <div className="lp-wrap">
                        <h1>Read the whole packet. Check only what’s in doubt.</h1>
                        <p className="lp-lede">Upload any PDF: a financial filing, a scanned form, a fax, a handwritten note. {APP_NAME} reads every page the cheapest reliable way, sorts the file into its documents, and flags only the values it could not prove. Digital pages are read directly from the PDF and checked against the page. Scans are read by free local OCR first, and a vision model steps in only for the lines or pages it cannot read well. You choose the engines and the models.</p>
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
                        <p className="lp-sub">No template to write first. Each page is routed by what it is, so you do not pay model prices for text the PDF already holds.</p>
                        <div className="lp-points lp-points--cols">
                            <div><h3>Digital PDFs: read by code</h3><p>Statements, filings and reports have real text and real table cells. They are copied exactly, and every number in a table is checked against the page. No model calls, unless a form-like page cannot be proven complete.</p></div>
                            <div><h3>Scans and handwriting: local first, models when needed</h3><p>A local OCR engine reads the page and says how sure it is. Clean pages stay local and free. Doubtful lines, or whole pages, go to two vision models that read independently and are compared. What is still in doubt goes to the review queue.</p></div>
                            <div><h3>Anything else: structured, then remembered</h3><p>No template needed. Every page also comes out as structured content: headings, paragraphs, label and value groups, tables and lists, with the dates, amounts and contacts found. Fields get stable names ("Invoice No." and "Inv #" are one key). When a layout keeps recurring, save it as a document type in one click.</p></div>
                        </div>
                    </div>
                </section>

                <section id="engines" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap">
                        <h2>You choose how scans are read</h2>
                        <p className="lp-sub">Set it once per workspace, or per upload. Digital PDFs cost nothing under every choice.</p>
                        <div className="lp-modes">{MODES.map(m => (
                            <div key={m.t} className={m.rec ? 'lp-mode lp-mode--rec' : 'lp-mode'}>
                                <h3>{m.t}{m.rec && <em> recommended</em>}</h3><small>{m.cost}</small><p>{m.d}</p>
                            </div>))}
                        </div>
                        <div className="lp-points lp-points--cols">
                            <div><h3>Local OCR engines</h3><p>Tesseract, RapidOCR, PaddleOCR and docTR, free and on your server. The newer engines are checked against Tesseract before a page is trusted, because their own confidence can’t tell print from handwriting.</p></div>
                            <div><h3>Vision models you pick</h3><p>OpenAI, Claude, Gemini, Ollama on your own hardware, or any OpenAI-compatible server. Choose two, from different providers if you like. Connect them on the Settings page: keys are stored encrypted.</p></div>
                            <div><h3>Pay for the line, not the page</h3><p>When only a few lines are doubtful, only those regions are cropped and sent. A token cap per document stops the spend, and the review screen shows which engine read each page and why.</p></div>
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
                        <p className="lp-sub">Page-by-page content and how it was read, each document’s key–value data, and the document’s structure as headings, text, tables and lists. Open a page in the app to see its structure beside how it was read, or download any file from an extraction.</p>
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
  "rows": [["97110", "Exercise", "2"]] }`}</pre>
                            </figure>
                        </div>
                    </div>
                </section>

                <section id="review" className="lp-sec">
                    <div className="lp-wrap lp-split">
                        <div>
                            <h2>Reviewers see the doubtful values first</h2>
                            <div className="lp-points">
                                <div><h3>Know how every value was read</h3><p>Each value says where it came from: copied from the PDF’s text, agreed by two readers, settled by a third reading, or edited by you. Each file shows how many model calls it cost.</p></div>
                                <div><h3>Two readers, compared</h3><p>Where a vision model reads a page, a value both readers agree on stays quiet. A disagreement keeps both readings, and one click takes the other. Not happy with a page? Send it to the vision models, or read the whole file again under another strategy, and compare the two.</p></div>
                                <div><h3>A queue, not a hunt</h3><p>Filter to what needs checking, edit values and table cells in place, and step through flagged values with <kbd>j</kbd> and <kbd>k</kbd>. Each one is highlighted on the source page.</p></div>
                                <div><h3>Rules that read across documents</h3><p>One document says one date, another says a different one. That becomes a finding, not something a person has to notice.</p></div>
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
                            <p className="lp-sub">A router profiles each page and picks how to read it, then picks how to extract each document. Every choice is recorded with its reason. You never have to define a type up front: a document with no template is read by discovery, and layouts that keep recurring are suggested as types. You can also upload a blank form to draft one. Types belong to a workspace, and a form sitting inside a longer document is found wherever its title appears.</p>
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
                    <p>Uploaded files and results are stored on the server running this app. Digital pages are read on that server by code and nothing leaves it. Under the Economy strategy, or with local-only mode on, nothing leaves the server at all: scans are read by local OCR engines, or by models on your own hardware. Otherwise only the page images (or just the cropped regions) of scans that local OCR could not read well, and, for form-like digital pages code cannot fully read, page text, are sent to the model provider you connect. Provider keys you enter are stored encrypted and never shown again. Use a provider agreement that fits the sensitivity of your documents before processing real ones.</p>
                </div>
            </footer>
        </div>
    );
}
