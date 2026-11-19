import type { Finding } from '../api';

const GROUPS: { sev: Finding['severity'][]; title: string; tone: string }[] = [
    { sev: ['error'], title: 'Errors', tone: 'error' },
    { sev: ['warn'], title: 'Warnings', tone: 'warn' },
    { sev: ['info'], title: 'Notes', tone: 'info' },
];

/** What the rules found, most serious first. Click one to see the value it is about. */
export function FindingsTab({ findings, onOpen }: { findings: Finding[]; onOpen: (f: Finding) => void }) {
    if (findings.length === 0) return <p className="empty">No findings. Every rule passed.</p>;
    return (
        <div className="rv-findings">
            {GROUPS.map(g => {
                const items = findings.filter(f => g.sev.includes(f.severity));
                if (!items.length) return null;
                return (
                    <section key={g.title}>
                        <h2 className={`rv-findings__head rv-findings__head--${g.tone}`}>{g.title} <span>{items.length}</span></h2>
                        {items.map((f, i) => (
                            <button key={i} className={`finding finding--${f.severity}`} onClick={() => onOpen(f)} disabled={!f.field}>
                                <span>{f.detail}</span>
                            </button>))}
                    </section>);
            })}
        </div>
    );
}
