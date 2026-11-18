// The workspace the person was last in, so the workspaces screen can offer to continue there.
// Per-browser convenience only: storage can be blocked or empty, so every access is guarded.
const KEY = 'pagewise.lastWorkspace';

export function getLastWorkspace(): string | null {
    try { return window.localStorage.getItem(KEY); } catch { return null; }
}
export function setLastWorkspace(id: string): void {
    try { window.localStorage.setItem(KEY, id); } catch { /* storage unavailable */ }
}
export function clearLastWorkspace(id: string): void {
    try { if (window.localStorage.getItem(KEY) === id) window.localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
}
