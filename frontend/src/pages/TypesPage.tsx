import { useEffect, useState } from 'react';
import { meta, type Registry } from '../api';

const EXTRACTOR: Record<string, string> = { template_form: 'Field template', kv: 'Label and value pairs', skip: 'Not extracted' };

export default function TypesPage() {
    const [reg, setReg] = useState<Registry | null>(null);
    const [error, setError] = useState('');
    useEffect(() => { meta.registry().then(setReg).catch(e => setError(e.message)); }, []);
    return (
        <main className="list">
            <h1 className="page-title">Document types</h1>
            <p className="lede">Every page is classified against these types, and the type decides how it is extracted. Pages that match none are read as label and value pairs.</p>
            {error && <p className="notice notice--error" role="alert">{error}</p>}
            {!reg ? !error && <p className="muted">Loading types</p> : (
                <>
                    <table className="ledger">
                        <thead><tr><th scope="col">Type</th><th scope="col">Extraction</th><th scope="col">Template</th><th scope="col" className="num">Fields</th><th scope="col" className="num">Required</th></tr></thead>
                        <tbody>{reg.types.map(t => (
                            <tr key={t.type}>
                                <th scope="row">{t.label}</th>
                                <td>{EXTRACTOR[t.extractor] ?? t.extractor}</td>
                                <td className="muted">{t.template ?? 'None'}</td>
                                <td className="num">{t.template ? t.fields : ''}</td><td className="num">{t.template ? t.required : ''}</td>
                            </tr>))}</tbody>
                    </table>
                    <h2 className="section-title">How text is read</h2>
                    <dl className="defs">{reg.readers.map(r => (<div key={r.id}><dt>{r.label}</dt><dd>{r.summary}</dd></div>))}</dl>
                    <h2 className="section-title">Add a document type</h2>
                    <p className="lede">Add an entry to <code>DOC_TYPES</code> in <code>classify.py</code> with the title patterns and extraction kind. For a fixed form, add a template JSON in <code>app/templates</code>. No pipeline code changes.</p>
                </>
            )}
        </main>
    );
}
