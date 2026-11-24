import type { Finding } from '../api';

const GROUPS: { sev: Finding['severity'][]; title: string; tone: string }[] = [
    { sev: ['error'], title: 'Errors', tone: 'error' },
    { sev: ['warn'], title: 'Warnings', tone: 'warn' },
    { sev: ['info'], title: 'Notes', tone: 'info' },
];

const RULE: Record<string, string> = {
    npi_check_digit: 'NPI', icd10_format: 'ICD-10', cpt_format: 'CPT', dob: 'Birth date', date_order: 'Dates', dose_unit: 'Dose', totals_mismatch: 'Totals',
    required_missing: 'Required', format: 'Format', needs_review: 'Check',
};

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
                                {RULE[f.rule] && <b className="finding__rule">{RULE[f.rule]}</b>}<span>{f.detail}</span>
                            </button>))}
                    </section>);
            })}
        </div>
    );
}
