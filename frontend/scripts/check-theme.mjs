// Checks theme.css: the dark values agree in both places, every token used is defined, no colour literals live outside the
// theme, and every text pair meets WCAG AA in both themes. Run with: npm run check:theme
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const src = new URL('../src/', import.meta.url).pathname;
const css = readFileSync(join(src, 'theme.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const decls = body => Object.fromEntries([...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]));
const lightBody = css.match(/:root\s*\{([\s\S]*?)\n\}/)[1];
const mediaBody = css.match(/@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{([\s\S]*?)\n\s*\}\s*\}/)[1];
const darkBody = css.match(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/)[1];
const light = decls(lightBody), dark = { ...light, ...decls(darkBody) }, media = decls(mediaBody), darkOnly = decls(darkBody);

let failed = 0;
const fail = msg => { failed++; console.log('  FAIL', msg); };

// 1. the two dark blocks are the same
console.log('Dark blocks');
for (const k of new Set([...Object.keys(media), ...Object.keys(darkOnly)])) if (media[k] !== darkOnly[k]) fail(`${k} differs: system dark "${media[k]}" vs chosen dark "${darkOnly[k]}"`);
for (const k of Object.keys(darkOnly)) if (!(k in light)) fail(`${k} is only defined for dark`);

// 2. every token used is defined; 3. no colour literals outside the theme
console.log('Usage');
const files = [];
(function walk(d) { for (const f of readdirSync(d)) { const p = join(d, f); statSync(p).isDirectory() ? walk(p) : /\.(css|tsx?|html)$/.test(f) && files.push(p); } })(src);
const allowed = new Set(['--min-font-size', '--min-font-size-inv', '--text-scale-factor', '--font-height', '--scale-x', '--rotate', '--scale-factor', '--total-scale-factor']);   // set by pdf.js
const local = new Set();                                                                                                           // set by a component's own rule or inline style, with a layout value
for (const f of files) for (const m of readFileSync(f, 'utf8').matchAll(/(--[\w-]+)\s*:/g)) if (!f.endsWith('theme.css')) local.add(m[1]);
for (const f of files) for (const m of readFileSync(f, 'utf8').matchAll(/\[\s*'(--[\w-]+)'\s+as\s+string\s*\]/g)) local.add(m[1]);
for (const f of files) {
    if (f.endsWith('theme.css')) continue;
    const text = readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of text.matchAll(/var\((--[\w-]+)/g)) if (!(m[1] in light) && !allowed.has(m[1]) && !local.has(m[1])) fail(`${f.replace(src, '')}: ${m[1]} is not defined in theme.css`);
    for (const m of text.matchAll(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/g)) fail(`${f.replace(src, '')}: colour literal ${m[0]}`);
}

// the browser's theme-color meta tags cannot use CSS variables: they must equal the canvas of each theme
console.log('index.html');
const html = readFileSync(new URL('../index.html', import.meta.url).pathname, 'utf8');
for (const [scheme, t] of [['light', light], ['dark', dark]]) {
    const m = html.match(new RegExp(`<meta name="theme-color" content="(#[0-9a-fA-F]{6})" media="\\(prefers-color-scheme: ${scheme}\\)"`));
    if (!m) fail(`index.html has no theme-color meta for ${scheme}`);
    else if (m[1].toLowerCase() !== t['--canvas'].toLowerCase()) fail(`index.html theme-color for ${scheme} is ${m[1]} but --canvas is ${t['--canvas']}`);
}
const strayHtml = html.replace(/<meta name="theme-color"[^>]*>/g, '').match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g);
if (strayHtml) fail(`index.html: colour literal ${strayHtml[0]}`);

// 4. contrast
const rgb = h => [1, 3, 5].map(i => parseInt(h.replace('#', '').slice(i - 1, i + 1), 16));
const lum = h => { const [r, g, b] = rgb(h).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + .05) / (y + .05); };
const mix = (fg, bg, a) => '#' + rgb(fg).map((v, i) => Math.round(v * a + rgb(bg)[i] * (1 - a)).toString(16).padStart(2, '0')).join('');
const share = (t, k) => parseInt(t[k].match(/(\d+)%/)[1], 10) / 100;
const PAIRS = [
    ['--text', '--canvas', 7], ['--text', '--surface', 7], ['--text', '--raised', 7], ['--text', '--well', 7],
    ['--text-2', '--canvas', 4.5], ['--text-2', '--surface', 4.5], ['--text-2', '--raised', 4.5], ['--text-2', '--well', 4.5],
    ['--accent', '--canvas', 4.5], ['--accent', '--surface', 4.5], ['--accent', '--raised', 4.5], ['--on-accent', '--accent', 4.5],
    ['--ok', '--ok-bg', 4.5], ['--ok', '--surface', 4.5], ['--flag', '--flag-bg', 4.5], ['--flag', '--surface', 4.5], ['--on-flag', '--flag', 4.5],
    ['--warn', '--warn-bg', 4.5], ['--warn', '--surface', 4.5], ['--text', '--ok-bg', 7], ['--text', '--flag-bg', 7],
];
for (const [name, t] of [['Light', light], ['Dark', dark]]) {
    console.log(name + ' contrast');
    for (const [a, b, need] of PAIRS) { const r = ratio(t[a], t[b]); if (r < need) fail(`${a} on ${b} is ${r.toFixed(2)}:1, needs ${need}`); }
    const edge = ratio(mix(t['--text'], t['--surface'], share(t, '--line-strong')), t['--surface']);
    if (edge < 2.5) fail(`--line-strong is only ${edge.toFixed(2)}:1 on --surface (an input's edge needs to be seen)`);
    console.log(`  accent ${ratio(t['--accent'], t['--surface']).toFixed(1)}:1, text ${ratio(t['--text'], t['--surface']).toFixed(1)}:1, input edge ${edge.toFixed(1)}:1`);
}
console.log(failed ? `\n${failed} problem(s)` : '\nTheme is consistent.');
process.exit(failed ? 1 : 0);
