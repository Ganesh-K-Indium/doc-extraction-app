import { useMemo, useState } from 'react';
import { JsonTree } from '../components/JsonTree';

type Source = 'fields' | 'pages' | 'structure';

/** The extracted JSON, in the app: browse it as a tree or read it raw, copy it, download it. Reflects your edits. */
export function JsonView({ fields, pages, structure, onDownload }: { fields: unknown; pages: unknown; structure: unknown; onDownload: (kind: Source) => void }) {
    const [source, setSource] = useState<Source>('fields');
    const [mode, setMode] = useState<'tree' | 'raw'>('tree');
    const [copied, setCopied] = useState(false);
    const data = source === 'fields' ? fields : source === 'pages' ? pages : structure;
    const raw = useMemo(() => JSON.stringify(data, null, 2), [data]);
    const copy = async () => {
        try { await navigator.clipboard.writeText(raw); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setMode('raw'); }
    };
    return (
        <div className="jsonview">
            <div className="jsonview__bar">
                <div className="seg" role="group" aria-label="File">
                    <button aria-pressed={source === 'fields'} className={source === 'fields' ? 'seg__on' : ''} onClick={() => setSource('fields')}>fields.json</button>
                    <button aria-pressed={source === 'structure'} className={source === 'structure' ? 'seg__on' : ''} onClick={() => setSource('structure')}>structure.json</button>
                    <button aria-pressed={source === 'pages'} className={source === 'pages' ? 'seg__on' : ''} onClick={() => setSource('pages')}>pages.json</button>
                </div>
                <div className="seg" role="group" aria-label="View">
                    <button aria-pressed={mode === 'tree'} className={mode === 'tree' ? 'seg__on' : ''} onClick={() => setMode('tree')}>Tree</button>
                    <button aria-pressed={mode === 'raw'} className={mode === 'raw' ? 'seg__on' : ''} onClick={() => setMode('raw')}>Raw</button>
                </div>
                <span className="jsonview__gap" />
                <button className="btn btn--tiny" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
                <button className="btn btn--tiny" onClick={() => onDownload(source)}>Download</button>
            </div>
            <p className="hint">{source === 'fields'
                ? 'The key–value data of each document, with your edits. Each value carries its status, page and position on the page.'
                : source === 'structure'
                    ? 'The document as headings, paragraphs, label and value groups, tables and lists in reading order, with the dates, amounts and contacts found in them.'
                    : 'The text of every page, how it was read, and how the pages group into documents.'} {(raw.length / 1024).toFixed(0)} KB.</p>
            {mode === 'tree' ? <JsonTree key={source} data={data} openDepth={source === 'fields' ? 2 : 1} /> : <pre className="jsonview__raw">{raw}</pre>}
        </div>
    );
}
