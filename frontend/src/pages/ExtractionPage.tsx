import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, authHeaders, type BBox, type Cell, type Detail, type Finding, type Form } from '../api';
import { type Overlay, type PdfViewerHandle } from '../components/PdfViewer';
import { Split } from '../components/Split';
import { useWorkspace } from '../workspaceContext';
import { FieldsTab } from '../review/FieldsTab';
import { FindingsTab } from '../review/FindingsTab';
import { allCells, cellAt, FLAGGED, revealInPane, rowId, withEdit, type Filter, type QItem, type Value } from '../review/helpers';
import { JsonView } from '../review/JsonView';
import { PagesTab } from '../review/PagesTab';
import { PdfPane } from '../review/PdfPane';
import { ReviewHeader } from '../review/ReviewHeader';
import { StepBar } from '../review/StepBar';
import '../components/textLayer.css';

type Tab = 'fields' | 'pages' | 'findings' | 'json';

export default function ExtractionPage() {
    const { wid = '', id = '' } = useParams();
    const { workspace, reload } = useWorkspace();
    const [data, setData] = useState<Detail | null>(null);
    const [error, setError] = useState('');
    const [params, setParams] = useSearchParams();
    const asked = params.get('tab');
    const tab: Tab = asked === 'pages' || asked === 'findings' || asked === 'json' ? asked : 'fields';
    const setTab = useCallback((t: Tab) => setParams(p => { const n = new URLSearchParams(p); if (t === 'fields') n.delete('tab'); else n.set('tab', t); return n; }, { replace: true }), [setParams]);
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
    const engineNames = useMemo(() => {
        const label: Record<string, string> = { tesseract: 'Tesseract', rapidocr: 'RapidOCR', paddleocr: 'PaddleOCR', doctr: 'docTR' };
        const ids = (data?.pages?.pages ?? []).filter(pg => pg.source === 'ocr-local').map(pg => pg.reading?.engine).filter((e): e is string => !!e);
        return [...new Set(ids)].map(e => label[e] ?? e);
    }, [data]);
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
    const verified = useMemo(() => {
        let n = 0;
        for (const f of forms) for (const { cell } of allCells(f)) if (cell.status === 'agreed' || cell.status === 'corrected' || cell.status === 'single') n++;
        return n;
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
    const selectedValue = sel && at >= 0 ? cellAt(forms.find(f => f.doc_index === sel.doc), sel.key)?.value : undefined;
    const confirm = useCallback(() => { if (sel && selectedValue !== null && selectedValue !== undefined) save(sel.doc, sel.key, selectedValue as Value); }, [sel, selectedValue, save]);

    // j / k step through what needs checking; Enter confirms the current value.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            const t = e.target as HTMLElement;
            if (t.closest('input, textarea, select, [contenteditable]') || e.metaKey || e.ctrlKey || e.altKey || tab !== 'fields' || !queue.length) return;
            if (e.key === 'j' || e.key === 'k') { step(e.key === 'j' ? 1 : -1); e.preventDefault(); }
            else if (e.key === 'Enter' && sel && at >= 0 && selectedValue !== null && selectedValue !== undefined) { confirm(); e.preventDefault(); }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [queue, sel, at, tab, step, confirm, selectedValue]);

    const overlays: Overlay[] = highlight ? [{ page: highlight.page, rects: [highlight.bbox], kind: 'hl' }] : [];
    const findingJump = (f: Finding) => {
        const form = forms.find(x => x.doc_index === f.doc_index) || forms[0];
        const cell = f.field ? form?.fields[f.field] : undefined;
        if (cell && f.field) { setTab('fields'); select({ doc: form.doc_index, key: f.field }, cell); }
    };
    const openDoc = (f: Form) => { setActiveDoc(f.doc_index); setSel(null); viewer.current?.scrollToPage(f.pages[0], true); };

    const promote = async (f: Form) => {
        const title = window.prompt('Name this document type', f.label || '');
        if (!title) return;
        try { const r = await api.promote(wid, id, f.doc_index, title.trim()); reload(); setSaved(x => ({ ...x, [f.doc_index]: r.title })); }
        catch (e) { setError((e as Error).message); }
    };
    const readRest = async (f: Form) => {
        setReading(f.doc_index);
        try {
            const out = await api.readRest(wid, id, f.doc_index);
            if (!out.added) setRestNote(n => ({ ...n, [f.doc_index]: 'Nothing else was found on these pages.' }));
            await load(); reload();
        } catch (e) { setError((e as Error).message); }
        finally { setReading(null); }
    };
    /** Read the file again under another strategy, or send chosen pages to the vision models. Makes a second extraction. */
    const reread = async (body: { strategy?: string; pages?: number[] }) => {
        setRereading(true); setError('');
        try { const r = await api.reread(wid, id, body); reload(); nav(`/app/w/${wid}/e/${r.id}`); }
        catch (e) { setError((e as Error).message); }
        finally { setRereading(false); }
    };

    if (error && !data) return <main className="list"><p className="notice notice--error" role="alert">{error}</p><Link to={`/app/w/${wid}`}>Back to documents</Link></main>;
    if (!data) return <main className="list"><p className="muted">Loading document</p></main>;

    const done = data.status === 'done';
    const errors = findings.filter(f => f.severity === 'error').length;
    const warnings = findings.filter(f => f.severity !== 'info').length;
    const tabs: [Tab, string][] = [['fields', 'Review'], ['pages', 'Pages'], ['findings', warnings ? `Findings (${warnings})` : 'Findings'], ['json', 'JSON']];
    const showStep = done && tab === 'fields' && queue.length > 0;

    const panel = (
        <div className="panel">
            <ReviewHeader wid={wid} filename={data.filename} workspaceName={workspace.name} done={done} stats={data.stats} engines={engineNames} verified={verified} toCheck={queue.length} errors={errors}
                hasScans={(data.stats?.scanned_pages ?? 0) > 0} busy={rereading}
                onShowCheck={() => { setTab('fields'); setFilter('check'); setQuery(''); if (queue.length) select(queue[0], cellAt(forms.find(f => f.doc_index === queue[0].doc), queue[0].key)); }}
                onShowFindings={() => setTab('findings')} onReread={s => reread({ strategy: s })} onDownload={kind => api.download(wid, id, kind, data.filename)} />
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            {!done ? (
                data.status === 'failed' ? <p className="notice notice--error" role="alert">{data.error}</p> :
                    <p className="notice" role="status">{data.stage === 'preparing' ? 'Preparing the pages: adding a text layer to scans.' : data.stage === 'documents' ? 'Extracting fields from each document.' : data.stage === 'rest' ? 'Reading the rest of each page.' : `Reading page ${data.progress.done} of ${data.progress.total || '…'}.`} This view updates when it finishes.</p>
            ) : (
                <>
                    <div className="tabs" role="tablist">
                        {tabs.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'tab tab--on' : 'tab'} onClick={() => setTab(t)}>{label}</button>)}
                    </div>
                    <div className="panel__body">
                        {tab === 'fields' && (forms.length === 0
                            ? <p className="empty">No fields were extracted from this file. That happens when it is a scan or handwriting that no model could read, or when it holds only cover or blank pages. The Pages tab shows the text that was read; Read again can try a vision model.</p>
                            : <FieldsTab forms={forms} active={active} toCheck={toCheck} filter={filter} onFilter={setFilter} query={query} onQuery={setQuery} sel={sel}
                                restDone={f => forms.some(x => x.remainder_of === f.doc_index) || (data.fields?.rest_checked ?? []).includes(f.doc_index)}
                                readingDoc={reading} restNote={active ? restNote[active.doc_index] : undefined} savedAs={active ? saved[active.doc_index] : undefined}
                                onOpenDoc={openDoc} onSelect={select} onSave={save} onJump={jump} onPromote={promote} onReadRest={readRest} />)}
                        {tab === 'pages' && data.pages && <PagesTab pages={data.pages} busy={rereading} onOpen={n => jump(n)} onReread={n => reread({ pages: [n] })} />}
                        {tab === 'findings' && <FindingsTab findings={findings} onOpen={findingJump} />}
                        {tab === 'json' && <JsonView fields={data.fields} pages={data.pages} onDownload={kind => api.download(wid, id, kind, data.filename)} />}
                    </div>
                    {showStep && <StepBar position={at + 1} total={queue.length} canConfirm={at >= 0 && selectedValue !== null && selectedValue !== undefined} onStep={step} onConfirm={confirm} />}
                </>
            )}
        </div>
    );

    return <Split className="review" left={<PdfPane url={api.pdfUrl(wid, id)} headers={headers} overlays={overlays} viewerRef={viewer} visible={visible} onVisiblePage={setVisible} onError={setError} />} right={panel} />;
}
