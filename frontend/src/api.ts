export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const KEY = import.meta.env.VITE_API_KEY || '';
const ROOT = `${API_BASE}`;

export const authHeaders = (): Record<string, string> => (KEY ? { 'X-API-Key': KEY } : {});

export type BBox = [number, number, number, number]; // PDF points, top-left origin
export type Status = 'agreed' | 'review' | 'single' | 'empty' | 'corrected' | 'undetermined';

export interface Summary {
    id: string; filename: string; status: 'queued' | 'processing' | 'done' | 'failed'; stage: string | null;
    progress: { done: number; total: number }; error: string | null; created_at: string; template_choice?: string; read_rest?: boolean;
    stats: Stats | null;
    /** What the file turned out to be (discovered title or classified type), first few documents. */
    labels?: string[];
    /** The reading plan this file was read under. Absent on older results. */
    reading?: ReadingPlan | null;
}
export interface ReadingPlan {
    strategy: string; mode: 'local' | 'escalate' | 'vision'; local_engine: string | null; models: string[];
    escalate_below: number; token_cap: number; uses_models: boolean; notes: string[]; fingerprint: string;
}
/** How one page was read: which engine, how sure it was, and why it was sent on to the vision models (if it was). */
export interface PageReading {
    engine?: string | null; confidence?: number | null; agreement?: number | null; local_confidence?: number | null;
    escalated?: boolean; reasons?: string[]; models?: string[]; cost_capped?: boolean;
}
export interface Stats {
    pages: number; forms: number; needs_review: number; errors: number;
    /** How it was read: digital pages by code, scans by vision models, pages with handwriting. Absent on older results. */
    digital_pages?: number; scanned_pages?: number; handwritten_pages?: number; unverified_tables?: number;
    local_ocr_pages?: number; vision_pages?: number; escalated_pages?: number;
    usage?: { calls: number; tokens: number; by_stage: Record<string, number> };
}
export interface Line { text: string; status: 'agreed' | 'review'; alternatives: string[]; reason: string | null }
export interface Page {
    page: number; source: string; verified: boolean; scanned: boolean; handwritten?: boolean; has_text_layer?: boolean; error?: string; text: string; lines: Line[];
    route?: Route; reading?: PageReading; page_meta: Record<string, string | number>; classification: { type: string; label: string; confidence: number };
}
export interface Route { reasons: string[]; reader?: string; extractor?: string }
export interface Doc { doc_index: number; type: string; label: string; pages: number[]; route?: Route }
export interface Cell {
    value: string | string[] | boolean | null; status: Status; alternatives: string[]; reason?: string;
    method?: string | null; bbox: BBox | null; page: number; original?: unknown; label?: string; section?: string | null;
    /** Set when a third reading settled a disagreement between the two readers. */
    settled_by?: string;
    type?: string; options?: string[];
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
export interface TemplateField { key: string; label: string; type: string; required?: boolean; options?: string[]; pattern?: string; page?: number; bbox?: BBox }
export interface TemplateSection { id: string; header: string | null; fields: TemplateField[] }
export interface TemplateTable { key: string; header: string | null; required?: boolean; columns: { key: string; label: string; required?: boolean; pattern?: string }[] }
export type LinkKind = 'name' | 'date' | 'text' | 'set' | 'mentioned';
export interface TemplateLink { kind: LinkKind; label?: string; fields?: string[]; table?: string; column?: string; pattern?: string }
export interface TemplateRule { type: 'date_order'; start: string; end: string; label?: string }
export interface TemplateDoc {
    doc_type: string; title: string; single_page: boolean; template_id?: string;
    sections: TemplateSection[]; tables: TemplateTable[];
    canonical?: Record<string, TemplateLink>; rules?: TemplateRule[];
    [k: string]: unknown;
}
export type DraftTemplate = TemplateDoc;
export interface Suggestion {
    title: string | null; count: number; fields: string[]; tables: string[];
    examples: { extraction_id: string; doc_index: number; filename: string }[];
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

export interface Health { ok: boolean; llm: boolean; tesseract: boolean; local_only?: boolean; local_engines?: string[]; providers?: string[] }

export const meta = {
    registry: (wid: string) => send<Registry>(`${ws(wid)}/registry`),
    health: async (): Promise<Health> => {
        const res = await fetch(`${ROOT}/health`);
        if (!res.ok) throw new Error('offline');
        return res.json();
    },
};

export interface LocalEngine { id: string; label: string; summary: string; ready: boolean; status: 'ready' | 'not_installed'; hint: string; cross_checked: boolean }
export interface Provider { id: string; label: string; cloud: boolean; ready: boolean; status: 'ready' | 'needs_setup' | 'blocked'; hint: string; models: string[] }
export interface Strategy { id: string; label: string; mode: string; summary: string }
export interface EnginesOverview {
    local_only: boolean; llm_enabled: boolean; local_engines: LocalEngine[]; providers: Provider[]; strategies: Strategy[];
    defaults: { models: string[]; escalate_below: number; plan: ReadingPlan };
}
export interface ReadingSettings { strategy?: string; mode?: string; local_engine?: string; models?: string[]; escalate_below?: number; token_cap?: number }
export interface ReadingView { settings: ReadingSettings; plan: ReadingPlan; strategy_default: string }
export interface EngineTest { ok: boolean; error?: string; seconds?: number; text?: string; confidence?: number | null; score?: number; tokens?: number }

export const engines = {
    overview: () => send<EnginesOverview>(`${ROOT}/api/engines`),
    test: (kind: 'local' | 'model', id: string) => send<EngineTest>(`${ROOT}/api/engines/test`, json('POST', { kind, id })),
};
export interface SettingField { name: string; label: string; secret: boolean; kind: 'key' | 'url' | 'text'; help: string; set: boolean; source: 'saved' | 'environment' | null; preview: string }
export interface ProviderSettings extends Provider { fields: SettingField[] }
export interface ProvidersView { locked: boolean; encryption: 'ok' | 'unavailable'; local_only: boolean; providers: ProviderSettings[] }
export const settings = {
    providers: () => send<ProvidersView>(`${ROOT}/api/settings/providers`),
    /** A string sets a value, null removes a saved one, an empty string leaves it alone. Keys are never sent back. */
    save: (id: string, values: Record<string, string | null>) => send<ProviderSettings>(`${ROOT}/api/settings/providers/${encodeURIComponent(id)}`, json('PUT', { values })),
};

export const reading = {
    get: (wid: string) => send<ReadingView>(`${ws(wid)}/reading`),
    save: (wid: string, settings: ReadingSettings) => send<ReadingView>(`${ws(wid)}/reading`, json('PUT', settings)),
};

export const templates = {
    draft: (wid: string, file: File) => { const f = new FormData(); f.append('file', file); return send<{ template: DraftTemplate }>(`${ws(wid)}/templates/draft`, { method: 'POST', body: f }); },
    save: (wid: string, template: TemplateDoc) => send<{ doc_type: string }>(`${ws(wid)}/templates`, json('POST', { template })),
    get: (wid: string, docType: string) => send<{ template: TemplateDoc; builtin: boolean }>(`${ws(wid)}/templates/${encodeURIComponent(docType)}`),
    replace: (wid: string, template: TemplateDoc) => send<{ doc_type: string }>(`${ws(wid)}/templates/${encodeURIComponent(template.doc_type)}`, json('PUT', { template })),
    remove: (wid: string, docType: string) => send<void>(`${ws(wid)}/templates/${encodeURIComponent(docType)}`, { method: 'DELETE' }),
    /** Document shapes that keep recurring among this workspace's untemplated files. */
    suggestions: (wid: string) => send<{ suggestions: Suggestion[] }>(`${ws(wid)}/templates/suggestions`).then(r => r.suggestions),
};

export const api = {
    list: (wid: string) => send<Summary[]>(`${ws(wid)}/extractions`),
    get: (wid: string, id: string) => send<Detail>(`${ws(wid)}/extractions/${id}`),
    upload: (wid: string, file: File, template = 'auto', readRest = false, readingChoice = '') => { const f = new FormData(); f.append('file', file); f.append('template', template); f.append('read_rest', String(readRest)); f.append('reading', readingChoice); return send<{ id: string }>(`${ws(wid)}/extractions`, { method: 'POST', body: f }); },
    /** Read the file again (another strategy, or chosen pages straight to the vision models). Creates a second extraction. */
    reread: (wid: string, id: string, body: { strategy?: string; pages?: number[] }) => send<{ id: string }>(`${ws(wid)}/extractions/${id}/reread`, json('POST', body)),
    promote: (wid: string, id: string, docIndex: number, title: string) => send<{ doc_type: string; title: string; fields: number }>(`${ws(wid)}/extractions/${id}/forms/${docIndex}/promote`, json('POST', { title })),
    correct: (wid: string, id: string, doc_index: number, key: string, value: unknown) => send<{ ok: boolean; needs_review: number }>(`${ws(wid)}/extractions/${id}/fields`, json('PATCH', { doc_index, key, value })),
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
