import { useCallback, useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useMatch, useNavigate, useParams } from 'react-router-dom';
import { workspaces, type Workspace } from '../api';
import { clearLastWorkspace, setLastWorkspace } from '../lib/lastWorkspace';
import type { WorkspaceContext } from '../workspaceContext';

/** Everything under /app/w/:wid. Loads the workspace once, remembers it, and gives its pages a way to switch. */
export default function WorkspaceLayout() {
    const { wid = '' } = useParams();
    const nav = useNavigate();
    const inReview = useMatch('/app/w/:wid/e/:id');
    const [workspace, setWorkspace] = useState<Workspace | null>(null);
    const [others, setOthers] = useState<Workspace[]>([]);
    const [error, setError] = useState('');

    const reload = useCallback(() => {
        workspaces.get(wid).then(w => { setWorkspace(w); setError(''); }).catch(e => setError(e.message));
        workspaces.list().then(setOthers).catch(() => undefined);
    }, [wid]);
    useEffect(() => { reload(); }, [reload]);
    // A workspace loaded for a previous URL is not this one: show nothing until the right one arrives.
    const current = workspace?.id === wid ? workspace : null;
    useEffect(() => { if (current) setLastWorkspace(current.id); }, [current]);
    useEffect(() => { if (error) clearLastWorkspace(wid); }, [error, wid]);

    if (error && !current) {
        return (
            <main className="list">
                <h1 className="page-title">This workspace is not available</h1>
                <p className="lede">It may have been deleted, or the link is wrong. {error}</p>
                <Link className="btn btn--primary" to="/app">Back to workspaces</Link>
            </main>
        );
    }
    if (!current) return <main className="list"><p className="muted">Opening workspace</p></main>;

    const context: WorkspaceContext = { workspace: current, reload };
    return (
        <>
            {!inReview && (
                <div className="wsbar">
                    <nav className="wsbar__crumb" aria-label="Workspace">
                        <Link to="/app">Workspaces</Link>
                        <span aria-hidden="true" className="wsbar__sep">/</span>
                        <label className="wsbar__switch">
                            <span className="sr-only">Switch workspace</span>
                            <select value={current.id} onChange={e => e.target.value === '__all' ? nav('/app') : nav(`/app/w/${e.target.value}`)}>
                                {others.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
                                {!others.some(w => w.id === current.id) && <option value={current.id}>{current.name}</option>}
                                <option value="__all">All workspaces…</option>
                            </select>
                        </label>
                    </nav>
                    <nav className="wsbar__tabs" aria-label="Workspace sections">
                        <NavLink to={`/app/w/${current.id}`} end>Documents</NavLink>
                        <NavLink to={`/app/w/${current.id}/types`}>Document types</NavLink>
                        <NavLink to={`/app/w/${current.id}/reading`}>Reading engines</NavLink>
                    </nav>
                </div>
            )}
            <Outlet context={context} />
        </>
    );
}
