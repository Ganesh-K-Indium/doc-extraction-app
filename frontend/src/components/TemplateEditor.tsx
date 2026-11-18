import { useState } from 'react';
import type { LinkKind, TemplateDoc, TemplateField, TemplateLink, TemplateSection, TemplateTable } from '../api';
import { slugify } from '../lib/slug';
import { JsonTree } from './JsonTree';

const FIELD_TYPES = ['text', 'date', 'phone', 'number', 'currency', 'email', 'id', 'state', 'zip', 'tax_id', 'npi', 'icd10', 'enum', 'multi_enum', 'checkbox'];
const KINDS: [LinkKind, string][] = [['name', 'Same name'], ['date', 'Same date'], ['text', 'Same text'], ['set', 'Same set of codes (table column)'], ['mentioned', 'Appears in the other documents']];

interface Props {
    template: TemplateDoc; onChange: (t: TemplateDoc) => void; readOnly?: boolean;
    selectedKey?: string | null; onSelectField?: (f: TemplateField) => void;
}

const allFields = (t: TemplateDoc) => t.sections.flatMap(s => s.fields);

/** A key that no field in the template already uses. */
function uniqueKey(t: TemplateDoc, base: string): string {
    const used = new Set(allFields(t).map(f => f.key));
    if (!used.has(base)) return base;
    let n = 2;
    while (used.has(`${base}_${n}`)) n++;
    return `${base}_${n}`;
}

/** Everything a template holds, editable: fields, choices, tables, links to other documents, rules. */
export function TemplateEditor({ template: t, onChange, readOnly, selectedKey, onSelectField }: Props) {
    const [showJson, setShowJson] = useState(false);
    const set = (patch: Partial<TemplateDoc>) => onChange({ ...t, ...patch });
    const setSection = (si: number, patch: Partial<TemplateSection>) => set({ sections: t.sections.map((s, i) => (i === si ? { ...s, ...patch } : s)) });
    const setField = (si: number, fi: number, patch: Partial<TemplateField>) =>
        setSection(si, { fields: t.sections[si].fields.map((f, j) => (j === fi ? { ...f, ...patch } : f)) });

    /** Remove fields and tidy anything that pointed at them (links, rules). */
    const dropFields = (keys: string[]) => {
        const gone = new Set(keys);
        const canonical = Object.fromEntries(Object.entries(t.canonical ?? {}).flatMap(([k, l]) => {
            if (l.kind === 'set') return [[k, l]];
            const left = (l.fields ?? []).filter(f => !gone.has(f));
            return left.length ? [[k, { ...l, fields: left }]] : [];
        }));
        const sections = t.sections.map(s => ({ ...s, fields: s.fields.filter(f => !gone.has(f.key)) })).filter(s => s.fields.length || s.header === null);
        set({ sections, canonical, rules: (t.rules ?? []).filter(r => !gone.has(r.start) && !gone.has(r.end)) });
    };
    const move = (si: number, fi: number, dir: -1 | 1) => {
        const fields = [...t.sections[si].fields];
        const to = fi + dir;
        if (to < 0 || to >= fields.length) return;
        [fields[fi], fields[to]] = [fields[to], fields[fi]];
        setSection(si, { fields });
    };
    const addField = (si: number) => {
        const sec = t.sections[si];
        const key = uniqueKey(t, `${sec.id === 'main' ? '' : `${sec.id}.`}field_${sec.fields.length + 1}`);
        setSection(si, { fields: [...sec.fields, { key, label: '', type: 'text' }] });
    };
    // A field that was never renamed takes its key from the label you give it; a field already in use keeps its key (links point at it).
    const setLabel = (si: number, fi: number, label: string) => {
        const f = t.sections[si].fields[fi];
        if (/(^|\.)field_\d+$/.test(f.key) && slugify(label)) {
            const sec = t.sections[si];
            const key = uniqueKey({ ...t, sections: t.sections.map(s => ({ ...s, fields: s.fields.filter(x => x.key !== f.key) })) }, `${sec.id === 'main' ? '' : `${sec.id}.`}${slugify(label)}`);
            setField(si, fi, { label, key });
        } else setField(si, fi, { label });
    };
    const addSection = () => {
        let n = 1; const ids = new Set(t.sections.map(s => s.id));
        while (ids.has(`section_${n}`)) n++;
        set({ sections: [...t.sections, { id: `section_${n}`, header: '', fields: [] }] });
    };

    const setTable = (ti: number, patch: Partial<TemplateTable>) => set({ tables: t.tables.map((x, i) => (i === ti ? { ...x, ...patch } : x)) });
    const addTable = () => {
        let n = 1; const keys = new Set(t.tables.map(x => x.key));
        while (keys.has(`table_${n}`)) n++;
        set({ tables: [...t.tables, { key: `table_${n}`, header: '', columns: [{ key: 'col_1', label: '' }] }] });
    };

    const fieldLabel = (k: string) => allFields(t).find(f => f.key === k)?.label || k;
    const links = Object.entries(t.canonical ?? {});
    const setLink = (name: string, patch: Partial<TemplateLink>) => set({ canonical: { ...t.canonical, [name]: { ...(t.canonical ?? {})[name], ...patch } } });
    const dateFields = allFields(t).filter(f => f.type === 'date');
    const [newLink, setNewLink] = useState({ name: '', kind: 'date' as LinkKind });

    return (
        <div className="tpl">
            <div className="tpl__top">
                <label className="tpl__title">Name
                    <input type="text" value={t.title} disabled={readOnly} maxLength={120} onChange={e => set({ title: e.target.value })} /></label>
                <label className="tpl__check"><input type="checkbox" checked={t.single_page} disabled={readOnly} onChange={e => set({ single_page: e.target.checked })} />
                    One page only <span className="muted">(a following page without a title is a different document)</span></label>
                <button className="btn btn--tiny" onClick={() => setShowJson(v => !v)}>{showJson ? 'Back to the editor' : 'View template JSON'}</button>
            </div>

            {showJson ? <JsonTree data={t} openDepth={3} /> : (
                <>
                    {t.sections.map((s, si) => (
                        <section key={s.id} className="tpl__section">
                            <div className="tpl__sechead">
                                {s.header === null ? <h3>Fields outside any section</h3>
                                    : <input type="text" aria-label="Section heading as printed on the form" placeholder="Section heading as printed" value={s.header} disabled={readOnly} onChange={e => setSection(si, { header: e.target.value })} />}
                                <span className="muted">{s.fields.length} {s.fields.length === 1 ? 'field' : 'fields'}</span>
                            </div>
                            <div className="tpl__rows">
                                {s.fields.map((f, fi) => (
                                    <div key={f.key} className={`tpl__row${selectedKey === f.key ? ' tpl__row--on' : ''}`} onClick={() => onSelectField?.(f)}>
                                        <input className="tpl__label" type="text" aria-label="Field label" placeholder="Field label as printed" value={f.label} disabled={readOnly}
                                            onFocus={() => onSelectField?.(f)} onChange={e => setLabel(si, fi, e.target.value)} />
                                        <select aria-label={`Type of ${f.label || 'field'}`} value={f.type} disabled={readOnly} onChange={e => setField(si, fi, { type: e.target.value, ...(['enum', 'multi_enum'].includes(e.target.value) ? {} : { options: undefined }) })}>
                                            {FIELD_TYPES.map(x => <option key={x} value={x}>{x.replace('_', ' ')}</option>)}
                                        </select>
                                        <label className="tpl__req"><input type="checkbox" aria-label={`${f.label || 'Field'} is required`} checked={!!f.required} disabled={readOnly} onChange={e => setField(si, fi, { required: e.target.checked || undefined })} />Required</label>
                                        {f.page && <span className="tpl__page muted" title="Where this was found on the blank form">p{f.page}</span>}
                                        {!readOnly && (
                                            <span className="tpl__ops">
                                                <button className="btn btn--tiny btn--quiet" aria-label="Move up" onClick={e => { e.stopPropagation(); move(si, fi, -1); }} disabled={fi === 0}>↑</button>
                                                <button className="btn btn--tiny btn--quiet" aria-label="Move down" onClick={e => { e.stopPropagation(); move(si, fi, 1); }} disabled={fi === s.fields.length - 1}>↓</button>
                                                <button className="btn btn--tiny btn--quiet" aria-label={`Remove ${f.label || 'field'}`} onClick={e => { e.stopPropagation(); dropFields([f.key]); }}>Remove</button>
                                            </span>)}
                                        {(f.type === 'enum' || f.type === 'multi_enum') && (
                                            <label className="tpl__options">Choices, separated by commas
                                                <input key={(f.options ?? []).join('|')} type="text" defaultValue={(f.options ?? []).join(', ')} disabled={readOnly}
                                                    onBlur={e => setField(si, fi, { options: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })} /></label>)}
                                    </div>))}
                            </div>
                            {!readOnly && <button className="btn btn--tiny" onClick={() => addField(si)}>Add a field</button>}
                        </section>))}
                    {!readOnly && <button className="btn btn--tiny" onClick={addSection}>Add a section</button>}

                    <h3 className="tpl__h">Tables</h3>
                    {t.tables.length === 0 && <p className="muted">No tables.</p>}
                    {t.tables.map((tb, ti) => (
                        <section key={tb.key} className="tpl__section">
                            <div className="tpl__sechead">
                                <input type="text" aria-label="Table title" placeholder="Table title as printed" value={tb.header ?? ''} disabled={readOnly} onChange={e => setTable(ti, { header: e.target.value })} />
                                <label className="tpl__req"><input type="checkbox" checked={!!tb.required} disabled={readOnly} onChange={e => setTable(ti, { required: e.target.checked || undefined })} />Must have rows</label>
                                {!readOnly && <button className="btn btn--tiny btn--quiet" onClick={() => set({ tables: t.tables.filter((_, i) => i !== ti) })}>Remove table</button>}
                            </div>
                            <div className="tpl__rows">
                                {tb.columns.map((c, ci) => (
                                    <div key={c.key} className="tpl__row tpl__row--col">
                                        <input className="tpl__label" type="text" aria-label="Column heading" placeholder="Column heading" value={c.label} disabled={readOnly}
                                            onChange={e => setTable(ti, { columns: tb.columns.map((x, j) => (j === ci ? { ...x, label: e.target.value } : x)) })} />
                                        <label className="tpl__req"><input type="checkbox" aria-label={`${c.label || 'Column'} is required`} checked={!!c.required} disabled={readOnly}
                                            onChange={e => setTable(ti, { columns: tb.columns.map((x, j) => (j === ci ? { ...x, required: e.target.checked || undefined } : x)) })} />Required</label>
                                        {!readOnly && tb.columns.length > 1 && <button className="btn btn--tiny btn--quiet" onClick={() => setTable(ti, { columns: tb.columns.filter((_, j) => j !== ci) })}>Remove</button>}
                                    </div>))}
                            </div>
                            {!readOnly && <button className="btn btn--tiny" onClick={() => setTable(ti, { columns: [...tb.columns, { key: `col_${tb.columns.length + 1}_${Date.now() % 1000}`, label: '' }] })}>Add a column</button>}
                        </section>))}
                    {!readOnly && <button className="btn btn--tiny" onClick={addTable}>Add a table</button>}

                    <h3 className="tpl__h">Links to other documents</h3>
                    <p className="muted tpl__help">When a file holds several documents, a link says what must agree between them, for example the same person’s name or date of birth. A disagreement is reported as an error. Without links, documents are not compared.</p>
                    {links.length === 0 && <p className="muted">No links yet.</p>}
                    {links.map(([name, l]) => (
                        <div key={name} className="tpl__link">
                            <div className="tpl__linkhead"><code>{name}</code>
                                <select aria-label={`How ${name} is compared`} value={l.kind} disabled={readOnly} onChange={e => setLink(name, { kind: e.target.value as LinkKind })}>{KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select>
                                <input type="text" aria-label="Label used in messages" placeholder="Label used in messages" value={l.label ?? ''} disabled={readOnly} onChange={e => setLink(name, { label: e.target.value })} />
                                {!readOnly && <button className="btn btn--tiny btn--quiet" onClick={() => set({ canonical: Object.fromEntries(links.filter(([k]) => k !== name)) })}>Remove link</button>}
                            </div>
                            {l.kind === 'set' ? (
                                <div className="tpl__linkbody">
                                    <select aria-label="Table" value={l.table ?? ''} disabled={readOnly} onChange={e => setLink(name, { table: e.target.value, column: undefined })}>
                                        <option value="">Choose a table</option>{t.tables.map(x => <option key={x.key} value={x.key}>{x.header || x.key}</option>)}</select>
                                    <select aria-label="Column" value={l.column ?? ''} disabled={readOnly || !l.table} onChange={e => setLink(name, { column: e.target.value })}>
                                        <option value="">Choose a column</option>{(t.tables.find(x => x.key === l.table)?.columns ?? []).map(c => <option key={c.key} value={c.key}>{c.label || c.key}</option>)}</select>
                                </div>
                            ) : (
                                <div className="tpl__linkbody">
                                    {(l.fields ?? []).map(k => (
                                        <span key={k} className="chip">{fieldLabel(k)}{!readOnly && <button aria-label={`Remove ${fieldLabel(k)} from this link`} onClick={() => setLink(name, { fields: (l.fields ?? []).filter(x => x !== k) })}>×</button>}</span>))}
                                    {!readOnly && (
                                        <select aria-label="Add a field to this link" value="" onChange={e => e.target.value && setLink(name, { fields: [...(l.fields ?? []), e.target.value] })}>
                                            <option value="">Add a field…</option>{allFields(t).filter(f => !(l.fields ?? []).includes(f.key) && f.label).map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
                                        </select>)}
                                </div>)}
                        </div>))}
                    {!readOnly && (
                        <div className="tpl__newlink">
                            <input type="text" aria-label="Name of the new link" placeholder="Name, for example person.dob" value={newLink.name} onChange={e => setNewLink({ ...newLink, name: e.target.value })} />
                            <select aria-label="Comparison" value={newLink.kind} onChange={e => setNewLink({ ...newLink, kind: e.target.value as LinkKind })}>{KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select>
                            <button className="btn btn--tiny" disabled={!newLink.name.trim() || !!(t.canonical ?? {})[newLink.name.trim()]}
                                onClick={() => { const name = newLink.name.trim().toLowerCase().replace(/[^a-z0-9_.]+/g, '_'); set({ canonical: { ...t.canonical, [name]: { kind: newLink.kind, label: '', ...(newLink.kind === 'set' ? {} : { fields: [] }) } } }); setNewLink({ name: '', kind: newLink.kind }); }}>Add link</button>
                        </div>)}

                    <h3 className="tpl__h">Rules</h3>
                    {(t.rules ?? []).length === 0 && <p className="muted">No rules. A rule can require, for example, that an end date is not before a start date.</p>}
                    {(t.rules ?? []).map((r, ri) => (
                        <div key={ri} className="tpl__rule">
                            <select aria-label="Start date" value={r.start} disabled={readOnly} onChange={e => set({ rules: (t.rules ?? []).map((x, i) => (i === ri ? { ...x, start: e.target.value } : x)) })}>
                                {dateFields.map(f => <option key={f.key} value={f.key}>{f.label || f.key}</option>)}</select>
                            <span>must not be after</span>
                            <select aria-label="End date" value={r.end} disabled={readOnly} onChange={e => set({ rules: (t.rules ?? []).map((x, i) => (i === ri ? { ...x, end: e.target.value } : x)) })}>
                                {dateFields.map(f => <option key={f.key} value={f.key}>{f.label || f.key}</option>)}</select>
                            {!readOnly && <button className="btn btn--tiny btn--quiet" onClick={() => set({ rules: (t.rules ?? []).filter((_, i) => i !== ri) })}>Remove</button>}
                        </div>))}
                    {!readOnly && dateFields.length >= 2 && (
                        <button className="btn btn--tiny" onClick={() => set({ rules: [...(t.rules ?? []), { type: 'date_order', start: dateFields[0].key, end: dateFields[1].key, label: 'Dates' }] })}>Add a date rule</button>)}
                </>
            )}
        </div>
    );
}
