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
    /** Correct a value of a read figure by hand. */
    onEdit: (page: number, index: number, field: string, value: string) => Promise<void> | void;
    /** Take a wrong part, connection or chart point out of a reading. */
    onRemove: (page: number, index: number, field: string) => Promise<void> | void;
}

const KIND_LABEL: Record<string, string> = { chart: 'Chart', diagram: 'Diagram', drawing: 'Drawing', photo: 'Photo', table: 'Table', logo: 'Logo', other: 'Figure' };

function FigureImage({ tools, page, index }: { tools: FigureTools; page: number; index: number }) {
    const [src, setSrc] = useState<string | null>(null);
    const [big, setBig] = useState(false);
    useEffect(() => {
        let url: string | null = null, live = true;
        api.figureImage(tools.wid, tools.id, page, index).then(u => { if (live) { url = u; setSrc(u); } else URL.revokeObjectURL(u); }).catch(() => undefined);
        return () => { live = false; if (url) URL.revokeObjectURL(url); };
    }, [tools.wid, tools.id, page, index]);
    return src
        ? <button type="button" className="rs-figure__zoom" onClick={e => { e.stopPropagation(); setBig(b => !b); }} title={big ? 'Shrink' : 'Click to enlarge'} aria-label={big ? 'Shrink the figure' : 'Enlarge the figure'}>
            <img className={big ? 'rs-figure__img is-big' : 'rs-figure__img'} src={src} alt="" />
        </button>
        : <div className="rs-figure__img rs-figure__img--wait" aria-hidden="true" />;
}

/** Read again: one click when nothing was edited; when something was, it asks first, in place, because it replaces the corrections. */
function Reread({ edited, busy, disabled, onRead }: { edited: boolean; busy: boolean; disabled: boolean; onRead: () => void }) {
    const [ask, setAsk] = useState(false);
    if (busy) return <button type="button" className="btn btn--tiny" disabled>Reading…</button>;
    if (ask) {
        return (
            <span className="rs-reread" role="group" aria-label="Replace your corrections?">
                <span className="muted">This replaces your corrections.</span>
                <button type="button" className="btn btn--tiny btn--primary" onClick={() => { setAsk(false); onRead(); }}>Read again</button>
                <button type="button" className="btn btn--tiny" onClick={() => setAsk(false)}>Keep my edits</button>
            </span>);
    }
    return <button type="button" className="btn btn--tiny" disabled={disabled} onClick={() => (edited ? setAsk(true) : onRead())}
        title={disabled ? 'Needs a vision model' : 'Ask the model again: one more model call'}>Read again</button>;
}

/** A value that can be corrected in place: click it, type, press Enter (or click away). Escape leaves it as it was. */
function Editable({ value, label, onSave, multiline, placeholder = 'add' }: { value: string | null; label: string; onSave: (v: string) => Promise<void> | void; multiline?: boolean; placeholder?: string }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const finish = async (save: boolean) => {
        const text = draft.trim();
        setEditing(false);
        if (save && text && text !== (value ?? '')) { setSaving(true); try { await onSave(text); } finally { setSaving(false); } }
    };
    if (!editing) {
        return <button type="button" className="rs-edit" disabled={saving} title={`Click to correct ${label} by hand`} onClick={e => { e.stopPropagation(); setDraft(value ?? ''); setEditing(true); }}>{saving ? 'Saving…' : value || placeholder}</button>;
    }
    const common = {
        autoFocus: true, value: draft, 'aria-label': `Correct ${label}`, className: 'rs-edit-input',
        onChange: (e: { target: { value: string } }) => setDraft(e.target.value), onClick: (e: { stopPropagation: () => void }) => e.stopPropagation(),
        onBlur: () => { void finish(true); },
        onKeyDown: (e: { key: string; shiftKey: boolean; preventDefault: () => void }) => {
            if (e.key === 'Escape') { setEditing(false); }
            else if (e.key === 'Enter' && !(multiline && e.shiftKey)) { e.preventDefault(); void finish(true); }
        },
    };
    return multiline ? <textarea rows={2} {...common} /> : <input type="text" {...common} />;
}

function RemoveButton({ what, onRemove }: { what: string; onRemove: () => Promise<void> | void }) {
    return <button type="button" className="rs-x" aria-label={`Remove ${what}`} title={`Remove ${what}`} onClick={e => { e.stopPropagation(); void onRemove(); }}>×</button>;
}

const Corrected = () => <span className="rs-mc" title="A person typed this value">manually corrected</span>;

function ChartView({ chart, edit, remove }: { chart: NonNullable<FigureReading['chart']>; edit?: (field: string, value: string) => Promise<void> | void; remove?: (field: string) => Promise<void> | void }) {
    // "Revenue (USD m)" with a unit of "USD m" is not written twice
    const unit = (a: { label: string | null; unit: string | null }) => [a.label, a.unit && !(a.label ?? '').includes(a.unit) ? `(${a.unit})` : null].filter(Boolean).join(' ');
    return (
        <div className="rs-chart">
            {edit ? (
                <p className="rs-chart__axes">
                    {chart.type} chart · x: <Editable value={chart.x_axis.label} label="the x axis label" onSave={v => edit('xaxis.label', v)} /> (<Editable value={chart.x_axis.unit} label="the x axis unit" placeholder="unit" onSave={v => edit('xaxis.unit', v)} />)
                    {' '}· y: <Editable value={chart.y_axis.label} label="the y axis label" onSave={v => edit('yaxis.label', v)} /> (<Editable value={chart.y_axis.unit} label="the y axis unit" placeholder="unit" onSave={v => edit('yaxis.unit', v)} />)
                    {(chart.x_axis.manually_corrected || chart.y_axis.manually_corrected) && <> <Corrected /></>}
                </p>
            ) : <p className="rs-chart__axes">{chart.type} chart{unit(chart.x_axis) ? ` · x: ${unit(chart.x_axis)}` : ''}{unit(chart.y_axis) ? ` · y: ${unit(chart.y_axis)}` : ''}</p>}
            {chart.series.map((s, i) => (
                <div className="rs-tablewrap" key={i}>
                    <table className="rs-table">
                        <thead><tr>
                            <th>{edit ? <Editable value={s.name} label="the series name" onSave={v => edit(`s${i}.name`, v)} /> : (s.name ?? 'Series')}{s.manually_corrected && <> <Corrected /></>}</th>
                            <th>{unit(chart.x_axis) || 'x'}</th><th>{unit(chart.y_axis) || 'y'}</th></tr></thead>
                        <tbody>{s.points.map((p, j) => (
                            <tr key={j}>
                                <td />
                                <td>{edit ? <Editable value={p.x} label="this label" onSave={v => edit(`s${i}.p${j}.x`, v)} /> : p.x}</td>
                                <td>
                                    {edit ? <Editable value={p.estimated && p.value != null ? String(p.value) : p.y} label="this value" onSave={v => edit(`s${i}.p${j}.y`, v)} /> : p.y}
                                    {p.estimated && <span className="rs-est" title="Worked out from the picture, not printed on it"> ≈ estimate</span>}
                                    {p.manually_corrected && <> <Corrected /></>}
                                    {remove && <> <RemoveButton what="this point" onRemove={() => remove(`s${i}.p${j}`)} /></>}
                                </td>
                            </tr>))}</tbody>
                    </table>
                </div>))}
        </div>);
}

function FigureView({ block, page, onJump, tools }: { block: Extract<Block, { type: 'figure' }>; page: Page; onJump: (page: number, bbox?: BBox | null) => void; tools?: FigureTools }) {
    const r = block.reading;
    const key = `${page.page}:${block.index}`;
    const working = tools?.busy === key || tools?.busy === 'all';
    const go = () => onJump(page.page, toPoints(block, page));
    const at = (field: string, v: string) => tools?.onEdit(page.page, block.index, field, v);
    const est = r?.chart ? r.chart.series.reduce((n, s) => n + s.points.filter(p => p.estimated).length, 0) : 0;
    const edited = !!r && (!!r.manually_corrected || !!r.chart?.series.some(s => s.manually_corrected || s.points.some(p => p.manually_corrected))
        || !!r.chart?.x_axis.manually_corrected || !!r.chart?.y_axis.manually_corrected || !!r.components?.some(c => c.manually_corrected) || !!r.connections?.some(c => c.manually_corrected));
    const state = !r ? { label: 'Not read', tone: 'muted' } : block.decorative ? { label: 'Decoration', tone: 'muted' } : edited ? { label: 'Edited by you', tone: 'warn' } : { label: 'Read by a model', tone: 'ok' };
    return (
        <figure className="rs-figure">
            <div className="rs-figure__top" onClick={go}>
                <span className="rv-chip rv-chip--muted">{KIND_LABEL[block.kind ?? 'other'] ?? 'Figure'}</span>
                <figcaption>{block.caption ?? r?.title ?? `Figure on page ${page.page}`}</figcaption>
                <span className={`rv-chip rv-chip--${state.tone} rs-figure__state`}>{state.label}</span>
            </div>
            {tools && <FigureImage tools={tools} page={page.page} index={block.index} />}
            {!r && (
                <div className="rs-figure__cta">
                    <p>{block.labels.length > 0 ? `${block.labels.length} labels are printed on it. ` : 'No text is printed on it. '}A model can read it into data: a chart as values, a diagram as parts and connections. One call, only when you ask.</p>
                    {tools && (
                        <button type="button" className="btn btn--primary btn--tiny" disabled={!tools.canRead || working || !!tools.busy} onClick={() => tools.onRead(page.page, block.index)}
                            title={tools.canRead ? 'One model call for this figure' : 'Needs a vision model: connect one on the Settings page'}>
                            {working ? 'Reading…' : 'Read this figure'}
                        </button>)}
                    {tools && !tools.canRead && <p className="rs-figure__hint">No vision model is connected. Add one on the Settings page.</p>}
                </div>)}
            {r && block.decorative && <p className="muted">The model took this for a logo or decoration, so nothing was extracted from it.</p>}
            {r && !block.decorative && (
                <div className="rs-figure__read">
                    {r.title && <h4 className="rs-figure__title">{tools ? <Editable value={r.title} label="the title" onSave={v => at('title', v)} /> : r.title}</h4>}
                    {r.summary && <p>{tools ? <Editable value={r.summary} label="the summary" multiline onSave={v => at('summary', v)} /> : r.summary}{r.manually_corrected && <> <Corrected /></>}</p>}
                    {r.chart && (
                        <>
                            <h5 className="rs-figure__h">Chart</h5>
                            <ChartView chart={r.chart} edit={tools ? at : undefined} remove={tools ? f => tools.onRemove(page.page, block.index, f) : undefined} />
                            {est > 0 && <p className="rs-figure__note">≈ marks values worked out from the picture{r.values_total ? `; ${r.values_confirmed ?? 0} of ${r.values_total} were found printed on it` : ''}. Treat them as estimates.</p>}
                        </>)}
                    {r.components && (
                        <>
                            <h5 className="rs-figure__h">Parts</h5>
                            <ul className="rs-parts">
                                {r.components.map((c, i) => (
                                    <li key={i}>
                                        {tools ? <Editable value={c.name} label="this part's name" onSave={v => at(`c${i}.name`, v)} /> : c.name}
                                        {(c.role || tools) && <span className="muted"> ({tools ? <Editable value={c.role} label="this part's role" onSave={v => at(`c${i}.role`, v)} /> : c.role})</span>}
                                        {c.manually_corrected && <> <Corrected /></>}
                                        {tools && <> <RemoveButton what="this part" onRemove={() => tools.onRemove(page.page, block.index, `c${i}`)} /></>}
                                    </li>))}
                            </ul>
                        </>)}
                    {r.connections && (
                        <>
                            <h5 className="rs-figure__h">Connections</h5>
                            <ul className="rs-figure__links">
                                {r.connections.map((c, i) => (
                                    <li key={i}>
                                        {tools ? <Editable value={c.from} label="where this connection starts" onSave={v => at(`l${i}.from`, v)} /> : c.from}
                                        {' → '}
                                        {tools ? <Editable value={c.to} label="where this connection ends" onSave={v => at(`l${i}.to`, v)} /> : c.to}
                                        {(c.label || tools) && <span className="muted"> ({tools ? <Editable value={c.label} label="this connection's label" onSave={v => at(`l${i}.label`, v)} /> : c.label})</span>}
                                        {c.manually_corrected && <> <Corrected /></>}
                                        {tools && <> <RemoveButton what="this connection" onRemove={() => tools.onRemove(page.page, block.index, `l${i}`)} /></>}
                                    </li>))}
                            </ul>
                        </>)}
                    {r.limits && <p className="rs-figure__note">Not readable: {tools ? <Editable value={r.limits} label="this note" multiline onSave={v => at('limits', v)} /> : r.limits}</p>}
                </div>)}
            {r && !block.decorative && (
                <div className="rs-figure__foot">
                    <span className="muted">Read by {r.model ?? 'a model'}.{tools && ' Click any text to correct it.'}</span>
                    {tools && <Reread edited={edited} busy={working} disabled={!tools.canRead || (!!tools.busy && !working)} onRead={() => tools.onRead(page.page, block.index, true)} />}
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
