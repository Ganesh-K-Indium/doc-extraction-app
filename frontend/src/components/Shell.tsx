import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { meta } from '../api';
import { APP_NAME } from '../brand';

export default function Shell() {
    const [health, setHealth] = useState<'checking' | 'full' | 'limited' | 'offline'>('checking');
    useEffect(() => {
        meta.health().then(h => setHealth(h.llm ? 'full' : 'limited')).catch(() => setHealth('offline'));
    }, []);
    const label = { checking: 'Checking server', full: 'Vision readers on', limited: 'Embedded text only', offline: 'Server offline' }[health];
    return (
        <div className="app">
            <header className="topbar">
                <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                <nav className="topnav" aria-label="Workspace">
                    <NavLink to="/app" end>Documents</NavLink>
                    <NavLink to="/app/types">Document types</NavLink>
                </nav>
                <span className={`health health--${health}`} title={health === 'limited' ? 'No OPENAI_API_KEY is set, so scanned pages are not transcribed.' : undefined}>{label}</span>
            </header>
            <Outlet />
        </div>
    );
}
