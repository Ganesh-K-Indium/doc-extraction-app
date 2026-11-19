import { useLayoutEffect, useRef, useState } from 'react';
import type { Cell } from '../api';
import { altIntro, altText, display, FLAGGED, labelFor, rowId, stateOf, typedLike, type Value } from './helpers';
import { Tick } from './Tick';

/** The control that fits the value: tick box, choice list, checklist, or a text box that grows with its content. */
function Control({ id, cell, onSave }: { id: string; cell: Cell; onSave: (v: Value) => void }) {
    const [edit, setEdit] = useState<string | null>(null);   // null = show the stored value
    const area = useRef<HTMLTextAreaElement>(null);
    const text = edit ?? display(cell.value);
    useLayoutEffect(() => { const el = area.current; if (el) { el.style.height = 'auto'; el.style.height = `${el.scrollHeight}px`; } }, [text]);

    if (typeof cell.value === 'boolean' || cell.type === 'checkbox') {
        return (
            <label className="toggle"><input id={id} type="checkbox" checked={cell.value === true} onChange={e => onSave(e.target.checked)} />
                <span>{cell.value === null ? 'Not read' : cell.value ? 'Yes' : 'No'}</span></label>
        );
    }
    if (cell.type === 'enum' && cell.options?.length && !Array.isArray(cell.value)) {
        const current = typeof cell.value === 'string' ? cell.value : '';
        return (
            <select id={id} className="field__select" value={current} onChange={e => onSave(e.target.value)}>
                <option value="">Not selected</option>
                {current && !cell.options.includes(current) && <option value={current}>{current}</option>}
                {cell.options.map(o => <option key={o} value={o}>{o}</option>)}
            </select>
        );
    }
    if (cell.type === 'multi_enum' && cell.options?.length) {
        const chosen = Array.isArray(cell.value) ? cell.value : [];
        return (
            <div id={id} className="checks" role="group">
                {cell.options.map(o => (
                    <label key={o} className="checks__item"><input type="checkbox" checked={chosen.includes(o)}
                        onChange={e => onSave(e.target.checked ? [...chosen, o] : chosen.filter(x => x !== o))} />{o}</label>))}
            </div>
        );
    }
    const commit = () => { if (edit !== null && edit !== display(cell.value)) onSave(Array.isArray(cell.value) ? edit.split(',').map(x => x.trim()).filter(Boolean) : edit); setEdit(null); };
    return (
        <textarea ref={area} id={id} className="field__input" rows={1} value={text} spellCheck={false}
            onChange={e => setEdit(e.target.value)} onBlur={commit}
            onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.blur(); }
                if (e.key === 'Escape') { setEdit(null); e.currentTarget.blur(); }
            }} />
    );
}

interface Props {
    doc: number; name: string; cell: Cell; selected: boolean;
    onSelect: () => void; onSave: (v: Value) => void; onJump: () => void;
}

/** One value. A value that is fine takes one line with a small tick; a value that needs checking opens its reasons and
 *  alternatives right under it; the selected value shows where it came from. Quiet rows make a long form skimmable. */
export function FieldRow({ doc, name, cell, selected, onSelect, onSave, onJump }: Props) {
    const st = stateOf(cell);
    const flagged = FLAGGED.has(cell.status);
    const hasValue = cell.value !== null && cell.value !== undefined;
    const inputId = `in-${doc}-${name}`;
    const detail = flagged || selected;
    return (
        <div id={rowId(doc, name)} className={`rf rf--${st.key}${selected ? ' rf--on' : ''}`} onClick={onSelect} onFocus={onSelect}>
            <label className="rf__label" htmlFor={inputId}>{labelFor(name, cell)}</label>
            <div className="rf__control"><Control id={inputId} cell={cell} onSave={onSave} /></div>
            <div className="rf__state">
                {st.key === 'done' && <span className="rf__tick" title={st.text}><Tick /><span className="sr-only">{st.text}</span></span>}
                {st.key === 'quiet' && <span className="rf__quiet" title={st.text}>{cell.status === 'empty' ? 'Blank' : 'One reader'}</span>}
            </div>
            {detail && (
                <div className="rf__detail">
                    {flagged && <span className="rf__chip">{st.text}</span>}
                    {flagged && cell.alternatives.length > 0 && (
                        <span className="rf__alt">{altIntro(cell)}{' '}
                            {cell.alternatives.map(a => <button key={a} className="link" onClick={e => { e.stopPropagation(); onSave(typedLike(cell, a)); }}>use “{altText(cell, a)}”</button>)}
                        </span>)}
                    {flagged && cell.alternatives.length === 0 && cell.reason && <span className="rf__alt">{cell.reason}</span>}
                    {!flagged && <span className="rf__src">{st.text}</span>}
                    {flagged && hasValue && <button className="btn btn--tiny" onClick={e => { e.stopPropagation(); onSave(cell.value as Value); }}>Confirm</button>}
                    <button className="link rf__page" onClick={e => { e.stopPropagation(); onJump(); }} aria-label={`Show page ${cell.page} of the source`}>page {cell.page}</button>
                </div>)}
        </div>
    );
}
