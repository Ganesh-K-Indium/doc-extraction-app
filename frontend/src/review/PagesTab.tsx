import type { BBox, Detail, Page } from '../api';
import { Blocks } from './Blocks';
import type { FigureTools } from './Blocks';
import { EXTRACT_LABEL, pageChips, readingSentence } from './text';

interface Props {
    pages: NonNullable<Detail['pages']>;
    busy: boolean;
    onOpen: (page: number) => void;
    onJump: (page: number, bbox?: BBox | null) => void;
    onReread: (page: number) => void;
    figures?: FigureTools;
    onReadAllFigures?: () => void;
}

/** Every page of the file as a card, grouped by document: a short line on how it was read, then what is on it, all open to read. */
export function PagesTab({ pages, busy, onOpen, onJump, onReread, figures, onReadAllFigures }: Props) {
    const byNum = new Map<number, Page>(pages.pages.map(p => [p.page, p]));
    const found = pages.pages.flatMap(p => (p.structure?.blocks ?? []).flatMap(b => b.type === 'figure' ? [{ page: p, block: b }] : []));
    const all = found.map(f => f.block);
    const unread = all.filter(b => !b.reading).length;
    return (
        <div className="rv-pages">
            {all.length > 0 && (
                <p className="rv-pfigures">
                    {all.length} {all.length === 1 ? 'figure' : 'figures'} found (charts, diagrams, drawings, pictures): found by code, read only when you ask.
                    {unread > 1 && onReadAllFigures && figures && (
                        <button type="button" className="link" disabled={!figures.canRead || !!figures.busy} onClick={onReadAllFigures}
                            title={figures.canRead ? `One model call for each of the ${unread} figures not yet read` : 'Needs a vision model: connect one on the Settings page'}>
                            {figures.busy === 'all' ? 'Reading…' : `Read all ${unread}`}
                        </button>)}
                    <span className="rv-pfigures__list">
                        {found.map(({ page: p, block: b }) => (
                            <button key={`${p.page}:${b.index}`} type="button" className="link" onClick={() => onJump(p.page, b.bbox && p.size
                                ? [b.bbox[0] * p.size.width, b.bbox[1] * p.size.height, b.bbox[2] * p.size.width, b.bbox[3] * p.size.height] : null)}>
                                p{p.page} · {(b.caption ?? b.reading?.title ?? b.kind ?? 'figure').slice(0, 48)}
                                {found.filter(f => f.page.page === p.page && (f.block.caption ?? f.block.kind) === (b.caption ?? b.kind)).length > 1 ? ` (#${b.index + 1})` : ''}
                            </button>))}
                    </span>
                </p>)}
            {pages.documents.map(d => (
                <section key={d.doc_index} className="rv-pgroup">
                    <h2 className="rv-pgroup__head">{d.label} <span className="muted">pages {d.pages.join(', ')}</span></h2>
                    {d.route && <p className="rv-pgroup__how">{EXTRACT_LABEL[d.route.extractor ?? ''] ?? d.route.extractor}. {d.route.reasons[0]}.</p>}
                    {d.pages.map(n => {
                        const p = byNum.get(n);
                        if (!p) return null;
                        const flagged = p.lines.filter(l => l.status === 'review');
                        return (
                            <article key={n} className="rp-card">
                                <header className="rp-card__head" onClick={() => onOpen(n)} title="Show this page">
                                    <span className="rp-card__n">Page {n}</span>
                                    <span className="rp-card__type">{p.classification.label}</span>
                                    <span className="rv-page__chips">{pageChips(p).map(c => <span key={c.label} className={`rv-chip rv-chip--${c.tone}`} title={c.title}>{c.label}</span>)}</span>
                                </header>
                                <p className="rp-card__how">
                                    {readingSentence(p)}
                                    {p.scanned && p.reading?.engine !== 'vision' && !p.error && (
                                        <button className="link" disabled={busy} onClick={() => onReread(n)}>Read with vision models</button>)}
                                </p>
                                {p.error && <p className="rv-page__err">This page could not be read: {p.error}</p>}
                                {flagged.length > 0 && (
                                    <div className="rp-card__unsure">
                                        <b>{flagged.length} {flagged.length === 1 ? 'line' : 'lines'} the reader was unsure of</b>
                                        <ul>{flagged.map((l, i) => <li key={i}>{l.text}{l.alternatives.length ? <span className="muted"> (other reading: {l.alternatives.join(' / ')})</span> : null}</li>)}</ul>
                                    </div>)}
                                <Blocks page={p} onJump={onJump} tools={figures} />
                            </article>);
                    })}
                </section>))}
        </div>
    );
}
