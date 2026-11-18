export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const KEY = import.meta.env.VITE_API_KEY || '';
const ROOT = `${API_BASE}`;

export const authHeaders = (): Record<string, string> => (KEY ? { 'X-API-Key': KEY } : {});

export type BBox = [number, number, number, number]; // PDF points, top-left origin
export type Status = 'agreed' | 'review' | 'single' | 'empty' | 'corrected' | 'undetermined';

export interface Summary {
    id: string; filename: string; status: 'queued' | 'processing' | 'done' | 'failed'; stage: string | null;
    progress: { done: number; total: number }; error: string | null; created_at: string; template_choice?: string; read_rest?: boolean;
    stats: { pages: number; forms: number; needs_review: number; errors: number } | null;
}
export interface Line { text: string; status: 'agreed' | 'review'; alternatives: string[]; reason: string | null }
export interface Page {
    page: number; source: string; verified: boolean; scanned: boolean; has_text_layer?: boolean; error?: string; text: string; lines: Line[];
    route?: Route; page_meta: Record<string, string | number>; classification: { type: string; label: string; confidence: number };
}
export interface Route { reasons: string[]; reader?: string; extractor?: string }
export interface Doc { doc_index: number; type: string; label: string; pages: number[]; route?: Route }
export interface Cell {
    value: string | string[] | boolean | null; status: Status; alternatives: string[]; reason?: string;
    method?: string | null; bbox: BBox | null; page: number; original?: unknown; label?: string; section?: string | null;
}
export interface Form {
    doc_index: number; doc_type: string; template_id: string; pages: number[]; readers: string[];
    fields: Record<string, Cell>; tables: Record<string, Record<string, Cell>[]>; values: Record<string, unknown>;
    discovered?: boolean; label?: string; table_columns?: Record<string, string[]>;
    remainder?: boolean; remainder_of?: number;
}
export interface Finding { rule: string; severity: 'error' | 'warn' | 'info'; detail: string; field?: string; doc_index?: number }
export interface Detail extends Summary {
    pages?: { documents: Doc[]; pages: Page[] };
    fields?: { forms: Form[]; validation: Finding[]; rest_checked?: number[]; other_documents: { doc_index: number; doc_type: string; pages: number[]; canonical: Record<string, string> }[] };
}

export interface RegistryType { type: string; label: string; extractor: 'template_form' | 'kv' | 'skip'; template: string | null; fields: number; required: number; custom?: boolean }
export interface DraftField { key: string; label: string; type: string; required?: boolean; options?: string[] }
export interface DraftTemplate {
    doc_type: string; title: string; single_page: boolean;
    sections: { id: string; header: string | null; fields: DraftField[] }[];
    tables: { key: string; header: string | null; columns: { key: string; label: string; required?: boolean }[] }[];
    [k: string]: unknown;
}
export interface Registry { types: RegistryType[]; readers: { id: string; label: string; summary: string }[] }

export interface Workspace {
    id: string; name: string; description: string; created_at: string; last_activity: string;
    documents: number; processing: number; to_check: number; errors: number; custom_types: number;
}

async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(url, { ...init, headers: { ...authHeaders(), ...(init.headers || {}) } });
    if (!res.ok) {
        let detail = `Request failed (${res.status})`;
        try { const b = await res.json(); if (typeof b.detail === 'string') detail = b.detail; } catch { /* not JSON */ }
        throw new Error(detail);
    }
    return res.status === 204 ? (undefined as T) : res.json();
}
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const ws = (wid: string) => `${ROOT}/api/workspaces/${encodeURIComponent(wid)}`;

export const workspaces = {
    list: () => send<Workspace[]>(`${ROOT}/api/workspaces`),
    get: (wid: string) => send<Workspace>(ws(wid)),
    create: (name: string, description?: string) => send<Workspace>(`${ROOT}/api/workspaces`, json('POST', { name, description })),
    rename: (wid: string, name: string, description?: string) => send<Workspace>(ws(wid), json('PATCH', { name, description })),
    remove: (wid: string) => send<void>(ws(wid), { method: 'DELETE' }),
};

export const meta = {
    registry: (wid: string) => send<Registry>(`${ws(wid)}/registry`),
    health: async (): Promise<{ ok: boolean; llm: boolean; tesseract: boolean }> => {
        const res = await fetch(`${ROOT}/health`);
        if (!res.ok) throw new Error('offline');
        return res.json();
    },
};

export const templates = {
    draft: (wid: string, file: File) => { const f = new FormData(); f.append('file', file); return send<{ template: DraftTemplate }>(`${ws(wid)}/templates/draft`, { method: 'POST', body: f }); },
    save: (wid: string, template: DraftTemplate) => send<{ doc_type: string }>(`${ws(wid)}/templates`, json('POST', { template })),
    remove: (wid: string, docType: string) => send<void>(`${ws(wid)}/templates/${encodeURIComponent(docType)}`, { method: 'DELETE' }),
};

export const api = {
    list: (wid: string) => send<Summary[]>(`${ws(wid)}/extractions`),
    get: (wid: string, id: string) => send<Detail>(`${ws(wid)}/extractions/${id}`),
    upload: (wid: string, file: File, template = 'auto', readRest = false) => { const f = new FormData(); f.append('file', file); f.append('template', template); f.append('read_rest', String(readRest)); return send<{ id: string }>(`${ws(wid)}/extractions`, { method: 'POST', body: f }); },
    promote: (wid: string, id: string, docIndex: number, title: string) => send<{ doc_type: string; title: string; fields: number }>(`${ws(wid)}/extractions/${id}/forms/${docIndex}/promote`, json('POST', { title })),
    correct: (wid: string, id: string, doc_index: number, key: string, value: unknown) => send<{ ok: boolean }>(`${ws(wid)}/extractions/${id}/fields`, json('PATCH', { doc_index, key, value })),
    remove: (wid: string, id: string) => send<void>(`${ws(wid)}/extractions/${id}`, { method: 'DELETE' }),
    readRest: (wid: string, id: string, docIndex: number) => send<{ added: boolean; doc_index: number | null; items: number }>(`${ws(wid)}/extractions/${id}/documents/${docIndex}/rest`, { method: 'POST' }),
    pdfUrl: (wid: string, id: string) => `${ws(wid)}/extractions/${id}/pdf`,
    /** Download a JSON file (fetch + blob so the API key header is sent). */
    download: async (wid: string, id: string, kind: 'pages' | 'fields' | 'truth', name: string) => {
        const res = await fetch(`${ws(wid)}/extractions/${id}/${kind}.json`, { headers: authHeaders() });
        if (!res.ok) throw new Error(`Download failed (${res.status})`);
        const url = URL.createObjectURL(await res.blob());
        const a = document.createElement('a');
        a.href = url; a.download = `${name.replace(/\.pdf$/i, '')}.${kind}.json`; a.click();
        URL.revokeObjectURL(url);
    },
};
