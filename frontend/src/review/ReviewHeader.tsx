import { Link } from 'react-router-dom';
import type { Stats } from '../api';
import { Menu } from '../components/Menu';
import { readSummary } from './text';

interface Props {
    wid: string;
    filename: string;
    workspaceName: string;
    done: boolean;
    stats: Stats | null;
    engines?: string[];            // names of the local OCR engines that read pages
    verified: number;
    toCheck: number;
    errors: number;
    hasScans: boolean;
    busy: boolean;
    onShowCheck: () => void;
    onShowFindings: () => void;
    onReread: (strategy: string) => void;
    onDownload: (kind: 'fields' | 'pages' | 'structure' | 'truth') => void;
    onCsv: () => void;
    /** The next file in this workspace that still has something to check. */
    next?: { id: string; name: string; toCheck: number } | null;
}

/** Who this is, what is left to do, and the two things you may want to do with the file: export it, or read it again. */
export function ReviewHeader(p: Props) {
    return (
        <header className="rv-head">
            <nav className="rv-head__nav" aria-label="Back">
                <Link to={`/app/w/${p.wid}`} className="rv-head__back">← Back to documents</Link>
                <Link to="/app" className="rv-head__crumb">Workspaces</Link>
                <span aria-hidden="true">/</span>
                <Link to={`/app/w/${p.wid}`} className="rv-head__crumb">{p.workspaceName}</Link>
            </nav>
            <div className="rv-head__title">
                <h1 title={p.filename}>{p.filename}</h1>
                {p.done && (
                    <div className="rv-head__actions">
                        <Menu label="Export ▾">
                            <button onClick={() => p.onDownload('fields')}>fields.json<small>Values for each document</small></button>
                            <button onClick={() => p.onDownload('structure')}>structure.json<small>Headings, text, tables and lists in reading order</small></button>
                            <button onClick={() => p.onDownload('pages')}>pages.json<small>Text and layout of every page</small></button>
                            <button onClick={p.onCsv}>reviewed.csv<small>Every value and table cell, with your corrections, for a spreadsheet</small></button>
                            <button onClick={() => p.onDownload('truth')}>Answer key<small>Your reviewed values, for accuracy scoring</small></button>
                        </Menu>
                        {p.hasScans && (
                            <Menu label="Read again ▾" disabled={p.busy} title="Make a second copy read under another strategy, to compare">
                                <small className="menu__note">Makes a second copy to compare. This one is kept.</small>
                                <button onClick={() => p.onReread('economy')}>Economy<small>Local OCR only. Free.</small></button>
                                <button onClick={() => p.onReread('balanced')}>Balanced<small>Vision models only where doubtful</small></button>
                                <button onClick={() => p.onReread('accuracy')}>Accuracy<small>Two vision models on every scan</small></button>
                            </Menu>)}
                    </div>)}
            </div>
            {p.done && (
                <>
                    <div className="rv-head__sum" role="status">
                        <span className="rv-stat rv-stat--ok"><b>{p.verified}</b> verified</span>
                        <button className={p.toCheck ? 'rv-stat rv-stat--flag' : 'rv-stat'} onClick={p.onShowCheck} disabled={!p.toCheck}><b>{p.toCheck}</b> to check</button>
                        <button className={p.errors ? 'rv-stat rv-stat--flag' : 'rv-stat'} onClick={p.onShowFindings} disabled={!p.errors}><b>{p.errors}</b> {p.errors === 1 ? 'error' : 'errors'}</button>
                    </div>
                    {p.next && <p className="rv-head__next"><Link to={`/app/w/${p.wid}/e/${p.next.id}`}>Next to review: {p.next.name} ({p.next.toCheck} to check) →</Link></p>}
                    {p.stats && <p className="rv-head__read" title="How the pages of this file were read">{readSummary(p.stats, p.engines)}</p>}
                </>)}
        </header>
    );
}
