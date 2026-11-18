import { useState } from 'react';
import type { Cell } from '../api';
import { cellKey, display, FLAGGED, rowId, type Value } from './helpers';

function GridCell({ id, cell, selected, onFocus, onSave }: { id: string; cell: Cell; selected: boolean; onFocus: () => void; onSave: (v: Value) => void }) {
    const [edit, setEdit] = useState<string | null>(null);
    const flagged = FLAGGED.has(cell.status);
    const tip = [cell.reason, cell.alternatives.length ? `Other reading: ${cell.alternatives.join(' / ')}` : ''].filter(Boolean).join('. ');
    return (
        <td id={id} className={`${flagged ? 'is-flag ' : ''}${cell.status === 'corrected' ? 'is-done ' : ''}${selected ? 'is-on' : ''}`} title={tip || undefined}>
            <input aria-label={cell.label ?? 'Cell'} value={edit ?? display(cell.value)} onFocus={onFocus} spellCheck={false}
                onChange={e => setEdit(e.target.value)}
                onBlur={() => { if (edit !== null && edit !== display(cell.value)) onSave(edit); setEdit(null); }}
                onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { setEdit(null); e.currentTarget.blur(); } }} />
        </td>
    );
}

interface Props {
    doc: number; name: string; rows: Record<string, Cell>[]; columns?: string[];
    selectedKey: string | null; onSelect: (key: string, cell: Cell) => void; onSave: (key: string, v: Value) => void;
}

/** A table whose cells can all be edited in place. Flagged cells are tinted; hover shows why. */
export function TableGrid({ doc, name, rows, columns, selectedKey, onSelect, onSave }: Props) {
    if (rows.length === 0) return <p className="empty">No rows were found.</p>;
    const keys = Object.keys(rows[0]);
    return (
        <div className="gridwrap">
            <table className="grid editable">
                <thead><tr><th className="grid__n" scope="col"><span className="sr-only">Row</span></th>{keys.map((k, i) => <th key={k} scope="col">{columns?.[i] || (k.startsWith('col_') ? '' : k.replace(/_/g, ' '))}</th>)}</tr></thead>
                <tbody>{rows.map((row, r) => (
                    <tr key={r}><th className="grid__n" scope="row">{r + 1}</th>
                        {keys.map(c => {
                            const key = cellKey(name, r, c);
                            return row[c] ? <GridCell key={c} id={rowId(doc, key)} cell={row[c]} selected={selectedKey === key} onFocus={() => onSelect(key, row[c])} onSave={v => onSave(key, v)} /> : <td key={c} />;
                        })}
                    </tr>))}
                </tbody>
            </table>
        </div>
    );
}
