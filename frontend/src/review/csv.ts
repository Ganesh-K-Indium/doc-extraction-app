import type { Cell, Form } from '../api';

const quote = (v: string) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
const text = (v: Cell['value'] | undefined) => (v === null || v === undefined ? '' : Array.isArray(v) ? v.join('; ') : typeof v === 'boolean' ? (v ? 'yes' : 'no') : v);

/** One row per value: fields first, then every table cell with its row number. What a reviewer corrected is exported as it stands now. */
export function reviewCsv(forms: Form[], names: Record<number, string> = {}): string {
    const head = ['document', 'kind', 'group', 'row', 'label', 'value', 'status', 'page'];
    const rows: string[][] = [];
    for (const f of forms) {
        const doc = names[f.doc_index] ?? f.label ?? f.doc_type;
        for (const c of Object.values(f.fields)) rows.push([doc, 'field', c.section ?? '', '', c.label ?? '', text(c.value), c.status, String(c.page)]);
        for (const [table, trs] of Object.entries(f.tables ?? {})) {
            trs.forEach((r, i) => { for (const c of Object.values(r)) rows.push([doc, 'table', table.replace(/_/g, ' '), String(i + 1), c.label ?? '', text(c.value), c.status, String(c.page)]); });
        }
    }
    return [head, ...rows].map(r => r.map(quote).join(',')).join('\r\n');
}

export function downloadText(name: string, body: string, type = 'text/csv') {
    const url = URL.createObjectURL(new Blob([body], { type: `${type};charset=utf-8` }));
    const a = document.createElement('a');
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
}
