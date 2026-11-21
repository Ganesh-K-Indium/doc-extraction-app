import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { meta } from '../api';
import { APP_NAME } from '../brand';
import { ThemeToggle } from './ThemeToggle';

export default function Shell() {
    const [health, setHealth] = useState<'checking' | 'full' | 'private' | 'local' | 'limited' | 'offline'>('checking');
    useEffect(() => {
        meta.health().then(h => setHealth(h.local_only ? 'private' : h.llm ? 'full' : (h.local_engines?.length || h.tesseract) ? 'local' : 'limited')).catch(() => setHealth('offline'));
    }, []);
    const label = { checking: 'Checking server', full: 'Models on', private: 'Local only', local: 'Digital PDFs + local OCR', limited: 'Digital PDFs only', offline: 'Server offline' }[health];
    return (
        <div className="app">
            <header className="topbar">
                <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                <span className={`health health--${health}`} title={{ full: 'Digital PDFs are read by code. Scans are read by local OCR, and by vision models when that is not enough.', private: 'Local-only mode: nothing leaves this server. Digital PDFs are read by code, scans by local OCR and any models on your own hardware.', local: 'No vision model is connected: digital PDFs are read in full and scans by local OCR. Connect a provider in Settings for handwriting and poor scans.', limited: 'No vision model and no local OCR engine: digital PDFs are read in full, scanned pages are not.', checking: undefined, offline: undefined }[health]}><span className="health__text">{label}</span></span>
                <NavLink to="/app" end className="topbar__link">Workspaces</NavLink>
                <NavLink to="/app/settings" className="topbar__link">Settings</NavLink>
                <ThemeToggle />
            </header>
            <Outlet />
        </div>
    );
}
