import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ModelPicker } from '../components/ModelPicker';
import { engines, reading, type EngineTest, type EnginesOverview, type ReadingSettings, type ReadingView } from '../api';

const COST: Record<string, string> = {
    economy: 'No model calls',
    balanced: 'Models only for doubtful pages',
    accuracy: 'Models on every scanned page',
    custom: 'You decide',
};
const MODES: [string, string][] = [['local', 'Local OCR only'], ['escalate', 'Local OCR, then vision models when doubtful'], ['vision', 'Vision models on every scanned page']];

type Tests = Record<string, EngineTest | 'running'>;

const pct = (n: number) => `${Math.round(n * 100)}%`;

function Result({ t }: { t?: EngineTest | 'running' }) {
    if (!t) return null;
    if (t === 'running') return <span className="rd__result muted" role="status">Reading a sample page…</span>;
    if (!t.ok) return <span className="rd__result rd__result--bad" role="status">{t.error}</span>;
    const good = (t.score ?? 0) >= 0.75;
    return (
        <span className={good ? 'rd__result rd__result--ok' : 'rd__result rd__result--bad'} role="status">
            {good ? 'Works' : 'Read the page poorly'}: found {pct(t.score ?? 0)} of the sample values in {t.seconds}s
            {t.tokens ? `, ${t.tokens.toLocaleString()} tokens` : ', free'}.
        </span>
    );
}

export default function ReadingPage() {
    const { wid = '' } = useParams();
    const [info, setInfo] = useState<EnginesOverview | null>(null);
    const [view, setView] = useState<ReadingView | null>(null);
    const [draft, setDraft] = useState<ReadingSettings>({});
    const [tests, setTests] = useState<Tests>({});
    const [busy, setBusy] = useState(false);
    const [saved, setSaved] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        Promise.all([engines.overview(), reading.get(wid)])
            .then(([o, v]) => { setInfo(o); setView(v); setDraft(v.settings); })
            .catch(e => setError(e.message));
    }, [wid]);

    const strategy = draft.strategy ?? view?.strategy_default ?? 'balanced';
    const mode = strategy === 'custom' ? (draft.mode ?? 'escalate') : strategy === 'economy' ? 'local' : strategy === 'accuracy' ? 'vision' : 'escalate';
    const usesLocal = mode !== 'vision';
    const usesModels = mode !== 'local';
    const engine = draft.local_engine ?? view?.plan.local_engine ?? '';
    const threshold = draft.escalate_below ?? info?.defaults.escalate_below ?? 0.85;
    const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(view?.settings ?? {}), [draft, view]);
    const set = (patch: ReadingSettings) => { setDraft(d => ({ ...d, ...patch })); setSaved(false); };

    const test = async (kind: 'local' | 'model', id: string) => {
        setTests(t => ({ ...t, [`${kind}:${id}`]: 'running' }));
        try { const r = await engines.test(kind, id); setTests(t => ({ ...t, [`${kind}:${id}`]: r })); }
        catch (e) { setTests(t => ({ ...t, [`${kind}:${id}`]: { ok: false, error: (e as Error).message } })); }
    };

    const save = async () => {
        setBusy(true); setError('');
        const body: ReadingSettings = { strategy };
        if (strategy === 'custom') body.mode = mode;
        if (draft.local_engine) body.local_engine = draft.local_engine;
        const models = (draft.models ?? []).map(m => m.trim()).filter(Boolean);
        if (models.length) body.models = models;
        if (draft.escalate_below !== undefined) body.escalate_below = draft.escalate_below;
        if (draft.token_cap) body.token_cap = draft.token_cap;
        try { const v = await reading.save(wid, body); setView(v); setDraft(v.settings); setSaved(true); }
        catch (e) { setError((e as Error).message); }
        finally { setBusy(false); }
    };

    if (error && !info) return <main className="list"><p className="notice notice--error" role="alert">{error}</p></main>;
    if (!info || !view) return <main className="list"><p className="muted">Loading reading settings</p></main>;

    const models = draft.models ?? [];
    const summary = [
        'Digital PDFs: read directly from their text by code. Free, and exact, under every setting.',
        mode === 'local' ? 'Scanned pages and handwriting: read by a local OCR engine on this server. No model is ever called; doubtful lines are flagged for you.'
            : mode === 'vision' ? 'Scanned pages and handwriting: two vision models read each page and are compared.'
                : `Scanned pages and handwriting: read by the local OCR engine first. A page goes to the vision models only when the local reading is below ${pct(threshold)} confidence or looks wrong.`,
    ];

    return (
        <main className="list rd">
            <h1 className="page-title">Reading engines</h1>
            <p className="lede">Choose how scanned pages and handwriting are read in this workspace: free local OCR, vision models, or both. Documents you upload from now on follow these settings; you can still choose differently for a single upload.</p>

            {info.local_only && <p className="notice rd__notice" role="status"><b>Local-only mode.</b> This server is set so that nothing leaves it: cloud models are switched off. Local OCR and models on your own hardware still work.</p>}
            {!info.llm_enabled && !info.local_only && <p className="notice rd__notice" role="status">No vision model is configured on this server, so every scanned page is read by local OCR. Add a provider key (see below) to let doubtful pages go to a model.</p>}
            {error && <p className="notice notice--error rd__notice" role="alert">{error}</p>}

            <section aria-labelledby="rd-strategy">
                <h2 className="section-title" id="rd-strategy">Strategy</h2>
                <div className="rd__cards" role="radiogroup" aria-labelledby="rd-strategy">
                    {info.strategies.map(s => (
                        <label key={s.id} className={strategy === s.id ? 'rd__card rd__card--on' : 'rd__card'}>
                            <input type="radio" name="strategy" checked={strategy === s.id} onChange={() => set({ strategy: s.id })} />
                            <span className="rd__card-title">{s.label}{s.id === 'balanced' && <em> recommended</em>}</span>
                            <span className="rd__card-sub">{COST[s.id]}</span>
                            <span className="rd__card-body">{s.summary}</span>
                        </label>))}
                </div>
                {strategy === 'custom' && (
                    <label className="rd__field">When to use a vision model
                        <select value={mode} onChange={e => set({ mode: e.target.value })}>{MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                    </label>)}
            </section>

            {usesLocal && (
                <section aria-labelledby="rd-local">
                    <h2 className="section-title" id="rd-local">Local OCR engine</h2>
                    <p className="hint">Runs on this server. Nothing is sent anywhere, and it costs nothing per page.</p>
                    <div className="rd__list" role="radiogroup" aria-labelledby="rd-local">
                        {info.local_engines.map(e => (
                            <div key={e.id} className={engine === e.id ? 'rd__row rd__row--on' : 'rd__row'}>
                                <label className="rd__pick">
                                    <input type="radio" name="engine" disabled={!e.ready} checked={engine === e.id} onChange={() => set({ local_engine: e.id })} />
                                    <span><b>{e.label}</b> <span className={`rd__chip rd__chip--${e.ready ? 'ok' : 'off'}`}>{e.ready ? 'Installed' : 'Not installed'}</span>
                                        <span className="rd__sub">{e.summary}{e.cross_checked && e.ready ? ' Its pages are checked against Tesseract before they are trusted.' : ''}</span>
                                        {!e.ready && <span className="rd__sub">Install: <code>{e.hint}</code></span>}</span>
                                </label>
                                {e.ready && <button className="btn" onClick={() => test('local', e.id)} disabled={tests[`local:${e.id}`] === 'running'}>Test</button>}
                                <Result t={tests[`local:${e.id}`]} />
                            </div>))}
                    </div>
                </section>)}

            {usesModels && (
                <section aria-labelledby="rd-models">
                    <h2 className="section-title" id="rd-models">Vision models</h2>
                    <p className="hint">Two different models read each page on their own and are compared; a value they disagree on is flagged for you. The first is the main reader. Leave both on the server default, or pick others, including ones from different providers. Keys are added in <Link to="/app/settings">Settings</Link>.</p>
                    {[0, 1].map(i => {
                        const spec = models[i] || info.defaults.models[i] || '';
                        const key = `model:${spec}`;
                        return (
                            <div className="rd__model" key={i}>
                                <ModelPicker label={i === 0 ? 'Main reader' : 'Cross-check reader'} value={models[i] ?? ''} fallback={info.defaults.models[i]} providers={info.providers}
                                    onChange={v => { const next = [models[0] ?? '', models[1] ?? '']; next[i] = v; set({ models: next[1] || next[0] ? next : [] }); }} />
                                {spec && <button className="btn" disabled={tests[key] === 'running'} onClick={() => test('model', spec)}>Test</button>}
                                <Result t={tests[key]} />
                            </div>);
                    })}
                    {info.providers.every(p => !p.ready) && <p className="notice rd__notice" role="status">No provider is connected yet. <Link to="/app/settings">Add a key in Settings</Link> to use vision models.</p>}
                </section>)}

            {usesModels && (
                <details className="rd__adv">
                    <summary>Advanced</summary>
                    {mode === 'escalate' && (
                        <label className="rd__field">Accept the local reading when its confidence is at least {pct(threshold)}
                            <input type="range" min={50} max={99} step={1} value={Math.round(threshold * 100)} onChange={e => set({ escalate_below: Number(e.target.value) / 100 })} aria-valuetext={pct(threshold)} />
                            <span className="rd__sub">Higher sends more pages to the vision models: more accurate, costs more. Tesseract scores about 90 to 95% on clean print and 40 to 50% on handwriting.</span>
                        </label>)}
                    <label className="rd__field rd__field--narrow">Token cap per document <span className="muted">(0 = no cap)</span>
                        <input type="number" min={0} step={1000} value={draft.token_cap ?? 0} onChange={e => set({ token_cap: Math.max(0, Number(e.target.value) || 0) })} />
                        <span className="rd__sub">Once a document has used this many model tokens, doubtful pages keep their local reading and are flagged for you instead.</span>
                    </label>
                </details>)}

            <section aria-labelledby="rd-summary">
                <h2 className="section-title" id="rd-summary">What this means</h2>
                <ul className="rd__summary">{summary.map(l => <li key={l}>{l}</li>)}</ul>
                {view.plan.notes.length > 0 && <div className="notice rd__notice" role="status"><b>Heads up</b><ul>{view.plan.notes.map(n => <li key={n}>{n}</li>)}</ul></div>}
            </section>

            <div className="rd__actions">
                <button className="btn btn--primary" onClick={save} disabled={busy || !dirty}>{busy ? 'Saving' : 'Save settings'}</button>
                <button className="btn" onClick={() => { setDraft(view.settings); setSaved(false); setError(''); }} disabled={busy || !dirty}>Discard changes</button>
                {saved && !dirty && <span className="rd__result rd__result--ok" role="status">Saved. New uploads will use these settings.</span>}
            </div>
        </main>
    );
}
