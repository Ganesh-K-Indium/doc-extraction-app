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

function Row({ w, onChanged }: { w: Workspace; onChanged: () => void }) {
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
        <tr>
            <th scope="row">
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
                    <>
                        <Link to={`/app/w/${w.id}`} className="wsname">{w.name}</Link>
                        {w.description && <span className="wsdesc">{w.description}</span>}
                        {error && <span className="notice notice--error" role="alert">{error}</span>}
                    </>
                )}
            </th>
            <td className="num">{w.documents}{w.processing > 0 && <span className="muted"> ({w.processing} reading)</span>}</td>
            <td className="num"><span className={w.to_check ? 'flagtext' : ''}>{w.to_check}</span></td>
            <td className="num"><span className={w.errors ? 'flagtext' : ''}>{w.errors}</span></td>
            <td className="muted">{timeAgo(w.last_activity)}</td>
            <td className="wsactions">
                {!editing && <button className="btn btn--quiet" aria-label={`Rename ${w.name}`} onClick={() => setEditing(true)}>Rename</button>}
                <button className="btn btn--quiet" aria-label={`Delete ${w.name}`} onClick={remove}>Delete</button>
            </td>
        </tr>
    );
}

export default function WorkspacesPage() {
    const [items, setItems] = useState<Workspace[] | null>(null);
    const [error, setError] = useState('');
    const nav = useNavigate();

    const load = useCallback(() => workspaces.list().then(w => { setItems(w); setError(''); }).catch(e => setError(e.message)), []);
    useEffect(() => { load(); }, [load]);

    const last = items?.find(w => w.id === getLastWorkspace());
    return (
        <main className="list">
            <h1 className="page-title">Workspaces</h1>
            <p className="lede">A workspace keeps its own documents and its own document types, so each project or client stays separate. Open one to upload files, of any kind and in any number, and review what was extracted.</p>
            {error && <p className="notice notice--error" role="alert">{error}</p>}

            {items === null ? (!error && <p className="muted">Loading workspaces</p>) : items.length === 0 ? (
                <section className="wsempty" aria-label="Create your first workspace">
                    <h2>Create your first workspace</h2>
                    <p className="muted">Name it after the project, client or kind of paperwork it will hold. You can create more later and switch between them at any time.</p>
                    <CreateForm prominent onCreated={w => nav(`/app/w/${w.id}`)} />
                </section>
            ) : (
                <>
                    {last && (
                        <section className="wscontinue" aria-label="Continue where you left off">
                            <div>
                                <span className="wscontinue__label">Continue where you left off</span>
                                <h2>{last.name}</h2>
                                <p className="muted">{last.documents} document{last.documents === 1 ? '' : 's'}{last.to_check ? `, ${last.to_check} value${last.to_check === 1 ? '' : 's'} to check` : ''}. Last activity {timeAgo(last.last_activity)}.</p>
                            </div>
                            <Link className="btn btn--primary btn--lg" to={`/app/w/${last.id}`}>Open {last.name}</Link>
                        </section>
                    )}
                    <table className="ledger">
                        <thead><tr><th scope="col">Workspace</th><th scope="col" className="num">Documents</th><th scope="col" className="num">To check</th><th scope="col" className="num">Errors</th><th scope="col">Last activity</th><td /></tr></thead>
                        <tbody>{items.map(w => <Row key={w.id} w={w} onChanged={load} />)}</tbody>
                    </table>
                    <h2 className="section-title">New workspace</h2>
                    <CreateForm onCreated={w => nav(`/app/w/${w.id}`)} />
                </>
            )}
        </main>
    );
}
