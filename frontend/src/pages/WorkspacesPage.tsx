import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { workspaces, type Workspace } from '../api';
import { clearLastWorkspace, getLastWorkspace } from '../lib/lastWorkspace';
import { timeAgo } from '../lib/time';

function CreateForm({ onCreated, prominent }: { onCreated: (w: Workspace) => void; prominent?: boolean }) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [more, setMore] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim()) return;
        setBusy(true); setError('');
        try { onCreated(await workspaces.create(name.trim(), description.trim() || undefined)); setName(''); setDescription(''); setMore(false); }
        catch (err) { setError((err as Error).message); }
        finally { setBusy(false); }
    };
    return (
        <form className={prominent ? 'wscreate wscreate--hero' : 'wscreate'} onSubmit={submit}>
            <label className="wscreate__name">Workspace name
                <input type="text" value={name} maxLength={120} autoFocus={prominent} placeholder="For example, Acme vendor onboarding" onChange={e => setName(e.target.value)} />
            </label>
            <button className="btn btn--primary" type="submit" disabled={busy || !name.trim()}>{busy ? 'Creating' : 'Create workspace'}</button>
            {more
                ? <label className="wscreate__desc">What is it for? <span className="muted">(optional)</span>
                    <input type="text" value={description} maxLength={500} onChange={e => setDescription(e.target.value)} /></label>
                : <button type="button" className="link wscreate__more" onClick={() => setMore(true)}>Add a description</button>}
            {error && <p className="notice notice--error wscreate__err" role="alert">{error}</p>}
        </form>
    );
}

function Card({ w, onChanged, last }: { w: Workspace; onChanged: () => void; last: boolean }) {
    const [editing, setEditing] = useState(false);
    const [name, setName] = useState(w.name);
    const [description, setDescription] = useState(w.description);
    const [error, setError] = useState('');
    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        try { await workspaces.rename(w.id, name.trim(), description.trim()); setEditing(false); setError(''); onChanged(); }
        catch (err) { setError((err as Error).message); }
    };
    const remove = async () => {
        const what = `${w.documents} document${w.documents === 1 ? '' : 's'}${w.custom_types ? ` and ${w.custom_types} document type${w.custom_types === 1 ? '' : 's'}` : ''}`;
        if (!confirm(`Delete “${w.name}”? This permanently removes its ${what}, with their results. This cannot be undone.`)) return;
        try { await workspaces.remove(w.id); clearLastWorkspace(w.id); onChanged(); } catch (err) { setError((err as Error).message); }
    };
    return (
        <article className={last ? 'card wscard wscard--last' : 'card wscard'}>
            {editing ? (
                <form className="wsedit" onSubmit={save}>
                    <input aria-label="Workspace name" type="text" value={name} maxLength={120} onChange={e => setName(e.target.value)} autoFocus />
                    <input aria-label="Description" type="text" value={description} maxLength={500} placeholder="What is it for?" onChange={e => setDescription(e.target.value)} />
                    <span className="wsedit__actions">
                        <button className="btn btn--primary" type="submit" disabled={!name.trim()}>Save</button>
                        <button className="btn btn--quiet" type="button" onClick={() => { setEditing(false); setName(w.name); setDescription(w.description); setError(''); }}>Cancel</button>
                    </span>
                    {error && <span className="notice notice--error" role="alert">{error}</span>}
                </form>
            ) : (
                <div>
                    {last && <span className="wscard__chip">Last opened</span>}
                    <Link to={`/app/w/${w.id}`} className="wscard__name">{w.name}</Link>
                    {w.description && <p className="wscard__desc">{w.description}</p>}
                    {error && <span className="notice notice--error" role="alert">{error}</span>}
                </div>
            )}
            <dl className="wscard__stats">
                <div><dt>Documents</dt><dd>{w.documents}</dd></div>
                <div className={w.to_check ? 'is-flag' : ''}><dt>To check</dt><dd>{w.to_check}</dd></div>
                <div className={w.errors ? 'is-flag' : ''}><dt>Errors</dt><dd>{w.errors}</dd></div>
            </dl>
            <footer className="wscard__foot">
                <span>{w.processing > 0 ? `${w.processing} reading now` : `Active ${timeAgo(w.last_activity)}`}</span>
                <span>
                    {!editing && <button className="btn btn--quiet" aria-label={`Rename ${w.name}`} onClick={() => setEditing(true)}>Rename</button>}
                    <button className="btn btn--quiet" aria-label={`Delete ${w.name}`} onClick={remove}>Delete</button>
                </span>
            </footer>
        </article>
    );
}

export default function WorkspacesPage() {
    const [items, setItems] = useState<Workspace[] | null>(null);
    const [error, setError] = useState('');
    const nav = useNavigate();

    const load = useCallback(() => workspaces.list().then(w => { setItems(w); setError(''); }).catch(e => setError(e.message)), []);
    useEffect(() => { load(); }, [load]);

    const last = items?.find(w => w.id === getLastWorkspace());
    const ordered = items && last ? [last, ...items.filter(w => w.id !== last.id)] : items;
    const total = (k: 'documents' | 'to_check' | 'errors') => (items ?? []).reduce((n, w) => n + w[k], 0);
    return (
        <main className="list">
            <header className="pagehead">
                <div className="pagehead__text">
                    <h1 className="page-title">Workspaces</h1>
                    <p className="lede">Each project or client gets its own workspace, with its own documents and document types. Open one to upload files and review what was read.</p>
                </div>
                {items && items.length > 0 && (
                    <div className="kpis" aria-label="Across all workspaces">
                        <div className="kpi"><b>{items.length}</b><span>Workspaces</span></div>
                        <div className="kpi"><b>{total('documents')}</b><span>Documents</span></div>
                        <div className={total('to_check') ? 'kpi kpi--flag' : 'kpi'}><b>{total('to_check')}</b><span>To check</span></div>
                    </div>)}
            </header>
            {error && <p className="notice notice--error" role="alert" style={{ marginLeft: 0, marginRight: 0 }}>{error}</p>}

            {ordered === null ? (!error && <p className="muted">Loading workspaces</p>) : ordered.length === 0 ? (
                <section className="wsempty" aria-label="Create your first workspace">
                    <h2>Create your first workspace</h2>
                    <p className="muted">Name it after the project, client or kind of paperwork it will hold. You can create more later and switch between them at any time.</p>
                    <CreateForm prominent onCreated={w => nav(`/app/w/${w.id}`)} />
                </section>
            ) : (
                <div className="wsgrid">
                    {ordered.map(w => <Card key={w.id} w={w} last={w.id === last?.id} onChanged={load} />)}
                    <section className="card wscard wscard--new" aria-label="New workspace">
                        <h2>New workspace</h2>
                        <CreateForm onCreated={w => nav(`/app/w/${w.id}`)} />
                    </section>
                </div>
            )}
        </main>
    );
}
