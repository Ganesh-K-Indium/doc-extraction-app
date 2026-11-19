import { useEffect, useRef, type ReactNode } from 'react';

interface Props { label: ReactNode; children: ReactNode; align?: 'left' | 'right'; disabled?: boolean; title?: string }

/** A small dropdown that closes when a choice is made, when you click elsewhere, or on Escape. */
export function Menu({ label, children, align = 'right', disabled, title }: Props) {
    const ref = useRef<HTMLDetailsElement>(null);
    useEffect(() => {
        const close = (e: Event) => { const d = ref.current; if (d?.open && !(e.target instanceof Node && d.contains(e.target))) d.open = false; };
        const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && ref.current?.open) { ref.current.open = false; ref.current.querySelector('summary')?.focus(); } };
        document.addEventListener('mousedown', close);
        document.addEventListener('keydown', esc);
        return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
    }, []);
    return (
        <details className="menu" ref={ref}>
            <summary className="btn btn--tiny" aria-disabled={disabled} title={title} onClick={e => { if (disabled) e.preventDefault(); }}>{label}</summary>
            <div className={`menu__list menu__list--${align}`} onClick={e => { if ((e.target as HTMLElement).closest('button') && ref.current) ref.current.open = false; }}>{children}</div>
        </details>
    );
}
