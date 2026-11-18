import { memo, useState } from 'react';

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };


function Primitive({ v }: { v: Json }) {
    if (v === null) return <span className="jt-null">null</span>;
    if (typeof v === 'string') return <span className="jt-str">“{v.length > 400 ? `${v.slice(0, 400)}… (${v.length} characters)` : v}”</span>;
    return <span className={typeof v === 'number' ? 'jt-num' : 'jt-bool'}>{String(v)}</span>;
}

const Node = memo(function Node({ name, value, depth, openDepth }: { name?: string; value: Json; depth: number; openDepth: number }) {
    const [open, setOpen] = useState(depth < openDepth);
    const container = typeof value === 'object' && value !== null;
    if (!container) return <div className="jt-row"><span className="jt-pad" />{name !== undefined && <span className="jt-key">{name}: </span>}<Primitive v={value} /></div>;
    const entries: [string, Json][] = Array.isArray(value) ? value.map((v, i) => [String(i), v]) : Object.entries(value);
    const brace = Array.isArray(value) ? ['[', ']'] : ['{', '}'];
    const summary = `${entries.length} ${Array.isArray(value) ? (entries.length === 1 ? 'item' : 'items') : (entries.length === 1 ? 'key' : 'keys')}`;
    // Children are only rendered while open, so a large file costs nothing until you look inside it.
    return (
        <div className="jt-node">
            <button className="jt-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}>
                <span className="jt-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
                {name !== undefined && <span className="jt-key">{name}: </span>}
                <span className="jt-brace">{brace[0]}{!open && <span className="jt-sum"> {summary} </span>}{!open && brace[1]}</span>
            </button>
            {open && (<>
                <div className="jt-children">{entries.map(([k, v]) => <Node key={k} name={Array.isArray(value) ? undefined : k} value={v} depth={depth + 1} openDepth={openDepth} />)}</div>
                <div className="jt-row"><span className="jt-pad" /><span className="jt-brace">{brace[1]}</span></div>
            </>)}
        </div>
    );
});

/** A collapsible view of any JSON value. `openDepth` controls how many levels start open. */
export function JsonTree({ data, openDepth = 1 }: { data: unknown; openDepth?: number }) {
    return <div className="jt" role="tree"><Node value={data as Json} depth={0} openDepth={openDepth} /></div>;
}
