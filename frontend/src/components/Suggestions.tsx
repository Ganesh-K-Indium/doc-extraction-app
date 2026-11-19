import { useCallback, useEffect, useState } from 'react';
import { api, templates, type Suggestion } from '../api';

const keyOf = (wid: string, s: Suggestion) => `sugg:${wid}:${s.title ?? ''}:${s.fields.slice(0, 5).join(',')}`;
const wasDismissed = (k: string) => { try { return localStorage.getItem(k) === '1'; } catch { return false; } };

/** Layouts that keep recurring among a workspace's untemplated files, each one click from becoming a document type. */
export function Suggestions({ wid, refreshKey, limit = 3, onSaved, onError }: {
    wid: string; refreshKey?: number; limit?: number; onSaved: () => void; onError: (message: string) => void;
}) {
    const [items, setItems] = useState<Suggestion[]>([]);
    const load = useCallback(() => templates.suggestions(wid).then(s => setItems(s.filter(x => !wasDismissed(keyOf(wid, x))))).catch(() => undefined), [wid]);
    useEffect(() => { load(); }, [load, refreshKey]);

    const save = async (s: Suggestion) => {
        const name = window.prompt('Name this document type', s.title ?? '');
        if (!name?.trim()) return;
        try { await api.promote(wid, s.examples[0].extraction_id, s.examples[0].doc_index, name.trim()); onSaved(); load(); }
        catch (e) { onError((e as Error).message); }
    };
    const dismiss = (s: Suggestion) => {
        try { localStorage.setItem(keyOf(wid, s), '1'); } catch { /* private mode: it simply comes back */ }
        setItems(x => x.filter(y => y !== s));
    };
    if (!items.length) return null;
    return (
        <section className="suggest" aria-label="Recurring document types">
            <h2>Your files keep repeating a layout</h2>
            <p className="muted">Saving it as a document type makes the next file of this kind faster, validated and named the same way every time.</p>
            <ul>{items.slice(0, limit).map(s => (
                <li key={keyOf(wid, s)}>
                    <div>
                        <b>{s.title || 'Untitled layout'}</b> <span className="muted">in {s.count} files</span>
                        <div className="suggest__fields">
                            {s.fields.slice(0, 8).map(f => <span key={f} className="chip">{f.replace(/_/g, ' ')}</span>)}
                            {s.fields.length > 8 && <span className="muted"> +{s.fields.length - 8} more</span>}
                            {s.tables.length > 0 && <span className="chip">{s.tables.length} {s.tables.length === 1 ? 'table' : 'tables'}</span>}
                        </div>
                    </div>
                    <span className="suggest__act"><button className="btn" onClick={() => save(s)}>Save as document type</button><button className="btn btn--quiet" onClick={() => dismiss(s)}>Not now</button></span>
                </li>))}
            </ul>
        </section>
    );
}
