import type { Cell, Form } from '../api';

export const FLAGGED = new Set(['review', 'undetermined']);
export type Value = string | boolean | string[];
export interface QItem { doc: number; key: string }
export type Filter = 'all' | 'check' | 'blank' | 'edited';

export const display = (v: Cell['value'] | undefined): string =>
    v === null || v === undefined ? '' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : Array.isArray(v) ? v.join(', ') : String(v);

export const isBlank = (c: Cell) => c.value === null || c.value === undefined || c.value === '' || (Array.isArray(c.value) && c.value.length === 0);

/** What the reviewer sees for a value's state. */
export function stateOf(c: Cell): { key: 'done' | 'quiet' | 'flag'; text: string } {
    if (c.status === 'corrected') return { key: 'done', text: display(c.value) === display(c.original as Cell['value']) ? 'Confirmed' : 'Edited' };
    switch (c.status) {
        case 'agreed': return { key: 'done', text: c.method ? 'Read from checkbox' : 'Both readers agree' };
        case 'single': return { key: 'quiet', text: 'One reader' };
        case 'empty': return { key: 'quiet', text: 'Blank' };
        default: return { key: 'flag', text: c.status === 'undetermined' ? 'Could not read' : 'Check' };
    }
}

export const isEdited = (c: Cell) => c.status === 'corrected' && display(c.value) !== display(c.original as Cell['value']);

/** An alternative reading arrives as text; a yes/no or multi-choice value must be corrected with its own type. */
export function typedLike(cell: Cell, text: string): Value {
    if (typeof cell.value === 'boolean' || cell.type === 'checkbox') return /^(true|yes)$/i.test(text.trim());
    if (Array.isArray(cell.value) || cell.type === 'multi_enum') return text.trim() === '(none)' ? [] : text.split(',').map(x => x.trim()).filter(Boolean);
    return text;
}
export const altText = (cell: Cell, a: string) => (typeof cell.value === 'boolean' ? (/^(true|yes)$/i.test(a.trim()) ? 'Yes' : 'No') : a);
export const altIntro = (cell: Cell) =>
    /scanned text/.test(cell.reason ?? '') ? 'The scanned text reads' : /pixels/.test(cell.reason ?? '') ? 'A model read it as' : 'The second reader saw';

const CELL = /^(?<t>[^[\]]+)\[(?<r>\d+)\]\.(?<c>.+)$/;
export const cellKey = (table: string, row: number, col: string) => `${table}[${row}].${col}`;

/** A field by key, or a table cell by `table[row].column`. */
export function cellAt(form: Form | undefined, key: string): Cell | undefined {
    if (!form) return undefined;
    if (key in form.fields) return form.fields[key];
    const m = CELL.exec(key);
    return m?.groups ? form.tables[m.groups.t]?.[Number(m.groups.r)]?.[m.groups.c] : undefined;
}

/** Every value in a form, in reading order, each with the key a correction uses. */
export function allCells(form: Form): { key: string; cell: Cell }[] {
    const out = Object.entries(form.fields).map(([key, cell]) => ({ key, cell }));
    for (const [t, rows] of Object.entries(form.tables)) rows.forEach((row, r) => Object.entries(row).forEach(([c, cell]) => out.push({ key: cellKey(t, r, c), cell })));
    return out;
}

export const rowId = (doc: number, key: string) => `row-${doc}-${key.replace(/\W/g, '_')}`;

export function matches(c: Cell, key: string, filter: Filter, query: string): boolean {
    if (filter === 'check' && !FLAGGED.has(c.status)) return false;
    if (filter === 'blank' && !isBlank(c)) return false;
    if (filter === 'edited' && !isEdited(c)) return false;
    const q = query.trim().toLowerCase();
    return !q || `${c.label ?? ''} ${key} ${display(c.value)}`.toLowerCase().includes(q);
}

/** Apply an edit to a copy of the form, the way the server will (so the screen updates before the round trip ends). */
export function withEdit(form: Form, key: string, value: Value): Form {
    const edit = (c: Cell): Cell => ({ ...c, original: c.original ?? c.value, value, status: 'corrected' });
    if (key in form.fields) return { ...form, fields: { ...form.fields, [key]: edit(form.fields[key]) }, values: { ...form.values, [key]: value } };
    const m = CELL.exec(key);
    if (!m?.groups) return form;
    const { t, r, c } = m.groups;
    const flat = (form.values[t] as Record<string, unknown>[] | undefined) ?? [];
    return {
        ...form,
        tables: { ...form.tables, [t]: form.tables[t].map((row, i) => (i === Number(r) ? { ...row, [c]: edit(row[c]) } : row)) },
        values: { ...form.values, [t]: flat.map((row, i) => (i === Number(r) ? { ...row, [c]: value } : row)) },
    };
}

/** Bring a row into view inside its own scrolling pane and nowhere else. (element.scrollIntoView scrolls every ancestor,
 *  including the window, which is what made the whole screen jump.) */
export function revealInPane(el: HTMLElement | null, paneSelector = '.panel__body'): void {
    const pane = el?.closest<HTMLElement>(paneSelector);
    if (!el || !pane) return;
    const e = el.getBoundingClientRect();
    const p = pane.getBoundingClientRect();
    const top = p.top + 44;                        // a sticky section heading covers the first rows
    if (e.top < top) pane.scrollTop -= top - e.top;
    else if (e.bottom > p.bottom - 8) pane.scrollTop += e.bottom - p.bottom + 8;
}
