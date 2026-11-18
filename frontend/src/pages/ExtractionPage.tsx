import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, authHeaders, type BBox, type Cell, type Detail, type Finding, type Form } from '../api';
import { PdfViewer, type Overlay, type PdfViewerHandle } from '../components/PdfViewer';
import '../components/textLayer.css';

type Tab = 'fields' | 'pages' | 'findings';
const SCALE = 1.1;
const FLAGGED = new Set(['review', 'undetermined']);

const display = (v: Cell['value']): string =>
    v === null || v === undefined ? '' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : Array.isArray(v) ? v.join(', ') : String(v);

/** What the reviewer sees for a field's state. */
function stateOf(c: Cell): { key: string; text: string } {
    if (c.status === 'corrected') return display(c.value as Cell['value']) === display(c.original as Cell['value']) ? { key: 'done', text: 'Confirmed' } : { key: 'done', text: 'Edited' };
    switch (c.status) {
        case 'agreed': return { key: 'done', text: c.method ? 'Read from checkbox' : 'Both readers agree' };
        case 'single': return { key: 'quiet', text: 'One reader' };
        case 'empty': return { key: 'quiet', text: 'Blank' };
        default: return { key: 'flag', text: c.status === 'undetermined' ? 'Could not read' : 'Check' };
    }
}

const Tick = () => <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5 4.8 9 10 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>;

interface QItem { doc: number; key: string }
const rowId = (doc: number, key: string) => `row-${doc}-${key.replace(/\W/g, '_')}`;

function FieldRow({ doc, name, cell, selected, onSelect, onSave }: {
    doc: number; name: string; cell: Cell; selected: boolean; onSelect: () => void; onSave: (v: string) => void;
}) {
    const [edit, setEdit] = useState<string | null>(null); // null = show the stored value
    const draft = edit ?? display(cell.value);
    const readOnly = typeof cell.value === 'boolean' || Array.isArray(cell.value);
    const st = stateOf(cell);
    return (
        <div id={rowId(doc, name)} className={`field field--${st.key}${selected ? ' field--on' : ''}`} onClick={onSelect}>
            <label className="field__label" htmlFor={`in-${doc}-${name}`}>{name.split('.').pop()?.replace(/_/g, ' ')}</label>
            <input id={`in-${doc}-${name}`} className="field__input" value={draft} readOnly={readOnly} onFocus={onSelect}
                onChange={e => setEdit(e.target.value)}
                onBlur={() => { if (draft !== display(cell.value)) onSave(draft); setEdit(null); }}
                onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { setEdit(null); e.currentTarget.blur(); } }} />
            <span className="field__state" title={cell.reason}>{st.key === 'done' && <Tick />}{st.text}</span>
            {cell.alternatives.length > 0 && (
                <span className="field__alt">The second reader saw{' '}
                    {cell.alternatives.map(a => <button key={a} className="link" onClick={e => { e.stopPropagation(); onSave(a); }}>use “{a}”</button>)}
                </span>)}
        </div>
    );
}

export default function ExtractionPage() {
    const { id = '' } = useParams();
    const [data, setData] = useState<Detail | null>(null);
    const [error, setError] = useState('');
    const [tab, setTab] = useState<Tab>('fields');
    const [highlight, setHighlight] = useState<{ page: number; bbox: BBox } | null>(null);
    const [visible, setVisible] = useState(1);
    const [sel, setSel] = useState<QItem | null>(null);
    const viewer = useRef<PdfViewerHandle>(null);
    const headers = useMemo(() => authHeaders(), []);

    const load = useCallback(() => api.get(id).then(setData).catch(e => setError(e.message)), [id]);
    useEffect(() => { load(); }, [load]);
    useEffect(() => {
        if (!data || data.status === 'done' || data.status === 'failed') return;
        const t = setInterval(load, 1500);
        return () => clearInterval(t);
    }, [data, load]);

    const forms = useMemo(() => data?.fields?.forms ?? [], [data]);
    const findings = useMemo(() => data?.fields?.validation ?? [], [data]);
    const cellOf = useCallback((q: QItem | null) => (q ? forms.find(f => f.doc_index === q.doc)?.fields[q.key] : undefined), [forms]);

    // Fields that need a human: unreadable / disagreeing readings, plus fields an error finding points at.
    const queue = useMemo<QItem[]>(() => {
        const out: QItem[] = [];
        for (const f of forms) for (const [key, c] of Object.entries(f.fields)) {
            const bad = FLAGGED.has(c.status) || findings.some(x => x.severity === 'error' && x.field === key && (x.doc_index ?? f.doc_index) === f.doc_index);
            if (bad && c.status !== 'corrected') out.push({ doc: f.doc_index, key });
        }
        return out;
    }, [forms, findings]);

    const tally = useMemo(() => {
        let verified = 0, blank = 0;
        for (const f of forms) for (const c of Object.values(f.fields)) {
            if (c.status === 'agreed' || c.status === 'corrected' || c.status === 'single') verified++;
            else if (c.status === 'empty') blank++;
        }
        return { verified, blank };
    }, [forms]);

    const jump = useCallback((page: number, bbox?: BBox | null) => {
        if (bbox) { setHighlight({ page, bbox }); viewer.current?.scrollToRect(page, bbox); }
        else { setHighlight(null); viewer.current?.scrollToPage(page, true); }
    }, []);
    const select = useCallback((q: QItem, cell?: Cell) => {
        setSel(q);
        if (cell) jump(cell.page, cell.bbox);
        document.getElementById(rowId(q.doc, q.key))?.scrollIntoView({ block: 'nearest' });
    }, [jump]);

    const save = useCallback(async (doc: number, key: string, value: string) => {
        try { await api.correct(id, doc, key, value); await load(); } catch (e) { setError((e as Error).message); }
    }, [id, load]);

    // j / k step through the review queue; Enter confirms the current value.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t.closest('input, textarea, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey || tab !== 'fields' || !queue.length) return;
            const at = sel ? queue.findIndex(q => q.doc === sel.doc && q.key === sel.key) : -1;
            if (e.key === 'j' || e.key === 'k') {
                const next = queue[(at + (e.key === 'j' ? 1 : -1) + queue.length) % queue.length];
                select(next, cellOf(next));
                e.preventDefault();
            } else if (e.key === 'Enter' && sel && at >= 0) {
                const c = cellOf(sel);
                if (c && typeof c.value === 'string') { save(sel.doc, sel.key, c.value); e.preventDefault(); }
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [queue, sel, tab, select, cellOf, save]);

    const overlays: Overlay[] = highlight ? [{ page: highlight.page, rects: [highlight.bbox], kind: 'hl' }] : [];
    const findingJump = (f: Finding) => {
        const form = forms.find(x => x.doc_index === f.doc_index) || forms[0];
        const cell = f.field ? form?.fields[f.field] : undefined;
        if (cell && f.field) { setTab('fields'); select({ doc: form.doc_index, key: f.field }, cell); }
    };

    if (error && !data) return <main className="list"><p className="notice notice--error" role="alert">{error}</p><Link to="/app">Back to documents</Link></main>;
    if (!data) return <main className="list"><p className="muted">Loading document</p></main>;

    const errors = findings.filter(f => f.severity === 'error').length;
    const sections = (f: Form) => {
        const g = new Map<string, string[]>();
        for (const k of Object.keys(f.fields)) g.set(k.includes('.') ? k.split('.')[0] : 'form', [...(g.get(k.includes('.') ? k.split('.')[0] : 'form') || []), k]);
        return [...g.entries()];
    };

    return (
        <div className="review">
            <section className="review__pdf" aria-label="Source document">
                <PdfViewer ref={viewer} url={api.pdfUrl(id)} headers={headers} scale={SCALE} overlays={overlays}
                    onPageCount={() => undefined} onVisiblePage={setVisible} onError={setError} />
            </section>
            <aside className="review__panel">
                <header className="panel__head">
                    <Link to="/app" className="crumb">All documents</Link>
                    <h1 title={data.filename}>{data.filename}</h1>
                    {data.status === 'done' && (
                        <div className="tally" role="status">
                            <span className="tally__item"><b>{tally.verified}</b> verified</span>
                            <span className={queue.length ? 'tally__item tally__item--flag' : 'tally__item'}><b>{queue.length}</b> to check</span>
                            <span className={errors ? 'tally__item tally__item--flag' : 'tally__item'}><b>{errors}</b> {errors === 1 ? 'error' : 'errors'}</span>
                            <span className="tally__page">Page {visible}</span>
                        </div>)}
                </header>
                {error && <p className="notice notice--error" role="alert">{error}</p>}
                {data.status !== 'done' ? (
                    data.status === 'failed' ? <p className="notice notice--error" role="alert">{data.error}</p> :
                        <p className="notice" role="status">Reading page {data.progress.done} of {data.progress.total || '…'}. This view updates when it finishes.</p>
                ) : (
                    <>
                        <div className="tabs" role="tablist">
                            {([['fields', 'Fields'], ['pages', 'Pages'], ['findings', `Findings${findings.filter(f => f.severity !== 'info').length ? ` (${findings.filter(f => f.severity !== 'info').length})` : ''}`]] as [Tab, string][]).map(([t, label]) => (
                                <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab tab--on' : 'tab'} onClick={() => setTab(t)}>{label}</button>))}
                            <span className="tabs__spacer" />
                            <button className="btn btn--quiet" onClick={() => api.download(id, 'pages', data.filename)}>Download pages JSON</button>
                            <button className="btn btn--quiet" onClick={() => api.download(id, 'fields', data.filename)}>Download fields JSON</button>
                        </div>
                        <div className="panel__body">
                            {tab === 'fields' && (forms.length === 0 ? <p className="empty">No form with a known template was found in this file. The Pages tab shows what was read.</p> : (
                                <>
                                    {queue.length > 0 && <p className="hint">Press <kbd>j</kbd> and <kbd>k</kbd> to move between the {queue.length} values to check, <kbd>Enter</kbd> to confirm one.</p>}
                                    {forms.map(f => (
                                        <div key={f.doc_index}>
                                            <h2 className="form-title">{f.template_id} <span className="muted">pages {f.pages.join(', ')}</span></h2>
                                            {sections(f).map(([g, keys]) => (
                                                <fieldset key={g} className="group"><legend>{g.replace(/_/g, ' ')}</legend>
                                                    {keys.map(k => <FieldRow key={k} doc={f.doc_index} name={k} cell={f.fields[k]}
                                                        selected={sel?.doc === f.doc_index && sel.key === k}
                                                        onSelect={() => select({ doc: f.doc_index, key: k }, f.fields[k])} onSave={v => save(f.doc_index, k, v)} />)}
                                                </fieldset>))}
                                            {Object.entries(f.tables).map(([name, rows]) => (
                                                <fieldset key={name} className="group"><legend>{name === 'cpt' ? 'CPT / HCPCS services' : name}</legend>
                                                    {rows.length === 0 ? <p className="empty">No rows were found.</p> : (
                                                        <table className="grid">
                                                            <thead><tr>{Object.keys(rows[0]).map(c => <th key={c} scope="col">{c}</th>)}</tr></thead>
                                                            <tbody>{rows.map((r, i) => <tr key={i}>{Object.entries(r).map(([c, cell]) => (
                                                                <td key={c} className={FLAGGED.has(cell.status) ? 'is-flag' : ''}>{display(cell.value)}
                                                                    {cell.alternatives.length > 0 && <div className="field__alt">second reader: {cell.alternatives.join(' / ')}</div>}</td>))}</tr>)}</tbody>
                                                        </table>)}
                                                </fieldset>))}
                                        </div>))}
                                </>))}
                            {tab === 'pages' && data.pages?.documents.map(d => (
                                <section key={d.doc_index} className="group"><legend className="legend">{d.label} <span className="muted">pages {d.pages.join(', ')}</span></legend>
                                    {d.route && <p className="route">Extracted as <b>{d.route.extractor?.replace('_', ' ')}</b>. {d.route.reasons[0]}.</p>}
                                    {d.pages.map(n => {
                                        const p = data.pages!.pages.find(x => x.page === n)!;
                                        const flagged = p.lines.filter(l => l.status === 'review');
                                        return (
                                            <details key={n} className="pagecard" onToggle={e => (e.currentTarget as HTMLDetailsElement).open && jump(n)}>
                                                <summary><b>Page {n}</b> {p.classification.label}
                                                    <span className={p.verified ? 'tag' : 'tag tag--flag'}>{p.verified ? 'verified' : 'unverified'}</span></summary>
                                                <p className="route">Read by <b>{p.route?.reader?.replace(/_/g, ' ') ?? p.source}</b>: {p.route?.reasons.join('; ')}.</p>
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
                        </div>
                    </>
                )}
            </aside>
        </div>
    );
}
