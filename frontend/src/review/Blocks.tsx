import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Block, BBox, FigureReading, Page } from '../api';

const ENTITY_LABEL: Record<string, string> = { date: 'Dates', amount: 'Amounts', phone: 'Phones', email: 'Emails', url: 'Links', percent: 'Percentages' };

/** Where on the PDF a block sits. The structure keeps positions as fractions of the page; the viewer wants points. */
function toPoints(b: Block, page?: Page): BBox | null {
    if (!b.bbox || !page?.size) return null;
    const { width: w, height: h } = page.size;
    return [b.bbox[0] * w, b.bbox[1] * h, b.bbox[2] * w, b.bbox[3] * h];
}

/** What the figure cards need: which file they belong to, whether a model can read them, and what to do when someone asks. */
export interface FigureTools {
    wid: string; id: string; canRead: boolean; busy: string | null;
    onRead: (page: number, index: number, force?: boolean) => void;
}

const KIND_LABEL: Record<string, string> = { chart: 'Chart', diagram: 'Diagram', drawing: 'Drawing', photo: 'Photo', table: 'Table', logo: 'Logo', other: 'Figure' };

function FigureImage({ tools, page, index }: { tools: FigureTools; page: number; index: number }) {
    const [src, setSrc] = useState<string | null>(null);
    useEffect(() => {
        let url: string | null = null, live = true;
        api.figureImage(tools.wid, tools.id, page, index).then(u => { if (live) { url = u; setSrc(u); } else URL.revokeObjectURL(u); }).catch(() => undefined);
        return () => { live = false; if (url) URL.revokeObjectURL(url); };
    }, [tools.wid, tools.id, page, index]);
    return src ? <img className="rs-figure__img" src={src} alt="" /> : <div className="rs-figure__img rs-figure__img--wait" aria-hidden="true" />;
}

function ChartView({ chart }: { chart: NonNullable<FigureReading['chart']> }) {
    const unit = (a: { label: string | null; unit: string | null }) => [a.label, a.unit ? `(${a.unit})` : null].filter(Boolean).join(' ');
    return (
        <div className="rs-chart">
            <p className="rs-chart__axes">{chart.type} chart{unit(chart.x_axis) ? ` · x: ${unit(chart.x_axis)}` : ''}{unit(chart.y_axis) ? ` · y: ${unit(chart.y_axis)}` : ''}</p>
            {chart.series.map((s, i) => (
                <div className="rs-tablewrap" key={i}>
                    <table className="rs-table">
                        <thead><tr><th>{s.name ?? 'Series'}</th><th>{unit(chart.x_axis) || 'x'}</th><th>{unit(chart.y_axis) || 'y'}</th></tr></thead>
                        <tbody>{s.points.map((p, j) => (
                            <tr key={j}><td /><td>{p.x}</td><td>{p.estimated ? <span className="rs-est" title="Worked out from the picture, not printed on it">≈ {p.value ?? p.y}</span> : p.y}</td></tr>))}</tbody>
                    </table>
                </div>))}
        </div>);
}

function FigureView({ block, page, onJump, tools }: { block: Extract<Block, { type: 'figure' }>; page: Page; onJump: (page: number, bbox?: BBox | null) => void; tools?: FigureTools }) {
    const r = block.reading;
    const key = `${page.page}:${block.index}`;
    const working = tools?.busy === key || tools?.busy === 'all';
    const go = () => onJump(page.page, toPoints(block, page));
    const est = r?.chart ? r.chart.series.reduce((n, s) => n + s.points.filter(p => p.estimated).length, 0) : 0;
    return (
        <figure className="rs-figure">
            <div className="rs-figure__top" onClick={go}>
                <span className="rv-chip rv-chip--muted">{KIND_LABEL[block.kind ?? 'other'] ?? 'Figure'}</span>
                <figcaption>{block.caption ?? r?.title ?? `Figure on page ${page.page}`}</figcaption>
            </div>
            {tools && <FigureImage tools={tools} page={page.page} index={block.index} />}
            {!r && (
                <p className="rs-figure__ask">
                    {block.labels.length > 0 ? `${block.labels.length} labels are printed on it. ` : 'No text is printed on it. '}
                    {tools && (
                        <button type="button" className="link" disabled={!tools.canRead || working || !!tools.busy} onClick={() => tools.onRead(page.page, block.index)}
                            title={tools.canRead ? 'One model call for this figure' : 'Needs a vision model: connect one on the Settings page'}>
                            {working ? 'Reading…' : 'Read this figure'}
                        </button>)}
                </p>)}
            {r && block.decorative && <p className="muted">The model took this for a logo or decoration, so nothing was extracted from it.</p>}
            {r && !block.decorative && (
                <div className="rs-figure__read">
                    {r.summary && <p>{r.summary}</p>}
                    {r.chart && <ChartView chart={r.chart} />}
                    {r.components && <p className="rs-figure__parts"><b>Parts</b> {r.components.map(c => c.role ? `${c.name} (${c.role})` : c.name).join(' · ')}</p>}
                    {r.connections && <ul className="rs-figure__links">{r.connections.map((c, i) => <li key={i}>{c.from} → {c.to}{c.label ? ` (${c.label})` : ''}</li>)}</ul>}
                    {est > 0 && <p className="rs-figure__note">≈ marks values worked out from the picture{r.values_total ? `; ${r.values_confirmed ?? 0} of ${r.values_total} were found printed on it` : ''}. Treat them as estimates.</p>}
                    {r.limits && <p className="rs-figure__note">Not readable: {r.limits}</p>}
                    <p className="rs-figure__note">Read by {r.model ?? 'a model'}.{tools && <> <button type="button" className="link" disabled={!tools.canRead || !!tools.busy} onClick={() => tools.onRead(page.page, block.index, true)}>Read again</button></>}</p>
                </div>)}
        </figure>);
}

const ROWS_SHOWN = 12;

/** A table; a long one (a datasheet's electrical characteristics runs to dozens of rows) shows its first rows and the rest on request. */
function TableView({ block, onClick }: { block: Extract<Block, { type: 'table' }>; onClick: () => void }) {
    const [all, setAll] = useState(false);
    const rows = all ? block.rows : block.rows.slice(0, ROWS_SHOWN);
    return (
        <div className="rs-tablewrap" onClick={onClick}>
            <table className="rs-table">
                {block.header && <thead><tr>{block.columns.map((c, i) => <th key={i}>{c}</th>)}</tr></thead>}
                <tbody>{rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
            </table>
            {block.rows.length > ROWS_SHOWN && (
                <button type="button" className="rs-more" onClick={(e) => { e.stopPropagation(); setAll(!all); }}>
                    {all ? 'Show fewer rows' : `Show all ${block.rows.length} rows`}
                </button>)}
        </div>);
}

function BlockView({ block, page, onJump, after, tools }: { block: Block; page: Page; onJump: (page: number, bbox?: BBox | null) => void; after?: Block; tools?: FigureTools }) {
    const go = () => onJump(page.page, toPoints(block, page));
    switch (block.type) {
        case 'heading': {
            const Tag = (block.level === 1 ? 'h3' : block.level === 2 ? 'h4' : 'h5') as 'h3' | 'h4' | 'h5';
            return <Tag className={`rs-h rs-h${block.level}`} onClick={go}>{block.text}</Tag>;
        }
        case 'paragraph':
            return <p className="rs-p" onClick={go}>{block.text}</p>;
        case 'key_value':
            return (
                <dl className="rs-kv" onClick={go}>
                    {block.items.map((it, i) => <div key={i}><dt>{it.label}</dt><dd>{it.value ?? <span className="muted">blank</span>}</dd></div>)}
                </dl>);
        case 'table':
            return <TableView block={block} onClick={go} />;
        case 'checkboxes': {
            const groups: { group: string | null; items: typeof block.items }[] = [];
            for (const it of block.items) {
                const g = it.group ?? null;
                if (groups.length && groups[groups.length - 1].group === g) groups[groups.length - 1].items.push(it);
                else groups.push({ group: g, items: [it] });
            }
            return (
                <div className="rs-boxes" onClick={go}>
                    {groups.map((g, i) => (
                        <div key={i}>
                            {g.group && !(after?.type === 'paragraph' && after.text.startsWith(g.group.slice(0, 40))) && <p className="rs-boxes__q">{g.group}</p>}
                            <ul>{g.items.map((it, j) => <li key={j} className={it.checked ? 'is-on' : ''}><span aria-hidden="true">{it.checked ? '\u2612' : '\u2610'}</span><span className="sr-only">{it.checked ? 'Checked: ' : 'Not checked: '}</span>{it.label}</li>)}</ul>
                        </div>))}
                </div>);
        }
        case 'figure':
            return <FigureView block={block} page={page} onJump={onJump} tools={tools} />;
        case 'list': {
            const Tag = block.ordered ? 'ol' : 'ul';
            return <Tag className="rs-list" onClick={go}>{block.items.map((t, i) => <li key={i}>{t}</li>)}</Tag>;
        }
    }
}

function EntityList({ entities }: { entities: { type: string; value: string }[] }) {
    const groups = new Map<string, string[]>();
    for (const e of entities) groups.set(e.type, [...(groups.get(e.type) ?? []), e.value]);
    if (!groups.size) return null;
    return (
        <div className="rs-entities">
            {[...groups].map(([type, values]) => (
                <p key={type}><b>{ENTITY_LABEL[type] ?? type}</b> {[...new Set(values)].slice(0, 12).join(' · ')}{new Set(values).size > 12 ? ' …' : ''}</p>))}
        </div>);
}

/** What is on one page: its blocks in reading order, then the dates, amounts and contacts found. Click a block to see it on the PDF. */
export function Blocks({ page, onJump, tools }: { page: Page; onJump: (page: number, bbox?: BBox | null) => void; tools?: FigureTools }) {
    const st = page.structure;
    if (!st || st.blocks.length === 0) return <p className="muted">{page.error ? 'This page could not be read.' : 'Nothing readable on this page.'}</p>;
    return (
        <div className="rs-page">
            {!st.layout && <p className="rs-nolayout"><span className="rv-chip rv-chip--warn">No layout</span> Read without positions, so blocks cannot be shown on the page and tables are found from the text only.</p>}
            {st.blocks.map((b, i) => <BlockView key={i} block={b} page={page} onJump={onJump} after={st.blocks[i - 1]} tools={tools} />)}
            <EntityList entities={st.entities} />
            {st.running && st.running.length > 0 && <p className="rs-running">Repeated on every page: {st.running.map((r) => r.text).join(' · ')}</p>}
            {st.page_number && <p className="rs-pageno">Page number on the sheet: {st.page_number}</p>}
        </div>);
}
