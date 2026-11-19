import { useState } from 'react';
import type { BBox, Cell, Form } from '../api';
import { Menu } from '../components/Menu';
import { FieldRow } from './FieldRow';
import { FLAGGED, matches, scrollPaneTo, type Filter, type QItem, type Value } from './helpers';
import { formTitle, pageRange, provenance, sectionId } from './text';
import { TableGrid } from './TableGrid';

const FILTERS: [Filter, string][] = [['all', 'All'], ['check', 'To check'], ['blank', 'Blank'], ['edited', 'Edited']];
const tableTitle = (n: string) => (n === 'cpt' ? 'CPT / HCPCS services' : n.replace(/_/g, ' '));

function groupsOf(f: Form) {
    const g = new Map<string, { title: string; keys: string[] }>();
    for (const [k, c] of Object.entries(f.fields)) {
        const prefix = k.includes('.') ? k.split('.')[0] : 'form';
        const entry = g.get(prefix) ?? { title: c.section || prefix.replace(/_/g, ' '), keys: [] };
        entry.keys.push(k);
        g.set(prefix, entry);
    }
    return [...g.values()];
}
const flaggedIn = (cells: Cell[]) => cells.filter(c => FLAGGED.has(c.status)).length;

interface Props {
    forms: Form[];
    active: Form | undefined;
    toCheck: Map<number, number>;
    filter: Filter; onFilter: (f: Filter) => void;
    query: string; onQuery: (q: string) => void;
    sel: QItem | null;
    restDone: (f: Form) => boolean;
    readingDoc: number | null;
    restNote: string | undefined;
    savedAs: string | undefined;
    onOpenDoc: (f: Form) => void;
    onSelect: (q: QItem, cell?: Cell) => void;
    onSave: (doc: number, key: string, v: Value) => void;
    onJump: (page: number, bbox?: BBox | null) => void;
    onPromote: (f: Form) => void;
    onReadRest: (f: Form) => void;
}

export function FieldsTab(p: Props) {
    const { forms, active: f, filter, query, sel } = p;
    const [why, setWhy] = useState(false);

    const toolbar = (
        <div className="rv-toolbar">
            {forms.length > 1 && (forms.length <= 4
                ? (
                    <div className="rv-docs" role="tablist" aria-label="Documents in this file">
                        {forms.map(d => {
                            const n = p.toCheck.get(d.doc_index) ?? 0;
                            return (
                                <button key={d.doc_index} role="tab" aria-selected={d.doc_index === f?.doc_index} className={d.doc_index === f?.doc_index ? 'rv-doc rv-doc--on' : 'rv-doc'}
                                    title={`${d.remainder ? d.label : formTitle(d)}, ${pageRange(d.pages)}`} onClick={() => p.onOpenDoc(d)}>
                                    <span className="rv-doc__name">{d.remainder ? d.label : formTitle(d)}</span>
                                    {n > 0 && <b className="rv-badge">{n}</b>}
                                </button>);
                        })}
                    </div>)
                : (
                    <label className="rv-docselect"><span className="sr-only">Document</span>
                        <select value={f?.doc_index} onChange={e => { const d = forms.find(x => x.doc_index === Number(e.target.value)); if (d) p.onOpenDoc(d); }}>
                            {forms.map(d => <option key={d.doc_index} value={d.doc_index}>{d.remainder ? d.label : formTitle(d)} · {pageRange(d.pages)}{p.toCheck.get(d.doc_index) ? ` · ${p.toCheck.get(d.doc_index)} to check` : ''}</option>)}
                        </select>
                    </label>))}
            <div className="rv-filters">
                <div className="seg" role="group" aria-label="Show">
                    {FILTERS.map(([k, label]) => <button key={k} aria-pressed={filter === k} className={filter === k ? 'seg__on' : ''} onClick={() => p.onFilter(k)}>{label}</button>)}
                </div>
                <input className="search" type="search" placeholder="Find a field or value" aria-label="Find a field or value" value={query} onChange={e => p.onQuery(e.target.value)} />
            </div>
        </div>
    );

    if (!f) return toolbar;

    const shown = (k: string) => matches(f.fields[k], k, filter, query);
    const tableShown = (rows: Record<string, Cell>[], name: string) => (filter === 'all' && !query.trim())
        || rows.some(row => Object.entries(row).some(([c, cell]) => matches(cell, `${name}.${c}`, filter, query)));
    const groups = groupsOf(f);
    const anything = groups.some(g => g.keys.some(shown)) || Object.entries(f.tables).some(([n, rows]) => tableShown(rows, n));
    const targets = [
        ...groups.filter(g => g.keys.some(shown)).map(g => ({ id: sectionId(f.doc_index, g.title), title: g.title })),
        ...Object.entries(f.tables).filter(([n, rows]) => tableShown(rows, n)).map(([n]) => ({ id: sectionId(f.doc_index, n), title: tableTitle(n) })),
    ];
    const anyFlag = Object.values(f.fields).some(c => FLAGGED.has(c.status)) || Object.values(f.tables).some(rows => rows.some(r => Object.values(r).some(c => FLAGGED.has(c.status))));
    const canRest = !f.discovered && !f.remainder && !p.restDone(f);

    return (
        <>
            {toolbar}
            <div className="rv-docbar">
                <span className="rv-docbar__meta">
                    <span>{pageRange(f.pages)}</span>
                    {!f.remainder && <button className="link" aria-expanded={why} onClick={() => setWhy(w => !w)}>How these were read</button>}
                    {f.discovered && !f.remainder && !p.savedAs && <span className="rv-docbar__tag" title="No template matched, so the fields were found on the page itself">No template</span>}
                    {p.savedAs && <span className="rv-docbar__ok">Saved as “{p.savedAs}”</span>}
                </span>
                <span className="rv-docbar__actions">
                    {targets.length > 5 && (
                        <label className="rv-jump"><span className="sr-only">Jump to a section</span>
                            <select value="" onChange={e => { scrollPaneTo(document.getElementById(e.target.value)); e.target.value = ''; }}>
                                <option value="">Jump to…</option>
                                {targets.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                            </select>
                        </label>)}
                    {((f.discovered && !f.remainder && !p.savedAs) || canRest) && (
                        <Menu label="Document ▾">
                            {f.discovered && !f.remainder && !p.savedAs && <button onClick={() => p.onPromote(f)}>Save as a document type…</button>}
                            {canRest && <button disabled={p.readingDoc !== null} onClick={() => p.onReadRest(f)}>{p.readingDoc === f.doc_index ? 'Reading the pages…' : 'Read the rest of these pages (uses models)'}</button>}
                        </Menu>)}
                </span>
            </div>
            {why && !f.remainder && <p className="rv-why">{provenance(f)}</p>}
            {f.remainder && <p className="rv-why">Everything else on these pages that the form’s template does not cover. Printed text that belongs to the form itself (phone numbers in a header, a legend) can appear here too; ignore it.</p>}
            {f.discovered && !f.remainder && !p.savedAs && anyFlag && <p className="rv-why">No template matched, so these fields were found on the page. Check the values marked “Check”, then save this as a document type so the next file of this kind is recognised and named the same way.</p>}
            {p.restNote && <p className="rv-why">{p.restNote}</p>}

            {!anything && <p className="empty">Nothing matches. {filter !== 'all' ? 'Try “All”.' : 'Try a different search.'}</p>}
            {groups.map(g => {
                const keys = g.keys.filter(shown);
                if (!keys.length) return null;
                const flagged = flaggedIn(g.keys.map(k => f.fields[k]));
                return (
                    <details key={g.title} id={sectionId(f.doc_index, g.title)} className="section" open>
                        <summary><span className="section__title">{g.title}</span>
                            <span className={flagged ? 'section__count section__count--flag' : 'section__count'}>{flagged ? `${flagged} to check` : g.keys.length}</span></summary>
                        {keys.map(k => <FieldRow key={k} doc={f.doc_index} name={k} cell={f.fields[k]} selected={sel?.doc === f.doc_index && sel.key === k}
                            onSelect={() => p.onSelect({ doc: f.doc_index, key: k }, f.fields[k])} onSave={v => p.onSave(f.doc_index, k, v)} onJump={() => p.onJump(f.fields[k].page, f.fields[k].bbox)} />)}
                    </details>);
            })}
            {Object.entries(f.tables).map(([name, rows]) => {
                if (!tableShown(rows, name)) return null;
                const n = rows.reduce((a, r) => a + flaggedIn(Object.values(r)), 0);
                return (
                    <details key={name} id={sectionId(f.doc_index, name)} className="section" open={rows.length <= 30 || n > 0}>
                        <summary><span className="section__title">{tableTitle(name)}</span>
                            <span className={n ? 'section__count section__count--flag' : 'section__count'}>{n ? `${n} to check · ` : ''}{rows.length} {rows.length === 1 ? 'row' : 'rows'}</span></summary>
                        <TableGrid doc={f.doc_index} name={name} rows={rows} columns={f.table_columns?.[name]} selectedKey={sel?.doc === f.doc_index ? sel.key : null}
                            onSelect={(key, cell) => p.onSelect({ doc: f.doc_index, key }, cell)} onSave={(key, v) => p.onSave(f.doc_index, key, v)} />
                    </details>);
            })}
        </>
    );
}
