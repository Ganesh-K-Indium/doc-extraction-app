import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api, meta, type RegistryType, type Summary } from '../api';
import { Suggestions } from '../components/Suggestions';
import { useWorkspace } from '../workspaceContext';

const STATE_LABEL: Record<Summary['status'], string> = { queued: 'Waiting', processing: 'Reading', done: 'Ready to review', failed: 'Failed' };
type View = 'all' | 'check' | 'working' | 'failed' | 'clean';
type Sort = 'new' | 'check' | 'name';
const VIEWS: [View, string][] = [['all', 'All'], ['check', 'To check'], ['working', 'Reading'], ['failed', 'Failed'], ['clean', 'Clean']];
const PAGE = 50;

const toCheck = (x: Summary) => (x.stats ? x.stats.needs_review + x.stats.errors : 0);
const inView = (x: Summary, v: View) =>
    v === 'all' || (v === 'check' && x.status === 'done' && toCheck(x) > 0) || (v === 'working' && (x.status === 'queued' || x.status === 'processing'))
    || (v === 'failed' && x.status === 'failed') || (v === 'clean' && x.status === 'done' && !!x.stats && toCheck(x) === 0);

/** How a file was read, in plain words: code reads digital pages, models read scans and handwriting. */
function ReadBy({ x }: { x: Summary }) {
    const s = x.stats;
    if (!s || s.digital_pages === undefined) return null;
    return (
        <span className="kinds">
            {s.digital_pages > 0 && <span className="kind kind--digital" title="Real text in the PDF: read directly by code, exactly">Digital{s.digital_pages !== s.pages ? ` ${s.digital_pages}` : ''}</span>}
            {s.local_ocr_pages !== undefined ? (
                <>
                    {s.local_ocr_pages > 0 && <span className="kind kind--scan" title="Pictures of pages read by a local OCR engine on this server">Local OCR{s.local_ocr_pages !== s.pages ? ` ${s.local_ocr_pages}` : ''}</span>}
                    {(s.vision_pages ?? 0) > 0 && <span className="kind kind--vision" title={`Read by vision models and compared${s.escalated_pages ? `; ${s.escalated_pages} of them were sent on because local OCR was doubtful` : ''}`}>Vision{s.vision_pages !== s.pages ? ` ${s.vision_pages}` : ''}</span>}
                </>
            ) : (s.scanned_pages ?? 0) > 0 && <span className="kind kind--scan" title="Pictures of pages: read by vision models and compared">Scanned{s.scanned_pages !== s.pages ? ` ${s.scanned_pages}` : ''}</span>}
            {(s.handwritten_pages ?? 0) > 0 && <span className="kind kind--hand" title="A reader saw handwriting on these pages">Handwriting {s.handwritten_pages}</span>}
        </span>
    );
}

function ModelUse({ x }: { x: Summary }) {
    const u = x.stats?.usage;
    if (!u) return <span className="muted">{x.status === 'done' ? '–' : ''}</span>;
    if (u.calls === 0) return <span className="muted" title="Read entirely by code: no model was called">None</span>;
    const tip = Object.entries(u.by_stage).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v.toLocaleString()} tokens`).join('\n');
    return <span title={tip}>{u.tokens >= 1000 ? `${(u.tokens / 1000).toFixed(1)}k` : u.tokens} tokens</span>;
}

export default function ListPage() {
    const [items, setItems] = useState<Summary[] | null>(null);
    const [error, setError] = useState('');
    const [notes, setNotes] = useState<string[]>([]);
    const [busy, setBusy] = useState('');
    const [over, setOver] = useState(false);
    const [choice, setChoice] = useState('auto');
    const [readRest, setReadRest] = useState(false);
    const [scanReading, setScanReading] = useState('');
    const [types, setTypes] = useState<RegistryType[]>([]);
    const [llm, setLlm] = useState(true);
    const [view, setView] = useState<View>('all');
    const [sort, setSort] = useState<Sort>('new');
    const [query, setQuery] = useState('');
    const [shown, setShown] = useState(PAGE);
    const input = useRef<HTMLInputElement>(null);
    const nav = useNavigate();
    const { wid = '' } = useParams();
    const { reload } = useWorkspace();

    const loadTypes = useCallback(() => meta.registry(wid).then(r => setTypes(r.types.filter(t => t.template))).catch(() => undefined), [wid]);
    useEffect(() => { loadTypes(); }, [loadTypes]);
    useEffect(() => { meta.health().then(h => setLlm(h.llm)).catch(() => undefined); }, []);
    const load = useCallback(() => api.list(wid).then(setItems).catch(e => setError(e.message)), [wid]);
    useEffect(() => {
        load();
        const t = setInterval(() => { if (!document.hidden) load(); }, 3000);
        return () => clearInterval(t);
    }, [load]);
    const doneCount = items?.filter(x => x.status === 'done').length ?? 0;

    const upload = async (picked: FileList | File[] | null | undefined) => {
        const files = Array.from(picked ?? []).filter(f => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
        if (!files.length) { if (picked && Array.from(picked).length) setError('Only PDF files can be read.'); return; }
        setError(''); setNotes([]);
        const failed: string[] = [];
        let last = '';
        for (let i = 0; i < files.length; i++) {
            setBusy(files.length > 1 ? `Uploading ${i + 1} of ${files.length}` : 'Uploading');
            try { last = (await api.upload(wid, files[i], choice, readRest && choice !== 'discover', scanReading)).id; }
            catch (e) { failed.push(`${files[i].name}: ${(e as Error).message}`); }
        }
        setBusy(''); if (input.current) input.current.value = '';
        reload(); load();
        if (failed.length) setNotes(failed);
        if (files.length === 1 && last && !failed.length) nav(`/app/w/${wid}/e/${last}`);
    };

    const counts = useMemo(() => Object.fromEntries(VIEWS.map(([v]) => [v, (items ?? []).filter(x => inView(x, v)).length])) as Record<View, number>, [items]);
    const rows = useMemo(() => {
        const q = query.trim().toLowerCase();
        const list = (items ?? []).filter(x => inView(x, view) && (!q || `${x.filename} ${(x.labels ?? []).join(' ')}`.toLowerCase().includes(q)));
        if (sort === 'check') list.sort((a, b) => toCheck(b) - toCheck(a) || b.created_at.localeCompare(a.created_at));
        else if (sort === 'name') list.sort((a, b) => a.filename.localeCompare(b.filename, undefined, { numeric: true }));
        return list;
    }, [items, view, sort, query]);

    const hint = choice === 'auto' ? 'Known document types use their template; anything else is read without one.'
        : choice === 'discover' ? 'The whole file is read as one document, with no template.'
            : 'Every page is read with the template you picked. For a packet of several documents, use automatic detection.';

    return (
        <main className="list">
            <div className={over ? 'intake intake--over' : 'intake'}
                onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
                <div>
                    <h1>Extract data from any PDF</h1>
                    <p className="muted">Digital reports and statements, scans, faxes, forms, handwritten notes. Drop one file or many. You get page-by-page JSON, structured JSON for each document, and a short list of values to check. Digital pages are read directly from the PDF, so they cost no model calls. {hint}</p>
                </div>
                <div className="intake__actions">
                    <label className="intake__pick">Document type
                        <select value={choice} onChange={e => setChoice(e.target.value)}>
                            <option value="auto">Detect automatically</option>
                            {types.length > 0 && <optgroup label="Use a template">{types.map(t => <option key={t.type} value={t.type}>{t.label}{t.custom ? ' (yours)' : ''}</option>)}</optgroup>}
                            <option value="discover">Read without a template</option>
                        </select>
                    </label>
                    <label className="intake__pick">Scanned pages
                        <select value={scanReading} onChange={e => setScanReading(e.target.value)}>
                            <option value="">Workspace setting</option>
                            <option value="economy">Economy: local OCR only</option>
                            <option value="balanced">Balanced: models if doubtful</option>
                            <option value="accuracy">Accuracy: vision models</option>
                        </select>
                    </label>
                    <button className="btn btn--primary" disabled={!!busy} onClick={() => input.current?.click()}>{busy || 'Choose PDFs'}</button>
                    {choice !== 'discover' && (
                        <label className="intake__rest">
                            <input type="checkbox" checked={readRest} onChange={e => setReadRest(e.target.checked)} />
                            <span>Also structure the text around the form <span className="muted">(only for pages that match a template; extra model calls)</span></span>
                        </label>)}
                </div>
                <input ref={input} type="file" accept="application/pdf" multiple hidden onChange={e => upload(e.target.files)} />
            </div>
            {!llm && <p className="notice" role="status">No vision model is connected. Digital PDFs are read in full and scans by local OCR, but handwriting and poor scans need a model. <Link to="/app/settings">Connect a provider in Settings</Link>.</p>}
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            {notes.length > 0 && <div className="notice notice--error" role="alert"><b>{notes.length === 1 ? 'One file was not uploaded' : `${notes.length} files were not uploaded`}</b><ul>{notes.map(n => <li key={n}>{n}</li>)}</ul></div>}

            <Suggestions wid={wid} refreshKey={doneCount} onSaved={() => { reload(); loadTypes(); }} onError={setError} />

            {items === null ? <p className="muted">Loading documents</p> : items.length === 0 ? (
                <p className="empty">No documents in this workspace yet. Drop PDFs above to read their pages and fields.</p>
            ) : (
                <>
                    <div className="listbar">
                        <div className="seg" role="group" aria-label="Show">
                            {VIEWS.map(([v, label]) => <button key={v} aria-pressed={view === v} className={view === v ? 'seg__on' : ''} onClick={() => { setView(v); setShown(PAGE); }}>{label}{v !== 'all' && counts[v] > 0 ? ` ${counts[v]}` : ''}</button>)}
                        </div>
                        <input className="search" type="search" placeholder="Search by file name or type" aria-label="Search documents" value={query} onChange={e => { setQuery(e.target.value); setShown(PAGE); }} />
                        <label className="listbar__sort">Sort
                            <select value={sort} onChange={e => { setSort(e.target.value as Sort); setShown(PAGE); }}>
                                <option value="new">Newest</option><option value="check">Most to check</option><option value="name">Name</option>
                            </select>
                        </label>
                    </div>
                    {rows.length === 0 ? <p className="empty">No documents match. {view !== 'all' || query ? <button className="link" onClick={() => { setView('all'); setQuery(''); setShown(PAGE); }}>Show all</button> : null}</p> : (
                        <div className="tablewrap">
                            <table className="ledger">
                                <thead><tr><th scope="col">Document</th><th scope="col">State</th><th scope="col">Read as</th><th scope="col" className="num">Pages</th><th scope="col" className="num">To check</th><th scope="col" className="num">Errors</th><th scope="col" className="num">Model use</th><th scope="col">Uploaded</th><td /></tr></thead>
                                <tbody>{rows.slice(0, shown).map(x => (
                                    <tr key={x.id}>
                                        <th scope="row"><Link to={`/app/w/${wid}/e/${x.id}`}>{x.filename}</Link>{x.labels && x.labels.length > 0 && <small className="ledger__sub">{x.labels.join(' · ')}</small>}</th>
                                        <td><span className={`state state--${x.status}`} title={x.status === 'failed' ? x.error ?? undefined : undefined}>{STATE_LABEL[x.status]}{x.status === 'processing' && x.progress.total ? ` ${x.progress.done} of ${x.progress.total}` : ''}</span></td>
                                        <td><ReadBy x={x} /></td>
                                        <td className="num">{x.stats?.pages ?? ''}</td>
                                        <td className="num">{x.stats ? <span className={x.stats.needs_review ? 'flagtext' : ''}>{x.stats.needs_review}</span> : ''}</td>
                                        <td className="num">{x.stats ? <span className={x.stats.errors ? 'flagtext' : ''}>{x.stats.errors}</span> : ''}</td>
                                        <td className="num"><ModelUse x={x} /></td>
                                        <td className="muted">{new Date(x.created_at + 'Z').toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</td>
                                        <td><button className="btn btn--quiet" aria-label={`Delete ${x.filename}`}
                                            onClick={async () => { if (confirm(`Delete “${x.filename}” and its extraction? This cannot be undone.`)) { await api.remove(wid, x.id); load(); reload(); } }}>Delete</button></td>
                                    </tr>))}
                                </tbody>
                            </table>
                        </div>)}
                    {rows.length > shown && <p className="listmore"><button className="btn" onClick={() => setShown(n => n + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more</button> <span className="muted">{shown} of {rows.length}</span></p>}
                </>
            )}
        </main>
    );
}
