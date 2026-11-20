import { useState } from 'react';
import type { Block, BBox, Page } from '../api';

const ENTITY_LABEL: Record<string, string> = { date: 'Dates', amount: 'Amounts', phone: 'Phones', email: 'Emails', url: 'Links', percent: 'Percentages' };

/** Where on the PDF a block sits. The structure keeps positions as fractions of the page; the viewer wants points. */
function toPoints(b: Block, page?: Page): BBox | null {
    if (!b.bbox || !page?.size) return null;
    const { width: w, height: h } = page.size;
    return [b.bbox[0] * w, b.bbox[1] * h, b.bbox[2] * w, b.bbox[3] * h];
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

function BlockView({ block, page, onJump, after }: { block: Block; page: Page; onJump: (page: number, bbox?: BBox | null) => void; after?: Block }) {
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
export function Blocks({ page, onJump }: { page: Page; onJump: (page: number, bbox?: BBox | null) => void }) {
    const st = page.structure;
    if (!st || st.blocks.length === 0) return <p className="muted">{page.error ? 'This page could not be read.' : 'Nothing readable on this page.'}</p>;
    return (
        <div className="rs-page">
            {!st.layout && <p className="rs-nolayout"><span className="rv-chip rv-chip--warn">No layout</span> Read without positions, so blocks cannot be shown on the page and tables are found from the text only.</p>}
            {st.blocks.map((b, i) => <BlockView key={i} block={b} page={page} onJump={onJump} after={st.blocks[i - 1]} />)}
            <EntityList entities={st.entities} />
            {st.running && st.running.length > 0 && <p className="rs-running">Repeated on every page: {st.running.map((r) => r.text).join(' · ')}</p>}
            {st.page_number && <p className="rs-pageno">Page number on the sheet: {st.page_number}</p>}
        </div>);
}
