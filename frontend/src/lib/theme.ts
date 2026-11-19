/** Light, dark, or follow the system. The choice is kept in this browser and applied on <html>; theme.css does the rest. */
export type ThemeChoice = 'system' | 'light' | 'dark';

const KEY = 'pagewise-theme';
const listeners = new Set<(c: ThemeChoice) => void>();

export function getTheme(): ThemeChoice {
    try {
        const v = localStorage.getItem(KEY);
        return v === 'light' || v === 'dark' ? v : 'system';
    } catch {
        return 'system';              // storage can be blocked: the system setting still works
    }
}

/** Tell the browser's own chrome (address bar, overscroll) the colour of the canvas. */
function syncChrome() {
    const canvas = getComputedStyle(document.documentElement).getPropertyValue('--canvas').trim();
    if (!canvas) return;
    document.querySelectorAll('meta[name="theme-color"]').forEach(m => m.setAttribute('content', canvas));
}

export function applyTheme(choice: ThemeChoice) {
    const root = document.documentElement;
    if (choice === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', choice);
    syncChrome();
}

export function setTheme(choice: ThemeChoice) {
    try {
        if (choice === 'system') localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, choice);
    } catch { /* the choice still applies for this visit */ }
    applyTheme(choice);
    listeners.forEach(l => l(choice));
}

/** Follow changes made elsewhere: another tab, or the system switching while the choice is "system". */
export function onThemeChange(fn: (c: ThemeChoice) => void): () => void {
    listeners.add(fn);
    const storage = (e: StorageEvent) => { if (e.key === KEY || e.key === null) { const c = getTheme(); applyTheme(c); fn(c); } };
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const system = () => { if (getTheme() === 'system') { syncChrome(); fn('system'); } };
    window.addEventListener('storage', storage);
    media.addEventListener('change', system);
    return () => { listeners.delete(fn); window.removeEventListener('storage', storage); media.removeEventListener('change', system); };
}
