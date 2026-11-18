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

const STEPS = [
    { t: 'Profile each page', d: 'Is there embedded text, or does a picture cover the page? Fax scans usually carry only a picture.', note: 'Decides the reader' },
    { t: 'Read the text', d: 'Digital pages use their own text. Scans get a Tesseract text layer for positions, and two vision models transcribe them and are compared.', note: 'Disagreements are kept, not hidden' },
    { t: 'Sort into documents', d: 'Fax stamps are split off as metadata. Pages are classified and grouped, so a 9-page packet becomes four documents.', note: 'Blank and cover pages are kept, not dropped' },
    { t: 'Extract and check', d: 'Each document is read field by field against its template. Rules then compare documents with each other.', note: 'Required fields, formats, cross-document facts' },
];

export default function Landing() {
    return (
        <div className="lp">
            <header className="lp-head">
                <div className="lp-wrap lp-head__in">
                    <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                    <nav className="lp-nav" aria-label="Page sections">
                        <a href="#how">How it works</a><a href="#output">Output</a><a href="#review">Review</a><a href="#types">Document types</a>
                    </nav>
                    <Link to="/app" className="btn btn--primary">Open workspace</Link>
                </div>
            </header>

            <main>
                <section className="lp-hero">
                    <div className="lp-wrap">
                        <h1>Read the whole packet. Check only what’s in doubt.</h1>
                        <p className="lp-lede">Upload any PDF: a scanned form, a fax, a statement, an application. {APP_NAME} reads every page, sorts the file into its documents, fills in the fields of each document type it knows, and flags the values its readers didn’t agree on.</p>
                        <div className="lp-cta">
                            <Link to="/app" className="btn btn--primary btn--lg">Open workspace</Link>
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

                <section id="how" className="lp-sec">
                    <div className="lp-wrap">
                        <h2>From scanned fax to checked values</h2>
                        <ol className="lp-steps">{STEPS.map((s, i) => (
                            <li key={s.t}><span className="lp-steps__n">{i + 1}</span><h3>{s.t}</h3><p>{s.d}</p><small>{s.note}</small></li>))}
                        </ol>
                    </div>
                </section>

                <section id="output" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap">
                        <h2>Two files, built to be loaded</h2>
                        <p className="lp-sub">Page-by-page content in one, each document’s key–value data in the other. Download both from any extraction.</p>
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
  "source": "ocr",
  "verified": true,
  "text": "Provider Prior Authorization…"
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
                        </div>
                    </div>
                </section>

                <section id="review" className="lp-sec">
                    <div className="lp-wrap lp-split">
                        <div>
                            <h2>Reviewers see the doubtful values first</h2>
                            <div className="lp-points">
                                <div><h3>Two readers, compared</h3><p>A value both readers agree on stays quiet. A disagreement keeps both readings, and one click takes the other.</p></div>
                                <div><h3>A queue, not a hunt</h3><p>Step through flagged values with <kbd>j</kbd> and <kbd>k</kbd>. Each one is highlighted on the source page.</p></div>
                                <div><h3>Rules that read across documents</h3><p>One document says one date, another says a different one. That becomes a finding, not something a person has to notice.</p></div>
                            </div>
                        </div>
                        <figure className="lp-spec" aria-label="Example of the review panel">
                            <div className="tally"><span className="tally__item"><b>31</b> verified</span><span className="tally__item tally__item--flag"><b>2</b> to check</span><span className="tally__item tally__item--flag"><b>2</b> errors</span></div>
                            <div className="field field--done"><span className="field__label">member id</span><span className="field__input">9000001234</span><span className="field__state">Both readers agree</span></div>
                            <div className="field field--flag"><span className="field__label">npi</span><span className="field__input">199999999</span><span className="field__state">Check</span>
                                <span className="field__alt">The second reader saw <span className="link">use “1999999990”</span></span></div>
                            <div className="field field--done"><span className="field__label">review type</span><span className="field__input">ROUTINE</span><span className="field__state">Read from checkbox</span></div>
                            <div className="finding finding--error"><span className="finding__sev">Error</span><span>Date of birth is 1970-07-01 in the form but 1975-01-15 in the daily note.</span></div>
                            <div className="finding finding--warn"><span className="finding__sev">Warning</span><span>Requested on the form but not in the daily note: 97112.</span></div>
                        </figure>
                    </div>
                </section>

                <section id="types" className="lp-sec lp-sec--tint">
                    <div className="lp-wrap lp-split">
                        <div>
                            <h2>One pipeline, chosen per document</h2>
                            <p className="lp-sub">A router profiles each page and picks how to read it, then picks how to extract each document. Every choice is recorded with its reason. Supporting a new kind of document means adding a registry entry and, for a fixed form, a template.</p>
                            <Link to="/app/types" className="btn">See document types</Link>
                        </div>
                        <ul className="lp-types">
                            <li><span>Prior authorization form</span><small>Field template</small></li>
                            <li><span>PT initial exam</span><small>Label and value pairs</small></li>
                            <li><span>Daily note and billing sheet</span><small>Label and value pairs</small></li>
                            <li><span>Fax cover sheet</span><small>Not extracted</small></li>
                            <li className="lp-types__next"><span>Your next document type</span><small>Registry entry</small></li>
                        </ul>
                    </div>
                </section>

                <section className="lp-close">
                    <div className="lp-wrap">
                        <h2>Start with a packet you already have</h2>
                        <Link to="/app" className="btn btn--lg lp-close__btn">Open workspace</Link>
                    </div>
                </section>
            </main>

            <footer className="lp-foot">
                <div className="lp-wrap">
                    <span>{APP_NAME}</span>
                    <p>Uploaded files and results are stored on the server running this app. Page images are sent to the model provider you configure; without a key, scans are read locally by Tesseract and nothing leaves the server. Use a provider agreement that fits the sensitivity of your documents before processing real ones.</p>
                </div>
            </footer>
        </div>
    );
}
