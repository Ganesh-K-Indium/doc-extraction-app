import { useCallback, useEffect, useRef, useState } from 'react';

const KEY = 'pagewise.panelWidth';
const MIN = 360;

function stored(): number {
    try { const n = Number(window.localStorage.getItem(KEY)); return n >= MIN ? n : 520; } catch { return 520; }
}

/** Two panes with a draggable divider. The right pane's width is remembered. Keyboard: focus the divider, then arrows. */
export function Split({ left, right, className = '', view }: { left: React.ReactNode; right: React.ReactNode; className?: string; view?: 'left' | 'right' }) {
    const [width, setWidth] = useState(stored);
    const root = useRef<HTMLDivElement>(null);
    const dragging = useRef(false);

    const clamp = useCallback((w: number) => {
        const total = root.current?.clientWidth ?? 1400;
        return Math.max(MIN, Math.min(w, total - 320));
    }, []);
    const save = (w: number) => { try { window.localStorage.setItem(KEY, String(Math.round(w))); } catch { /* storage unavailable */ } };

    useEffect(() => {
        const move = (e: PointerEvent) => {
            if (!dragging.current || !root.current) return;
            setWidth(clamp(root.current.getBoundingClientRect().right - e.clientX));
        };
        const up = () => { if (dragging.current) { dragging.current = false; document.body.classList.remove('is-resizing'); setWidth(w => { save(w); return w; }); } };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    }, [clamp]);

    return (
        <div ref={root} className={`split ${className}`} data-view={view} style={{ ['--panel-w' as string]: `${width}px` }}>
            <section className="split__left">{left}</section>
            <div className="split__handle" role="separator" aria-orientation="vertical" aria-label="Resize the panels" aria-valuenow={width} tabIndex={0}
                onPointerDown={e => { e.preventDefault(); dragging.current = true; document.body.classList.add('is-resizing'); }}
                onKeyDown={e => {
                    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                        const next = clamp(width + (e.key === 'ArrowLeft' ? 32 : -32));
                        setWidth(next); save(next); e.preventDefault();
                    }
                }} />
            <aside className="split__right">{right}</aside>
        </div>
    );
}
