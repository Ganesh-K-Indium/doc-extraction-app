import { useCallback, useEffect, useState } from 'react';
import { engines, settings, type EngineTest, type ProviderSettings, type ProvidersView, type SettingField } from '../api';

const STATUS: Record<string, string> = { ready: 'Ready', needs_setup: 'Needs setup', blocked: 'Switched off' };

function FieldRow({ f, value, onChange, onRemove, disabled }: { f: SettingField; value: string; onChange: (v: string) => void; onRemove: () => void; disabled: boolean }) {
    const [replacing, setReplacing] = useState(false);
    const id = `f-${f.name}`;
    if (f.set && !replacing && !value) {
        return (
            <div className="st__field">
                <span className="st__label">{f.label}</span>
                <span className="st__saved"><code>{f.preview}</code>
                    <span className="muted"> {f.source === 'saved' ? 'saved in this app' : 'set by the server'}</span></span>
                {!disabled && <span className="st__links">
                    <button className="link" onClick={() => setReplacing(true)}>Replace</button>
                    {f.source === 'saved' && <button className="link" onClick={onRemove}>Remove</button>}
                </span>}
            </div>);
    }
    return (
        <div className="st__field">
            <label htmlFor={id} className="st__label">{f.label}</label>
            <input id={id} type={f.secret ? 'password' : 'text'} autoComplete="off" spellCheck={false} disabled={disabled} value={value}
                placeholder={f.kind === 'url' ? 'https://…' : f.secret ? 'Paste the key' : ''} onChange={e => onChange(e.target.value)} />
            {f.help && <span className="st__help">{f.help}</span>}
        </div>);
}

function ProviderCard({ p, locked, onSaved }: { p: ProviderSettings; locked: boolean; onSaved: (p: ProviderSettings) => void }) {
    const [vals, setVals] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
    const [test, setTest] = useState<EngineTest | 'running' | null>(null);
    const typed = Object.values(vals).some(v => v.trim());

    const send = async (values: Record<string, string | null>, done: string) => {
        setBusy(true); setMsg(null);
        try { onSaved(await settings.save(p.id, values)); setVals({}); setMsg({ ok: true, text: done }); }
        catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
        finally { setBusy(false); }
    };
    const model = p.models[0] ?? '';
    const runTest = async () => {
        setTest('running');
        try { setTest(await engines.test('model', model)); } catch (e) { setTest({ ok: false, error: (e as Error).message }); }
    };

    return (
        <section className="st__card" aria-labelledby={`p-${p.id}`}>
            <header className="st__head">
                <h2 id={`p-${p.id}`}>{p.label}</h2>
                <span className={`rd__chip rd__chip--${p.status === 'ready' ? 'ok' : 'off'}`}>{STATUS[p.status]}</span>
                <span className="muted st__where">{p.cloud ? 'Cloud: pages are sent to the provider' : 'Runs on your own hardware'}</span>
            </header>
            {p.status === 'blocked' && <p className="hint">{p.hint}</p>}
            {p.fields.map(f => <FieldRow key={f.name} f={f} value={vals[f.name] ?? ''} disabled={locked || busy}
                onChange={v => setVals(s => ({ ...s, [f.name]: v }))} onRemove={() => send({ [f.name]: null }, 'Removed. The server setting, if any, is used again.')} />)}
            <div className="st__actions">
                {!locked && <button className="btn btn--primary" disabled={busy || !typed}
                    onClick={() => send(Object.fromEntries(Object.entries(vals).filter(([, v]) => v.trim()).map(([k, v]) => [k, v.trim()])), 'Saved. It is stored encrypted.')}>{busy ? 'Saving' : 'Save'}</button>}
                {p.ready && model && <button className="btn" disabled={test === 'running'} onClick={runTest}>Test connection</button>}
                {msg && <span className={msg.ok ? 'rd__result rd__result--ok' : 'rd__result rd__result--bad'} role="status">{msg.text}</span>}
                {test && test !== 'running' && <span className={test.ok ? 'rd__result rd__result--ok' : 'rd__result rd__result--bad'} role="status">
                    {test.ok ? `Connected: ${model} answered in ${test.seconds}s (${(test.tokens ?? 0).toLocaleString()} tokens).` : test.error}</span>}
                {test === 'running' && <span className="rd__result muted" role="status">Contacting {p.label}…</span>}
            </div>
        </section>);
}

export default function SettingsPage() {
    const [view, setView] = useState<ProvidersView | null>(null);
    const [error, setError] = useState('');
    const load = useCallback(() => settings.providers().then(setView).catch(e => setError(e.message)), []);
    useEffect(() => { load(); }, [load]);
    const replace = (p: ProviderSettings) => setView(v => v && { ...v, providers: v.providers.map(x => x.id === p.id ? p : x) });

    if (error) return <main className="list"><p className="notice notice--error" role="alert">{error}</p></main>;
    if (!view) return <main className="list"><p className="muted">Loading settings</p></main>;
    return (
        <main className="list st">
            <h1 className="page-title">Settings</h1>
            <p className="lede">Connect the model providers this server can use. Keys you enter here are stored encrypted and are never shown again, only their last four characters. Which models read a document is chosen per workspace under Reading engines.</p>
            {view.local_only && <p className="notice st__notice" role="status"><b>Local-only mode.</b> Cloud providers are switched off on this server, so nothing can leave it. Models on your own hardware still work.</p>}
            {view.locked && <p className="notice st__notice" role="status"><b>Settings are locked.</b> Whoever runs this server manages these through its environment, so they are shown but cannot be changed here.</p>}
            {view.encryption === 'unavailable' && !view.locked && <p className="notice notice--error st__notice" role="alert">This server cannot encrypt saved keys right now, so keys cannot be saved here. Set them as environment variables instead.</p>}
            <div className="st__cards">{view.providers.map(p => <ProviderCard key={p.id} p={p} locked={view.locked || view.encryption === 'unavailable'} onSaved={replace} />)}</div>
        </main>
    );
}
