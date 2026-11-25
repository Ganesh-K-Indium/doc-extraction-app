import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useMatch, useNavigate } from 'react-router-dom';
import { meta, workspaces, type Workspace } from '../api';
import { APP_NAME } from '../brand';
import { Icon } from './Icon';
import { ThemeToggle } from './ThemeToggle';

const FOLD = 'pagewise.sideFolded';
const folded = () => { try { return window.localStorage.getItem(FOLD) === '1'; } catch { return false; } };

type Health = 'checking' | 'full' | 'private' | 'local' | 'limited' | 'offline';
const HEALTH_LABEL: Record<Health, string> = { checking: 'Checking server', full: 'Models on', private: 'Local only', local: 'Digital PDFs + local OCR', limited: 'Digital PDFs only', offline: 'Server offline' };
const HEALTH_TIP: Partial<Record<Health, string>> = {
    full: 'Digital PDFs are read by code. Scans are read by local OCR, and by vision models when that is not enough.',
    private: 'Local-only mode: nothing leaves this server. Digital PDFs are read by code, scans by local OCR and any models on your own hardware.',
    local: 'No vision model is connected: digital PDFs are read in full and scans by local OCR. Connect a provider in Settings for handwriting and poor scans.',
    limited: 'No vision model and no local OCR engine: digital PDFs are read in full, scanned pages are not.',
};

/** The app frame: a navigation rail down the left, the page in the rest. The rail folds to icons to give a page more room,
 *  and does so by itself while a document is being reviewed. On a phone it is a drawer. */
export default function Shell() {
    const [health, setHealth] = useState<Health>('checking');
    const [fold, setFold] = useState(folded);
    const [open, setOpen] = useState(false);
    const [spaces, setSpaces] = useState<Workspace[]>([]);
    const nav = useNavigate();
    const wid = useMatch('/app/w/:wid/*')?.params.wid ?? '';
    const inReview = !!useMatch('/app/w/:wid/e/:id');
    const rail = fold || inReview;

    useEffect(() => {
        meta.health().then(h => setHealth(h.local_only ? 'private' : h.llm ? 'full' : (h.local_engines?.length || h.tesseract) ? 'local' : 'limited')).catch(() => setHealth('offline'));
    }, []);
    useEffect(() => { workspaces.list().then(setSpaces).catch(() => undefined); }, [wid]);
    useEffect(() => {
        if (!open) return;
        const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
        window.addEventListener('keydown', esc);
        return () => window.removeEventListener('keydown', esc);
    }, [open]);

    const toggleFold = () => setFold(f => { try { window.localStorage.setItem(FOLD, f ? '0' : '1'); } catch { /* storage unavailable */ } return !f; });
    const current = spaces.find(w => w.id === wid);
    const item = (to: string, icon: Parameters<typeof Icon>[0]['name'], label: string, end = false) => (
        <NavLink to={to} end={end} className="side__link" title={rail ? label : undefined}>
            <Icon name={icon} /><span className="side__label">{label}</span>
        </NavLink>
    );

    return (
        <div className={`app${rail ? ' app--rail' : ''}${open ? ' app--drawer' : ''}`}>
            <div className="mbar">
                <button type="button" className="iconbtn" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Icon name="menu" /></button>
                <Link to="/" className="brand"><span className="brand__mark" aria-hidden="true" />{APP_NAME}</Link>
            </div>
            <button type="button" className="scrim" aria-label="Close menu" tabIndex={-1} onClick={() => setOpen(false)} />
            <aside className="side" aria-label="Navigation" onClick={e => { if ((e.target as HTMLElement).closest('a')) setOpen(false); }}>
                <div className="side__top">
                    <Link to="/" className="brand" title={rail ? APP_NAME : undefined}><span className="brand__mark" aria-hidden="true" /><span className="side__label">{APP_NAME}</span></Link>
                    <button type="button" className="iconbtn side__fold" onClick={toggleFold} disabled={inReview} aria-label={rail ? 'Expand the menu' : 'Fold the menu'} title={inReview ? 'The menu is folded while you review' : rail ? 'Expand the menu' : 'Fold the menu'}>
                        <span className={rail ? 'ficon turn' : 'ficon'}><Icon name="chevron" size={18} /></span>
                    </button>
                    <button type="button" className="iconbtn side__close" aria-label="Close menu" onClick={() => setOpen(false)}><Icon name="close" /></button>
                </div>
                <nav className="side__nav">
                    {item('/app', 'workspaces', 'Workspaces', true)}
                    {wid && (
                        <div className="side__group" role="group" aria-label="This workspace">
                            <label className="side__switch">
                                <span className="side__cap">Workspace</span>
                                <select value={wid} onChange={e => { setOpen(false); if (e.target.value === '__all') nav('/app'); else nav(`/app/w/${e.target.value}`); }} aria-label="Switch workspace">
                                    {spaces.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
                                    {!current && <option value={wid}>Current workspace</option>}
                                    <option value="__all">All workspaces…</option>
                                </select>
                            </label>
                            {item(`/app/w/${wid}`, 'documents', 'Documents', true)}
                            {item(`/app/w/${wid}/types`, 'types', 'Document types')}
                            {item(`/app/w/${wid}/reading`, 'engines', 'Reading engines')}
                        </div>)}
                </nav>
                <div className="side__foot">
                    {item('/app/settings', 'settings', 'Settings')}
                    <div className="side__meta">
                        <span className={`health health--${health}`} title={HEALTH_TIP[health] ?? HEALTH_LABEL[health]}><span className="side__label">{HEALTH_LABEL[health]}</span></span>
                        <ThemeToggle />
                    </div>
                </div>
            </aside>
            <div className="main"><Outlet /></div>
        </div>
    );
}
