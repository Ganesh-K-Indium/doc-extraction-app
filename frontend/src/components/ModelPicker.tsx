import { useState } from 'react';
import type { Provider } from '../api';

interface Props {
    label: string;
    value: string;
    /** What is used when nothing is chosen (the server's default), shown in the first option. */
    fallback?: string;
    providers: Provider[];
    onChange: (spec: string) => void;
}

/** Choose a model from the connected providers, keep the server default, or type any other `provider:model`. */
export function ModelPicker({ label, value, fallback, providers, onChange }: Props) {
    const known = providers.some(p => p.models.includes(value));
    const [other, setOther] = useState(value !== '' && !known);
    const selected = other ? '__other' : value;
    return (
        <div className="mp">
            <label className="rd__field">{label}
                <select value={selected} onChange={e => {
                    if (e.target.value === '__other') { setOther(true); onChange(''); } else { setOther(false); onChange(e.target.value); }
                }}>
                    <option value="">{fallback ? `Server default (${fallback})` : 'Server default'}</option>
                    {providers.filter(p => p.models.length > 0).map(p => (
                        <optgroup key={p.id} label={p.ready ? p.label : `${p.label} (add its key in Settings first)`}>
                            {p.models.map(m => <option key={m} value={m} disabled={!p.ready}>{m.replace(/^[a-z]+:/, '')}</option>)}
                        </optgroup>))}
                    <option value="__other">Another model…</option>
                </select>
            </label>
            {other && (
                <label className="rd__field">Model name
                    <input value={value} placeholder="provider:model, for example ollama:llava" spellCheck={false} onChange={e => onChange(e.target.value.trim())} />
                </label>)}
        </div>
    );
}
