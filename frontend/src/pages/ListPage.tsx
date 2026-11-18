import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, meta, type RegistryType, type Summary } from '../api';

const STATE_LABEL: Record<Summary['status'], string> = { queued: 'Waiting', processing: 'Reading', done: 'Ready to review', failed: 'Failed' };

export default function ListPage() {
    const [items, setItems] = useState<Summary[] | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [over, setOver] = useState(false);
    const [choice, setChoice] = useState('auto');
    const [types, setTypes] = useState<RegistryType[]>([]);
    const input = useRef<HTMLInputElement>(null);
    const nav = useNavigate();

    useEffect(() => { meta.registry().then(r => setTypes(r.types.filter(t => t.template))).catch(() => undefined); }, []);
    const load = useCallback(() => api.list().then(setItems).catch(e => setError(e.message)), []);
    useEffect(() => {
        load();
        const t = setInterval(load, 3000);
        return () => clearInterval(t);
    }, [load]);

    const upload = async (file?: File) => {
        if (!file) return;
        setBusy(true); setError('');
        try { nav(`/app/e/${(await api.upload(file, choice)).id}`); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); if (input.current) input.current.value = ''; }
    };

    return (
        <main className="list">
            <div className={over ? 'intake intake--over' : 'intake'}
                onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={e => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}>
                <div>
                    <h1>Extract pages and form fields from a PDF</h1>
                    <p className="muted">Drop a form, a packet or a scan. You get page-by-page JSON, key–value JSON for each document, and a short list of values to check. {choice === 'auto' ? 'Known document types use their template; anything else is read without one.' : choice === 'discover' ? 'The whole file is read as one document, with no template.' : 'Every page is read with the template you picked. For a packet of several documents, use automatic detection.'}</p>
                </div>
                <div className="intake__actions">
                    <label className="intake__pick">Document type
                        <select value={choice} onChange={e => setChoice(e.target.value)}>
                            <option value="auto">Detect automatically</option>
                            {types.length > 0 && <optgroup label="Use a template">{types.map(t => <option key={t.type} value={t.type}>{t.label}{t.custom ? ' (yours)' : ''}</option>)}</optgroup>}
                            <option value="discover">Read without a template</option>
                        </select>
                    </label>
                    <button className="btn btn--primary" disabled={busy} onClick={() => input.current?.click()}>{busy ? 'Uploading' : 'Choose a PDF'}</button>
                </div>
                <input ref={input} type="file" accept="application/pdf" hidden onChange={e => upload(e.target.files?.[0])} />
            </div>
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            {items === null ? <p className="muted">Loading documents</p> : items.length === 0 ? (
                <p className="empty">No documents yet. Drop a PDF above to read its pages and fields.</p>
            ) : (
                <table className="ledger">
                    <thead><tr><th scope="col">Document</th><th scope="col">State</th><th scope="col" className="num">Pages</th><th scope="col" className="num">To check</th><th scope="col" className="num">Errors</th><th scope="col">Uploaded</th><td /></tr></thead>
                    <tbody>{items.map(x => (
                        <tr key={x.id}>
                            <th scope="row"><Link to={`/app/e/${x.id}`}>{x.filename}</Link></th>
                            <td><span className={`state state--${x.status}`}>{STATE_LABEL[x.status]}{x.status === 'processing' && x.progress.total ? ` ${x.progress.done} of ${x.progress.total}` : ''}</span></td>
                            <td className="num">{x.stats?.pages ?? ''}</td>
                            <td className="num">{x.stats ? <span className={x.stats.needs_review ? 'flagtext' : ''}>{x.stats.needs_review}</span> : ''}</td>
                            <td className="num">{x.stats ? <span className={x.stats.errors ? 'flagtext' : ''}>{x.stats.errors}</span> : ''}</td>
                            <td className="muted">{new Date(x.created_at + 'Z').toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</td>
                            <td><button className="btn btn--quiet" aria-label={`Delete ${x.filename}`}
                                onClick={async () => { if (confirm(`Delete “${x.filename}” and its extraction? This cannot be undone.`)) { await api.remove(x.id); load(); } }}>Delete</button></td>
                        </tr>))}
                    </tbody>
                </table>
            )}
        </main>
    );
}
