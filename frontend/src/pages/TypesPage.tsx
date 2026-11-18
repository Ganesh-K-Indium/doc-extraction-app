import { useCallback, useEffect, useRef, useState } from 'react';
import { meta, templates, type DraftTemplate, type Registry } from '../api';

const EXTRACTOR: Record<string, string> = { template_form: 'Field template', kv: 'Label and value pairs', skip: 'Not extracted' };
const FIELD_TYPES = ['text', 'date', 'phone', 'number', 'currency', 'email', 'id', 'state', 'zip', 'tax_id', 'icd10', 'enum', 'multi_enum', 'checkbox'];

export default function TypesPage() {
    const [reg, setReg] = useState<Registry | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [draft, setDraft] = useState<DraftTemplate | null>(null);
    const input = useRef<HTMLInputElement>(null);

    const load = useCallback(() => meta.registry().then(setReg).catch(e => setError(e.message)), []);
    useEffect(() => { load(); }, [load]);

    const readBlank = async (file?: File) => {
        if (!file) return;
        setBusy(true); setError('');
        try { setDraft((await templates.draft(file)).template); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); if (input.current) input.current.value = ''; }
    };
    const edit = (si: number, fi: number, patch: Record<string, unknown>) =>
        setDraft(d => d && { ...d, sections: d.sections.map((s, i) => i !== si ? s : { ...s, fields: s.fields.map((f, j) => j !== fi ? f : { ...f, ...patch }) }) });
    const drop = (si: number, fi: number) =>
        setDraft(d => d && { ...d, sections: d.sections.map((s, i) => i !== si ? s : { ...s, fields: s.fields.filter((_, j) => j !== fi) }).filter(s => s.fields.length) });
    const save = async () => {
        if (!draft) return;
        setBusy(true); setError('');
        try { await templates.save(draft); setDraft(null); await load(); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };

    return (
        <main className="list">
            <h1 className="page-title">Document types</h1>
            <p className="lede">A known type is read against its template and validated. Anything else is read without one, and you can save the result as a type afterwards. To add a type before you have an example filled in, upload a blank copy of the form.</p>
            {error && <p className="notice notice--error" role="alert">{error}</p>}

            <div className="intake">
                <div><h2 className="section-title" style={{ margin: 0 }}>Add a type from a blank form</h2>
                    <p className="muted" style={{ margin: '4px 0 0' }}>Upload a scan or PDF with nothing filled in. The fields, types and required marks are read from it as a draft you can correct.</p></div>
                <button className="btn" disabled={busy} onClick={() => input.current?.click()}>{busy && !draft ? 'Reading the form' : 'Upload blank form'}</button>
                <input ref={input} type="file" accept="application/pdf" hidden onChange={e => readBlank(e.target.files?.[0])} />
            </div>

            {draft && (
                <section className="draft" aria-label="Draft template">
                    <div className="draft__head">
                        <label>Name<input type="text" value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
                        <span className="muted">{draft.sections.reduce((n, s) => n + s.fields.length, 0)} fields{draft.tables.length ? `, ${draft.tables.length} table${draft.tables.length === 1 ? '' : 's'}` : ''}</span>
                    </div>
                    <p className="hint">Check the required marks first: a printed star is easy to miss. Remove anything that is not a field to fill in.</p>
                    <table>
                        <thead><tr><th scope="col">Section</th><th scope="col">Field</th><th scope="col">Type</th><th scope="col">Required</th><td /></tr></thead>
                        <tbody>{draft.sections.flatMap((s, si) => s.fields.map((f, fi) => (
                            <tr key={f.key}>
                                <td className="muted">{s.header ?? ''}</td>
                                <td>{f.label}{f.options?.length ? <span className="muted"> ({f.options.join(', ')})</span> : null}</td>
                                <td><select aria-label={`Type of ${f.label}`} value={f.type} onChange={e => edit(si, fi, { type: e.target.value })}>{FIELD_TYPES.map(t => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</select></td>
                                <td><input type="checkbox" aria-label={`${f.label} is required`} checked={!!f.required} onChange={e => edit(si, fi, { required: e.target.checked })} /></td>
                                <td><button className="btn btn--quiet" aria-label={`Remove ${f.label}`} onClick={() => drop(si, fi)}>Remove</button></td>
                            </tr>)))}
                        </tbody>
                    </table>
                    {draft.tables.map(t => <p key={t.key} className="muted">Table “{t.header ?? t.key}”: {t.columns.map(c => c.label).join(', ')}</p>)}
                    <div className="draft__actions">
                        <button className="btn btn--primary" disabled={busy || !draft.title.trim()} onClick={save}>{busy ? 'Saving' : 'Save document type'}</button>
                        <button className="btn btn--quiet" onClick={() => setDraft(null)}>Discard draft</button>
                    </div>
                </section>
            )}

            {!reg ? !error && <p className="muted">Loading types</p> : (
                <>
                    <table className="ledger">
                        <thead><tr><th scope="col">Type</th><th scope="col">Extraction</th><th scope="col">Template</th><th scope="col" className="num">Fields</th><th scope="col" className="num">Required</th><td /></tr></thead>
                        <tbody>{reg.types.map(t => (
                            <tr key={t.type}>
                                <th scope="row">{t.label}{t.custom && <span className="tag--custom">yours</span>}</th>
                                <td>{EXTRACTOR[t.extractor] ?? t.extractor}</td>
                                <td className="muted">{t.template ?? 'None'}</td>
                                <td className="num">{t.template ? t.fields : ''}</td><td className="num">{t.template ? t.required : ''}</td>
                                <td>{t.custom && <button className="btn btn--quiet" aria-label={`Delete ${t.label}`}
                                    onClick={async () => { if (confirm(`Delete the “${t.label}” type? Files already extracted keep their results.`)) { await templates.remove(t.type); load(); } }}>Delete</button>}</td>
                            </tr>))}</tbody>
                    </table>
                    <h2 className="section-title">How text is read</h2>
                    <dl className="defs">{reg.readers.map(r => (<div key={r.id}><dt>{r.label}</dt><dd>{r.summary}</dd></div>))}</dl>
                </>
            )}
        </main>
    );
}
