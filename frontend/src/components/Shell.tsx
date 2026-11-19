import { useEffect, useState } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { meta } from '../api';
import { APP_NAME } from '../brand';

export default function Shell() {
    const [health, setHealth] = useState<'checking' | 'full' | 'local' | 'limited' | 'offline'>('checking');
    useEffect(() => {
        meta.health().then(h => setHealth(h.llm ? 'full' : h.tesseract ? 'local' : 'limited')).catch(() => setHealth('offline'));
    }, []);
    const label = { checking: 'Checking server', full: 'Models on', local: 'Digital PDFs + local OCR', limited: 'Digital PDFs only', offline: 'Server offline' }[health];
    return (
        <div className="app">
            <header className="topbar">
                <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
                <span className={`health health--${health}`} title={health === 'full' ? 'Digital PDFs are read by code. Scans and handwriting are read by vision models.' : health === 'limited' ? 'No model key and no Tesseract: digital PDFs are read in full, scanned pages are not.' : health === 'local' ? 'No OPENAI_API_KEY: digital PDFs are read in full; scans are read by Tesseract on this machine, as a single unverified reader.' : undefined}>{label}</span>
            </header>
            <Outlet />
        </div>
    );
}
