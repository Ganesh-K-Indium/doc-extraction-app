import type { Detail, Page } from '../api';
import { EXTRACT_LABEL, pageChips, readingSentence } from './text';

interface Props {
    pages: NonNullable<Detail['pages']>;
    busy: boolean;
    onOpen: (page: number) => void;
    onReread: (page: number) => void;
}

/** Every page of the file, grouped by document: what it is, how it was read, and what is doubtful on it. */
export function PagesTab({ pages, busy, onOpen, onReread }: Props) {
    const byNum = new Map<number, Page>(pages.pages.map(p => [p.page, p]));
    return (
        <div className="rv-pages">
            {pages.documents.map(d => (
                <section key={d.doc_index} className="rv-pgroup">
                    <h2 className="rv-pgroup__head">{d.label} <span className="muted">pages {d.pages.join(', ')}</span></h2>
                    {d.route && <p className="rv-pgroup__how">{EXTRACT_LABEL[d.route.extractor ?? ''] ?? d.route.extractor}. {d.route.reasons[0]}.</p>}
                    <ul>
                        {d.pages.map(n => {
                            const p = byNum.get(n);
                            if (!p) return null;
                            const flagged = p.lines.filter(l => l.status === 'review');
                            return (
                                <li key={n}>
                                    <details className="rv-page" onToggle={e => (e.currentTarget as HTMLDetailsElement).open && onOpen(n)}>
                                        <summary>
                                            <span className="rv-page__n">{n}</span>
                                            <span className="rv-page__type">{p.classification.label}</span>
                                            <span className="rv-page__chips">{pageChips(p).map(c => <span key={c.label} className={`rv-chip rv-chip--${c.tone}`} title={c.title}>{c.label}</span>)}</span>
                                            {flagged.length > 0 && <span className="rv-page__flag">{flagged.length} unsure</span>}
                                        </summary>
                                        <div className="rv-page__body">
                                            <p>{readingSentence(p)}</p>
                                            {p.error && <p className="rv-page__err">This page could not be read: {p.error}</p>}
                                            {flagged.length > 0 && (
                                                <ul className="rv-page__lines">{flagged.map((l, i) => <li key={i}>{l.text}{l.alternatives.length ? <span className="muted"> (other reading: {l.alternatives.join(' / ')})</span> : null}</li>)}</ul>)}
                                            {p.scanned && p.reading?.engine !== 'vision' && !p.error && (
                                                <button className="btn btn--tiny" disabled={busy} onClick={() => onReread(n)}>Read this page with vision models</button>)}
                                        </div>
                                    </details>
                                </li>);
                        })}
                    </ul>
                </section>))}
        </div>
    );
}
