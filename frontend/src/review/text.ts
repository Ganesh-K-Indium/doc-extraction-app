import type { Form, Page, Stats } from '../api';

export const EXTRACT_LABEL: Record<string, string> = { template_form: 'Read against a template', discover: 'Read without a template', kv: 'Read as label and value pairs', skip: 'Not extracted' };
export const READER_LABEL: Record<string, string> = {
    text_layer: 'embedded text, by code', ocr_dual: 'two vision readers', ocr_ladder: 'local OCR, with vision models if it was doubtful',
    ocr_local: 'local OCR on this server', text_layer_unverified: 'the scanner’s own text (unverified)',
};
const ENGINE: Record<string, string> = { tesseract: 'Tesseract', rapidocr: 'RapidOCR', paddleocr: 'PaddleOCR', doctr: 'docTR' };
const pct = (n: number) => `${Math.round(n * 100)}%`;

export const pageRange = (p: number[]) => (p.length === 1 ? `page ${p[0]}` : `pages ${p[0]}–${p[p.length - 1]}`);
export const formTitle = (f: Form) => (f.discovered ? f.label || 'Untitled document' : f.template_id);
export const sectionId = (doc: number, name: string) => `sec-${doc}-${name.replace(/\W/g, '_')}`;

/** One honest sentence about how a document's values were obtained. */
export function provenance(f: Form): string {
    if (f.readers.includes('text-layer')) return 'Read directly from the PDF’s own text and tables, so these values are exact copies. Tables were checked against the page: every number printed in them is present.';
    if (f.readers.length > 1) return 'Read by two models independently and compared. Values they agree on are quiet; anything else is marked Check.';
    if (f.readers.length === 1) return 'Read by one model only, so nothing was cross-checked. Treat every value as unverified.';
    return 'No model was available, so only text the PDF already holds was used.';
}

const pages = (n: number) => `${n} ${n === 1 ? 'page' : 'pages'}`;

/** "5 pages digital · 3 pages read by RapidOCR · no model calls": how the whole file was read, in a line. `engines` names the local OCR engines used. */
export function readSummary(s: Stats, engines: string[] = []): string {
    const parts: string[] = [];
    if (s.digital_pages) parts.push(`${pages(s.digital_pages)} digital`);
    if (s.local_ocr_pages !== undefined) {
        if (s.local_ocr_pages) parts.push(`${pages(s.local_ocr_pages)} read by ${engines.length ? engines.join(' + ') : 'local OCR'}`);
        if (s.vision_pages) parts.push(`${pages(s.vision_pages)} read by vision models`);
        if (s.region_pages) parts.push(`${pages(s.region_pages)} partly re-read by vision models`);
    } else if (s.scanned_pages) parts.push(`${pages(s.scanned_pages)} scanned`);
    if (s.handwritten_pages) parts.push(`${pages(s.handwritten_pages)} with handwriting`);
    if (s.usage) parts.push(s.usage.calls === 0 ? 'no model calls' : `${s.usage.tokens.toLocaleString()} tokens`);
    return parts.join(' · ');
}

export interface Chip { label: string; tone: 'ok' | 'info' | 'warn' | 'hand' | 'muted'; title?: string }

/** How one page was read, as short labels for the Pages tab. */
export function pageChips(p: Page): Chip[] {
    const r = p.reading;
    const out: Chip[] = [];
    if (p.source === 'failed') out.push({ label: 'Failed', tone: 'warn' });
    else if (p.source === 'text-layer') out.push({ label: 'Digital', tone: 'ok', title: 'Read directly from the PDF’s text, exactly' });
    else if (p.source === 'text-layer-unverified') out.push({ label: 'Scanner text', tone: 'muted', title: 'Only the scanner’s own text was available' });
    else if (r?.engine === 'vision') out.push({ label: r.escalated ? 'Vision (escalated)' : 'Vision', tone: 'info', title: r.models?.join(' and ') });
    else if (r?.engine && ENGINE[r.engine]) {
        const name = ENGINE[r.engine];
        if (r.scope === 'regions') out.push({ label: `${name} + ${r.regions} ${r.regions === 1 ? 'region' : 'regions'} by vision`, tone: 'info', title: r.reasons?.[r.reasons.length - 1] });
        else out.push({ label: `${name}${r.confidence != null ? ` ${pct(r.confidence)}` : ''}`, tone: (r.reasons ?? []).length ? 'warn' : 'info', title: 'Read on this server' });
    }
    if (p.handwritten) out.push({ label: 'Handwriting', tone: 'hand' });
    return out;
}

/** The longer explanation of how a page was read, shown when its row is opened. */
export function readingSentence(p: Page): string {
    const r = p.reading;
    const by = READER_LABEL[p.route?.reader ?? ''] ?? p.source;
    if (!r || !r.engine || r.engine === 'text-layer' || r.engine === 'scanner text') return `Read by ${by}.`;
    if (r.engine === 'vision') {
        const lead = r.escalated ? `Local OCR${r.local_confidence != null ? ` (${pct(r.local_confidence)} sure)` : ''} was not enough, so vision models read the whole page` : 'Read by vision models';
        return `${lead}${r.models?.length ? `: ${r.models.join(' and ')}` : ''}.${(r.reasons ?? []).length ? ` Why: ${r.reasons!.join('; ')}.` : ''}`;
    }
    const name = ENGINE[r.engine] ?? r.engine;
    const bits = [r.confidence != null ? `${pct(r.confidence)} sure` : '', r.agreement != null ? `${pct(r.agreement)} agreement with a second engine` : ''].filter(Boolean).join(', ');
    return `Read by ${name}${bits ? ` (${bits})` : ''}.${(r.reasons ?? []).length ? ` ${r.reasons!.join('; ')}.` : ''}`;
}
