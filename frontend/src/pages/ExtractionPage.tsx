import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, authHeaders, type BBox, type Cell, type Detail, type Finding, type Form } from '../api';
import { type Overlay, type PdfViewerHandle } from '../components/PdfViewer';
import { Split } from '../components/Split';
import { useWorkspace } from '../workspaceContext';
import { FieldRow } from '../review/FieldRow';
import { allCells, cellAt, FLAGGED, matches, revealInPane, rowId, scrollPaneTo, withEdit, type Filter, type QItem, type Value } from '../review/helpers';
import { JsonView } from '../review/JsonView';
import { PdfPane } from '../review/PdfPane';
import { TableGrid } from '../review/TableGrid';
import '../components/textLayer.css';

type Tab = 'fields' | 'pages' | 'findings' | 'json';
const FILTERS: [Filter, string][] = [['all', 'All'], ['check', 'To check'], ['blank', 'Blank'], ['edited', 'Edited']];
const EXTRACT_LABEL: Record<string, string> = { template_form: 'Read against a template', discover: 'Read without a template', kv: 'Read as label and value pairs', skip: 'Not extracted' };
const READER_LABEL: Record<string, string> = { text_layer: 'embedded text, by code', ocr_dual: 'two vision readers', ocr_ladder: 'local OCR, with vision models if it was doubtful', ocr_local: 'local OCR on this server', text_layer_unverified: 'the scanner’s own text (unverified)' };

/** One honest sentence about how a document's values were obtained. */
function provenance(f: Form): string {
    if (f.readers.includes('text-layer')) return 'Read directly from the PDF’s own text and tables, so these values are exact copies. Tables were checked against the page: every number printed in them is present.';
    if (f.readers.length > 1) return 'Read by two models independently and compared. Values they agree on are quiet; anything else is marked Check.';
    if (f.readers.length === 1) return 'Read by one model only, so nothing was cross-checked. Treat every value as unverified.';
    return 'No model was available, so only text the PDF already holds was used.';
}
function readLine(s: NonNullable<Detail['stats']>): string {
    const parts: string[] = [];
    if (s.digital_pages) parts.push(`${s.digital_pages} digital ${s.digital_pages === 1 ? 'page' : 'pages'} read by code`);
    if (s.local_ocr_pages !== undefined) {
        if (s.local_ocr_pages) parts.push(`${s.local_ocr_pages} scanned ${s.local_ocr_pages === 1 ? 'page' : 'pages'} read by local OCR`);
        if (s.vision_pages) parts.push(`${s.vision_pages} read by vision models${s.escalated_pages ? ` (${s.escalated_pages} sent on because local OCR was doubtful)` : ''}`);
    } else if (s.scanned_pages) parts.push(`${s.scanned_pages} scanned ${s.scanned_pages === 1 ? 'page' : 'pages'} read by models`);
    if (s.handwritten_pages) parts.push(`${s.handwritten_pages} with handwriting`);
    if (s.usage) parts.push(s.usage.calls === 0 ? 'no model calls' : `${s.usage.calls} model ${s.usage.calls === 1 ? 'call' : 'calls'}, ${s.usage.tokens.toLocaleString()} tokens`);
    return parts.join(' · ');
}
const sectionId = (doc: number, name: string) => `sec-${doc}-${name.replace(/\W/g, '_')}`;

const formTitle = (f: Form) => (f.discovered ? f.label || 'Untitled document' : f.template_id);
const pageRange = (p: number[]) => (p.length === 1 ? `page ${p[0]}` : `pages ${p[0]}–${p[p.length - 1]}`);

export default function ExtractionPage() {
    const { wid = '', id = '' } = useParams();
    const { workspace, reload } = useWorkspace();
    const [data, setData] = useState<Detail | null>(null);
    const [error, setError] = useState('');
    const [tab, setTab] = useState<Tab>('fields');
    const [activeDoc, setActiveDoc] = useState<number | null>(null);
    const [filter, setFilter] = useState<Filter>('all');
    const [query, setQuery] = useState('');
    const [highlight, setHighlight] = useState<{ page: number; bbox: BBox } | null>(null);
    const [visible, setVisible] = useState(1);
    const [sel, setSel] = useState<QItem | null>(null);
    const [saved, setSaved] = useState<Record<number, string>>({});
    const [reading, setReading] = useState<number | null>(null);
    const [restNote, setRestNote] = useState<Record<number, string>>({});
    const [rereading, setRereading] = useState(false);
    const nav = useNavigate();
    const viewer = useRef<PdfViewerHandle>(null);
    const headers = useMemo(() => authHeaders(), []);

    const load = useCallback(() => api.get(wid, id).then(setData).catch(e => setError(e.message)), [wid, id]);
    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        if (!data || data.status === 'done' || data.status === 'failed') return;
        const t = setInterval(load, 1500);
        return () => clearInterval(t);
    }, [data, load]);

    const forms = useMemo(() => data?.fields?.forms ?? [], [data]);
    const findings = useMemo(() => data?.fields?.validation ?? [], [data]);

    // Everything that needs a person: flagged fields and table cells, plus fields an error finding points at.
    const queue = useMemo<QItem[]>(() => {
        const out: QItem[] = [];
        for (const f of forms) for (const { key, cell } of allCells(f)) {
            const pointed = findings.some(x => x.severity === 'error' && x.field === key && (x.doc_index ?? f.doc_index) === f.doc_index);
            if ((FLAGGED.has(cell.status) || pointed) && cell.status !== 'corrected') out.push({ doc: f.doc_index, key });
        }
        return out;
    }, [forms, findings]);
    const toCheck = useMemo(() => { const m = new Map<number, number>(); queue.forEach(q => m.set(q.doc, (m.get(q.doc) ?? 0) + 1)); return m; }, [queue]);

    const tally = useMemo(() => {
        let verified = 0;
        for (const f of forms) for (const { cell } of allCells(f)) if (cell.status === 'agreed' || cell.status === 'corrected' || cell.status === 'single') verified++;
        return { verified };
    }, [forms]);

    // Which document the Fields tab shows: the one chosen, else the first that has something to check.
    const activeIdx = activeDoc ?? (forms.find(f => toCheck.has(f.doc_index)) ?? forms.find(f => !f.remainder) ?? forms[0])?.doc_index;
    const active = forms.find(f => f.doc_index === activeIdx);

    const jump = useCallback((page: number, bbox?: BBox | null) => {
        if (bbox) { setHighlight({ page, bbox }); viewer.current?.scrollToRect(page, bbox); }
        else { setHighlight(null); viewer.current?.scrollToPage(page, true); }
    }, []);
    const select = useCallback((q: QItem, cell?: Cell) => {
        setSel(q); setActiveDoc(q.doc);
        if (cell) jump(cell.page, cell.bbox);
    }, [jump]);
    useEffect(() => { if (sel && tab === 'fields') revealInPane(document.getElementById(rowId(sel.doc, sel.key))); }, [sel, activeIdx, tab]);

    // Edits show immediately; the server confirms in the background and the list's "to check" count follows.
    const save = useCallback(async (doc: number, key: string, value: Value) => {
        setData(d => (d?.fields ? { ...d, fields: { ...d.fields, forms: d.fields.forms.map(f => (f.doc_index === doc ? withEdit(f, key, value) : f)) } } : d));
        try {
            const r = await api.correct(wid, id, doc, key, value);
            setData(d => (d?.stats ? { ...d, stats: { ...d.stats, needs_review: r.needs_review } } : d));
            reload();
        } catch (e) { setError((e as Error).message); load(); }
    }, [wid, id, load, reload]);

    const at = sel ? queue.findIndex(q => q.doc === sel.doc && q.key === sel.key) : -1;
    const step = useCallback((dir: 1 | -1) => {
        if (!queue.length) return;
        const next = queue[(at + dir + queue.length) % queue.length];
        select(next, cellAt(forms.find(f => f.doc_index === next.doc), next.key));
    }, [queue, at, select, forms]);

    // j / k step through what needs checking; Enter confirms the current value.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey || tab !== 'fields' || !queue.length) return;
            if (e.key === 'j' || e.key === 'k') { step(e.key === 'j' ? 1 : -1); e.preventDefault(); }
            else if (e.key === 'Enter' && sel && at >= 0) {
                const c = cellAt(forms.find(f => f.doc_index === sel.doc), sel.key);
                if (c && c.value !== null && c.value !== undefined) { save(sel.doc, sel.key, c.value as Value); e.preventDefault(); }
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [queue, sel, at, tab, step, forms, save]);

    const overlays: Overlay[] = highlight ? [{ page: highlight.page, rects: [highlight.bbox], kind: 'hl' }] : [];
    const findingJump = (f: Finding) => {
        const form = forms.find(x => x.doc_index === f.doc_index) || forms[0];
        const cell = f.field ? form?.fields[f.field] : undefined;
        if (cell && f.field) { setTab('fields'); select({ doc: form.doc_index, key: f.field }, cell); }
    };
    const openDoc = (f: Form) => { setActiveDoc(f.doc_index); setSel(null); viewer.current?.scrollToPage(f.pages[0], true); };

    if (error && !data) return <main className="list"><p className="notice notice--error" role="alert">{error}</p><Link to={`/app/w/${wid}`}>Back to documents</Link></main>;
    if (!data) return <main className="list"><p className="muted">Loading document</p></main>;

    const done = data.status === 'done';
    const errors = findings.filter(f => f.severity === 'error').length;
    const warnings = findings.filter(f => f.severity !== 'info').length;

    const groups = (f: Form) => {
        const g = new Map<string, { title: string; keys: string[] }>();
        for (const [k, c] of Object.entries(f.fields)) {
            const prefix = k.includes('.') ? k.split('.')[0] : 'form';
            const entry = g.get(prefix) ?? { title: c.section || prefix.replace(/_/g, ' '), keys: [] };
            entry.keys.push(k);
            g.set(prefix, entry);
        }
        return [...g.values()];
    };

    const fieldsView = (f: Form) => {
        const shown = (k: string) => matches(f.fields[k], k, filter, query);
        const tableShown = (rows: Record<string, Cell>[], name: string) => filter === 'all' && !query.trim()
            || rows.some(row => Object.entries(row).some(([c, cell]) => matches(cell, `${name}.${c}`, filter, query)));
        const anything = groups(f).some(g => g.keys.some(shown)) || Object.entries(f.tables).some(([n, rows]) => tableShown(rows, n));
        return (
            <>
                {f.remainder && <div className="banner banner--rest"><p>Everything else on these pages that the form’s template does not cover. Printed text that belongs to the form itself (phone numbers in a header, a legend) can appear here too; ignore it.</p></div>}
                {!f.remainder && <p className="provenance">{provenance(f)}</p>}
                {f.discovered && !f.remainder && (
                    <div className="banner">
                        <p>No template matched, so these fields were discovered from the page. {Object.values(f.fields).some(c => FLAGGED.has(c.status)) || Object.values(f.tables).some(rows => rows.some(r => Object.values(r).some(c => FLAGGED.has(c.status)))) ? 'Check the values marked “Check”, then save' : 'Save'} this as a document type to have the next file of this kind recognised, validated and named the same way every time.</p>
                        {saved[f.doc_index]
                            ? <p className="banner__ok">Saved as “{saved[f.doc_index]}”. New uploads of this kind will use it.</p>
                            : <button className="btn" onClick={async () => {
                                const title = window.prompt('Name this document type', f.label || '');
                                if (!title) return;
                                try { const r = await api.promote(wid, id, f.doc_index, title.trim()); reload(); setSaved(x => ({ ...x, [f.doc_index]: r.title })); }
                                catch (e) { setError((e as Error).message); }
                            }}>Save as document type</button>}
                    </div>)}
                {(() => {
                    const targets = [...groups(f).filter(g => g.keys.some(shown)).map(g => ({ id: sectionId(f.doc_index, g.title), title: g.title })),
                        ...Object.entries(f.tables).filter(([n, rows]) => tableShown(rows, n)).map(([n]) => ({ id: sectionId(f.doc_index, n), title: n === 'cpt' ? 'CPT / HCPCS services' : n.replace(/_/g, ' ') }))];
                    return targets.length > 4 ? (
                        <label className="jump">Jump to
                            <select value="" onChange={e => { scrollPaneTo(document.getElementById(e.target.value)); e.target.value = ''; }}>
                                <option value="">{targets.length} sections…</option>
                                {targets.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                            </select>
                        </label>) : null;
                })()}
                {!anything && <p className="empty">Nothing matches. {filter !== 'all' ? 'Try “All”.' : 'Try a different search.'}</p>}
                {groups(f).map(g => {
                    const keys = g.keys.filter(shown);
                    if (!keys.length) return null;
                    const flagged = g.keys.filter(k => FLAGGED.has(f.fields[k].status)).length;
                    return (
                        <details key={g.title} id={sectionId(f.doc_index, g.title)} className="section" open>
                            <summary><span className="section__title">{g.title}</span>
                                <span className={flagged ? 'section__count section__count--flag' : 'section__count'}>{flagged ? `${flagged} to check` : `${g.keys.length}`}</span></summary>
                            {keys.map(k => <FieldRow key={k} doc={f.doc_index} name={k} cell={f.fields[k]} selected={sel?.doc === f.doc_index && sel.key === k}
                                onSelect={() => select({ doc: f.doc_index, key: k }, f.fields[k])} onSave={v => save(f.doc_index, k, v)} onJump={() => jump(f.fields[k].page, f.fields[k].bbox)} />)}
                        </details>);
                })}
                {Object.entries(f.tables).map(([name, rows]) => tableShown(rows, name) && (
                    <details key={name} id={sectionId(f.doc_index, name)} className="section" open={rows.length <= 30 || rows.some(r => Object.values(r).some(c => FLAGGED.has(c.status)))}>
                        <summary><span className="section__title">{name === 'cpt' ? 'CPT / HCPCS services' : name.replace(/_/g, ' ')}</span>
                            {(() => { const n = rows.reduce((a, r) => a + Object.values(r).filter(c => FLAGGED.has(c.status)).length, 0);
                                return <span className={n ? 'section__count section__count--flag' : 'section__count'}>{n ? `${n} to check · ` : ''}{rows.length} {rows.length === 1 ? 'row' : 'rows'}</span>; })()}</summary>
                        <TableGrid doc={f.doc_index} name={name} rows={rows} columns={f.table_columns?.[name]}
                            selectedKey={sel?.doc === f.doc_index ? sel.key : null}
                            onSelect={(key, cell) => select({ doc: f.doc_index, key }, cell)} onSave={(key, v) => save(f.doc_index, key, v)} />
                    </details>))}
                {!f.discovered && !forms.some(x => x.remainder_of === f.doc_index) && !(data.fields?.rest_checked ?? []).includes(f.doc_index) && (
                    <div className="restbar">
                        <button className="btn" disabled={reading !== null} onClick={async () => {
                            setReading(f.doc_index);
                            try {
                                const out = await api.readRest(wid, id, f.doc_index);
                                if (!out.added) setRestNote(n => ({ ...n, [f.doc_index]: 'Nothing else was found on these pages.' }));
                                await load(); reload();
                            } catch (e) { setError((e as Error).message); }
                            finally { setReading(null); }
                        }}>{reading === f.doc_index ? 'Reading the pages' : 'Read the rest of these pages'}</button>
                        <span className="muted">Finds text, fields and tables around the form that its template does not cover. Uses model calls.</span>
                    </div>)}
                {restNote[f.doc_index] && <p className="muted">{restNote[f.doc_index]}</p>}
            </>
        );
    };

    /** Read the file again under another strategy, or send chosen pages to the vision models. Makes a second extraction. */
    const reread = async (body: { strategy?: string; pages?: number[] }) => {
        setRereading(true); setError('');
        try { const r = await api.reread(wid, id, body); reload(); nav(`/app/w/${wid}/e/${r.id}`); }
        catch (e) { setError((e as Error).message); }
        finally { setRereading(false); }
    };

    const panel = (
        <div className="panel">
            <header className="panel__head">
                <Link to={`/app/w/${wid}`} className="crumb">{workspace.name} / All documents</Link>
                <div className="panel__title">
                    <h1 title={data.filename}>{data.filename}</h1>
                    {done && (
                        <details className="menu">
                            <summary className="btn btn--tiny">Export</summary>
                            <div className="menu__list" onClick={e => (e.currentTarget.parentElement as HTMLDetailsElement).open = false}>
                                <button onClick={() => api.download(wid, id, 'fields', data.filename)}>fields.json</button>
                                <button onClick={() => api.download(wid, id, 'pages', data.filename)}>pages.json</button>
                                <button title="The values as they are now, including your edits, as an answer key for accuracy scoring" onClick={() => api.download(wid, id, 'truth', data.filename)}>Answer key</button>
                            </div>
                        </details>)}
                    {done && (data.stats?.scanned_pages ?? 0) > 0 && (
                        <details className="menu">
                            <summary className="btn btn--tiny" aria-disabled={rereading}>{rereading ? 'Starting…' : 'Read again'}</summary>
                            <div className="menu__list" onClick={e => (e.currentTarget.parentElement as HTMLDetailsElement).open = false}>
                                <small className="menu__note">Makes a second copy to compare. This one is kept.</small>
                                <button disabled={rereading} onClick={() => reread({ strategy: 'economy' })}>Economy: local OCR only, free</button>
                                <button disabled={rereading} onClick={() => reread({ strategy: 'balanced' })}>Balanced: models only if doubtful</button>
                                <button disabled={rereading} onClick={() => reread({ strategy: 'accuracy' })}>Accuracy: two vision models on every scan</button>
                            </div>
                        </details>)}
                </div>
                {done && (
                    <div className="tally" role="status">
                        <span className="tally__item"><b>{tally.verified}</b> verified</span>
                        <span className={queue.length ? 'tally__item tally__item--flag' : 'tally__item'}><b>{queue.length}</b> to check</span>
                        <span className={errors ? 'tally__item tally__item--flag' : 'tally__item'}><b>{errors}</b> {errors === 1 ? 'error' : 'errors'}</span>
                    </div>)}
                {done && data.stats && <p className="readline">{readLine(data.stats)}</p>}
            </header>
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            {!done ? (
                data.status === 'failed' ? <p className="notice notice--error" role="alert">{data.error}</p> :
                    <p className="notice" role="status">{data.stage === 'preparing' ? 'Preparing the pages: adding a text layer to scans.' : data.stage === 'documents' ? 'Extracting fields from each document.' : data.stage === 'rest' ? 'Reading the rest of each page.' : `Reading page ${data.progress.done} of ${data.progress.total || '…'}.`} This view updates when it finishes.</p>
            ) : (
                <>
                    <div className="tabs" role="tablist">
                        {([['fields', 'Fields'], ['pages', 'Pages'], ['findings', `Findings${warnings ? ` (${warnings})` : ''}`], ['json', 'JSON']] as [Tab, string][]).map(([t, label]) => (
                            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab tab--on' : 'tab'} onClick={() => setTab(t)}>{label}</button>))}
                    </div>

                    {tab === 'fields' && forms.length > 0 && (
                        <div className="fieldsbar">
                            {forms.length > 1 && (
                                <div className="docs" role="tablist" aria-label="Documents in this file">
                                    {forms.map(f => (
                                        <button key={f.doc_index} role="tab" aria-selected={f.doc_index === activeIdx} className={f.doc_index === activeIdx ? 'doc doc--on' : 'doc'} onClick={() => openDoc(f)}>
                                            <span className="doc__name">{f.remainder ? f.label : formTitle(f)}</span>
                                            <span className="doc__meta">{pageRange(f.pages)}{toCheck.get(f.doc_index) ? <b className="doc__flag"> · {toCheck.get(f.doc_index)} to check</b> : ''}</span>
                                        </button>))}
                                </div>)}
                            <div className="filters">
                                <div className="seg" role="group" aria-label="Show">
                                    {FILTERS.map(([k, label]) => <button key={k} aria-pressed={filter === k} className={filter === k ? 'seg__on' : ''} onClick={() => setFilter(k)}>{label}</button>)}
                                </div>
                                <input className="search" type="search" placeholder="Find a field or value" aria-label="Find a field or value" value={query} onChange={e => setQuery(e.target.value)} />
                            </div>
                            {queue.length > 0 && (
                                <div className="stepper">
                                    <button className="btn btn--tiny" onClick={() => step(-1)} aria-label="Previous value to check">‹ Previous</button>
                                    <span className="stepper__pos">{at >= 0 ? `${at + 1} of ${queue.length} to check` : `${queue.length} to check`}</span>
                                    <button className="btn btn--tiny btn--primary" onClick={() => step(1)}>Next to check ›</button>
                                    <span className="stepper__keys muted"><kbd>j</kbd> <kbd>k</kbd> move, <kbd>Enter</kbd> confirms</span>
                                </div>)}
                        </div>)}

                    <div className="panel__body">
                        {tab === 'fields' && (forms.length === 0
                            ? <p className="empty">No fields were extracted from this file. That happens when the file is a scan or handwriting and no model is configured on this server, or when it holds only cover or blank pages. The Pages tab shows the text that was read.</p>
                            : active && fieldsView(active))}
                        {tab === 'pages' && data.pages?.documents.map(d => (
                            <section key={d.doc_index} className="group"><h2 className="legend">{d.label} <span className="muted">pages {d.pages.join(', ')}</span></h2>
                                {d.route && <p className="route"><b>{EXTRACT_LABEL[d.route.extractor ?? ''] ?? d.route.extractor}</b>. {d.route.reasons[0]}.</p>}
                                {d.pages.map(n => {
                                    const p = data.pages!.pages.find(x => x.page === n)!;
                                    const flagged = p.lines.filter(l => l.status === 'review');
                                    return (
                                        <details key={n} className="pagecard" onToggle={e => (e.currentTarget as HTMLDetailsElement).open && jump(n)}>
                                            <summary><b>Page {n}</b> {p.classification.label}
                                                <span className={p.verified ? 'tag' : 'tag tag--flag'}>{p.verified ? 'verified' : 'unverified'}</span>
                                                {p.handwritten && <span className="tag tag--hand">handwriting</span>}</summary>
                                            <p className="route">Read by <b>{READER_LABEL[p.route?.reader ?? ''] ?? p.source}</b>: {p.route?.reasons.join('; ')}.</p>
                                            {p.reading && (p.reading.engine === 'vision' || p.reading.engine === 'tesseract' || p.reading.engine === 'rapidocr' || p.reading.engine === 'paddleocr' || p.reading.engine === 'doctr') && (
                                                <p className="route">
                                                    {p.reading.escalated
                                                        ? <>Local OCR{p.reading.local_confidence != null ? ` (${Math.round(p.reading.local_confidence * 100)}% sure)` : ''} was not enough, so <b>vision models</b> read this page.</>
                                                        : p.reading.engine === 'vision' ? <>Read by <b>vision models</b>{p.reading.models?.length ? `: ${p.reading.models.join(' and ')}` : ''}.</>
                                                            : <>Read by <b>{p.reading.engine}</b>{p.reading.confidence != null ? `, ${Math.round(p.reading.confidence * 100)}% sure` : ''}{p.reading.agreement != null ? `, ${Math.round(p.reading.agreement * 100)}% agreement with a second engine` : ''}.</>}
                                                    {(p.reading.reasons ?? []).length > 0 && <> Why: {p.reading.reasons!.join('; ')}.</>}
                                                </p>)}
                                            {p.scanned && p.source !== 'ocr' && !p.error && <button className="btn btn--tiny" disabled={rereading} onClick={() => reread({ pages: [n] })}>Read this page with vision models</button>}
                                            {p.error && <p className="field__alt">This page could not be read: {p.error}</p>}
                                            {flagged.map((l, i) => <p key={i} className="field__alt">{l.text}{l.alternatives.length ? ` (second reader: ${l.alternatives.join(' / ')})` : ''}</p>)}
                                        </details>);
                                })}
                            </section>))}
                        {tab === 'findings' && (findings.length === 0 ? <p className="empty">No findings. Every rule passed.</p> :
                            findings.map((f, i) => (
                                <button key={i} className={`finding finding--${f.severity}`} onClick={() => findingJump(f)}>
                                    <span className="finding__sev">{f.severity === 'error' ? 'Error' : f.severity === 'warn' ? 'Warning' : 'Note'}</span>
                                    <span>{f.detail}</span>
                                </button>)))}
                        {tab === 'json' && <JsonView fields={data.fields} pages={data.pages} onDownload={kind => api.download(wid, id, kind, data.filename)} />}
                    </div>
                </>
            )}
        </div>
    );

    return <Split className="review" left={<PdfPane url={api.pdfUrl(wid, id)} headers={headers} overlays={overlays} viewerRef={viewer} visible={visible} onVisiblePage={setVisible} onError={setError} />} right={panel} />;
}
