import { useEffect, useState, type ReactElement } from 'react';
import { getTheme, onThemeChange, setTheme, type ThemeChoice } from '../lib/theme';

const OPTIONS: { value: ThemeChoice; label: string; icon: ReactElement }[] = [
    { value: 'light', label: 'Light', icon: <><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" /></> },
    { value: 'system', label: 'Match system', icon: <><rect x="2" y="2.5" width="12" height="8" rx="1.2" /><path d="M5.5 13.5h5M8 10.5v3" /></> },
    { value: 'dark', label: 'Dark', icon: <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" /> },
];

/** Light, match system, dark: one control, in the top bar and on the landing page. */
export function ThemeToggle() {
    const [choice, setChoice] = useState<ThemeChoice>(getTheme);
    useEffect(() => onThemeChange(setChoice), []);
    return (
        <div className="theme-toggle" role="group" aria-label="Colour theme">
            {OPTIONS.map(o => (
                <button key={o.value} type="button" aria-pressed={choice === o.value} aria-label={o.label} title={o.label} onClick={() => setTheme(o.value)}>
                    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{o.icon}</svg>
                </button>))}
        </div>
    );
}
