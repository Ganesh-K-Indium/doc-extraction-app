import { useCallback, useEffect, useState } from 'react';
import { Link, Outlet, useParams } from 'react-router-dom';
import { workspaces, type Workspace } from '../api';
import { clearLastWorkspace, setLastWorkspace } from '../lib/lastWorkspace';
import type { WorkspaceContext } from '../workspaceContext';

/** Everything under /app/w/:wid. Loads the workspace once, remembers it, and gives its pages a way to switch. */
export default function WorkspaceLayout() {
    const { wid = '' } = useParams();
    const [workspace, setWorkspace] = useState<Workspace | null>(null);
    const [error, setError] = useState('');

    const reload = useCallback(() => {
        workspaces.get(wid).then(w => { setWorkspace(w); setError(''); }).catch(e => setError(e.message));
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
    return <Outlet context={context} />;
}
