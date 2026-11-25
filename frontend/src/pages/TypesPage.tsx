import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { meta, templates, type RegistryType, type Registry, type TemplateDoc, type TemplateField } from '../api';
import type { Overlay, PdfViewerHandle } from '../components/PdfViewer';
import { Split } from '../components/Split';
import { Suggestions } from '../components/Suggestions';
import { TemplateEditor } from '../components/TemplateEditor';
import { slugify } from '../lib/slug';
import { PdfPane } from '../review/PdfPane';
import { useWorkspace } from '../workspaceContext';

const EXTRACTOR: Record<string, string> = { template_form: 'Field template', kv: 'Label and value pairs', skip: 'Not extracted' };

type Mode = 'draft' | 'edit' | 'view' | 'copy';
interface Editing { template: TemplateDoc; mode: Mode; blobUrl?: string }

const MODE_NOTE: Record<Mode, string> = {
    draft: 'This is what was read from the blank form. Check it against the form on the left, correct anything wrong, then save.',
    edit: 'Changes apply to files you upload from now on. Documents already extracted keep their results.',
    view: 'This is a built-in type, so it is read-only. Make an editable copy to change it.',
    copy: 'A copy of a built-in type. Give it a name of your own, adjust it, then save.',
};

export default function TypesPage() {
    const [reg, setReg] = useState<Registry | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [editing, setEditing] = useState<Editing | null>(null);
    const [selectedKey, setSelectedKey] = useState<string | null>(null);
    const [highlight, setHighlight] = useState<{ page: number; bbox: [number, number, number, number] } | null>(null);
    const [visible, setVisible] = useState(1);
    const input = useRef<HTMLInputElement>(null);
    const viewer = useRef<PdfViewerHandle>(null);
    const { wid = '' } = useParams();
    const { reload, workspace } = useWorkspace();

    const load = useCallback(() => meta.registry(wid).then(setReg).catch(e => setError(e.message)), [wid]);
    useEffect(() => { load(); }, [load]);

    const close = () => {
        if (editing?.blobUrl) URL.revokeObjectURL(editing.blobUrl);
        setEditing(null); setSelectedKey(null); setHighlight(null); setError('');
    };
    const readBlank = async (file?: File) => {
        if (!file) return;
        setBusy(true); setError('');
        try { const { template } = await templates.draft(wid, file); setEditing({ template, mode: 'draft', blobUrl: URL.createObjectURL(file) }); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); if (input.current) input.current.value = ''; }
    };
    const open = async (t: RegistryType) => {
        setError('');
        try { const r = await templates.get(wid, t.type); setEditing({ template: r.template, mode: r.builtin ? 'view' : 'edit' }); }
        catch (e) { setError((e as Error).message); }
    };
    const save = async () => {
        if (!editing) return;
        setBusy(true); setError('');
        try {
            if (editing.mode === 'edit') await templates.replace(wid, editing.template);
            else await templates.save(wid, { ...editing.template, doc_type: slugify(editing.template.title) });
            close(); await load(); reload();
        } catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };
    const onSelectField = (f: TemplateField) => {
        setSelectedKey(f.key);
        if (f.bbox && f.page) { setHighlight({ page: f.page, bbox: f.bbox }); viewer.current?.scrollToRect(f.page, f.bbox); }
        else setHighlight(null);
    };

    if (editing) {
        const readOnly = editing.mode === 'view';
        const t = editing.template;
        const fieldCount = t.sections.reduce((n, s) => n + s.fields.length, 0);
        const overlays: Overlay[] = highlight ? [{ page: highlight.page, rects: [highlight.bbox], kind: 'hl' }] : [];
        const editor = (
            <div className="editor__panel">
                <p className="notice editor__note">{MODE_NOTE[editing.mode]}{editing.mode === 'draft' && ` It found ${fieldCount} field${fieldCount === 1 ? '' : 's'}${t.tables.length ? ` and ${t.tables.length} table${t.tables.length === 1 ? '' : 's'}` : ''}. Required marks are the easiest thing to get wrong: look for the printed star.`}</p>
                <TemplateEditor template={t} readOnly={readOnly} selectedKey={selectedKey} onSelectField={onSelectField} onChange={next => setEditing({ ...editing, template: next })} />
            </div>
        );
        return (
            <div className="editor">
                <header className="editor__head">
                    <button className="btn btn--quiet" onClick={close}>{readOnly ? 'Close' : 'Back without saving'}</button>
                    <h1>{t.title || 'Untitled document type'}</h1>
                    <span className="editor__actions">
                        {readOnly
                            ? <button className="btn btn--primary" onClick={() => setEditing({ template: { ...t, title: `${t.title} (copy)`, doc_type: '' }, mode: 'copy' })}>Make an editable copy</button>
                            : <button className="btn btn--primary" disabled={busy || !t.title.trim()} onClick={save}>{busy ? 'Saving' : editing.mode === 'edit' ? 'Save changes' : 'Save document type'}</button>}
                    </span>
                </header>
                {error && <p className="notice notice--error editor__err" role="alert">{error}</p>}
                {editing.blobUrl
                    ? <Split className="editor__split" left={<PdfPane url={editing.blobUrl} overlays={overlays} viewerRef={viewer} visible={visible} onVisiblePage={setVisible} onError={setError} />} right={editor} />
                    : <div className="editor__wide">{editor}</div>}
            </div>
        );
    }

    return (
        <main className="list">
            <header className="pagehead"><div className="pagehead__text"><p className="pagehead__eyebrow">{workspace.name}</p><h1 className="page-title">Document types</h1>
            <p className="lede">You never have to define a type first: files that match nothing are read without a template, and your files are watched for layouts that repeat. A known type is read against its template, validated, and named the same way every time. Save a reviewed result as a type, accept a suggestion below, or upload a blank form to draft one. Types you add belong to this workspace only; the built-in ones are available everywhere.</p></div></header>
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            <div className="types">
                <div className="types__main">
                    {!reg ? !error && <p className="muted">Loading types</p> : (
                        <div className="tablewrap">
                    <table className="ledger">
                        <thead><tr><th scope="col">Type</th><th scope="col">Extraction</th><th scope="col">Template</th><th scope="col" className="num">Fields</th><th scope="col" className="num">Required</th><td /></tr></thead>
                        <tbody>{reg.types.map(t => (
                            <tr key={t.type}>
                                <th scope="row">{t.label}{t.custom && <span className="tag--custom">yours</span>}</th>
                                <td>{EXTRACTOR[t.extractor] ?? t.extractor}</td>
                                <td className="muted">{t.template ?? 'None'}</td>
                                <td className="num">{t.template ? t.fields : ''}</td><td className="num">{t.template ? t.required : ''}</td>
                                <td className="wsactions">
                                    {t.template && <button className="btn btn--quiet" aria-label={`${t.custom ? 'Edit' : 'View'} ${t.label}`} onClick={() => open(t)}>{t.custom ? 'Edit' : 'View'}</button>}
                                    {t.custom && <button className="btn btn--quiet" aria-label={`Delete ${t.label}`}
                                        onClick={async () => { if (confirm(`Delete the “${t.label}” type? Files already extracted keep their results.`)) { await templates.remove(wid, t.type); load(); reload(); } }}>Delete</button>}
                                </td>
                            </tr>))}</tbody>
                    </table>
                        </div>
                    )}
                </div>
                <aside className="types__side">
            <Suggestions wid={wid} limit={5} onSaved={() => { load(); reload(); }} onError={setError} />

            <div className="intake">
                <div><h2 className="section-title" style={{ margin: 0 }}>Add a type from a blank form</h2>
                    <p className="muted" style={{ margin: '4px 0 0' }}>Upload a scan or PDF with nothing filled in. You then see what was found next to the form, and can correct, add or remove anything before saving.</p></div>
                <button className="btn" disabled={busy} onClick={() => input.current?.click()}>{busy ? 'Reading the form' : 'Upload blank form'}</button>
                <input ref={input} type="file" accept="application/pdf" hidden onChange={e => readBlank(e.target.files?.[0])} />
            </div>

                    {reg && <section className="card card__pad types__how">
                    <h2>How pages are read</h2>
                    <dl className="defs">{reg.readers.map(r => (<div key={r.id}><dt>{r.label}</dt><dd>{r.summary}</dd></div>))}</dl>
                    </section>}
                </aside>
            </div>
        </main>
    );
}
