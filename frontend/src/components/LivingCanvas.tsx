import { useEffect, useRef } from 'react';

/**
 * The landing page's backdrop: a fine grid of dots that brightens softly around the cursor, under a faint glow that follows it.
 * Nothing moves apart or jumps. Left alone, a very slow light drifts across the grid.
 *
 * It paints with the theme's own colours (read from CSS), pauses when off screen or the tab is hidden, and under
 * "reduce motion" draws one still frame.
 */

const STEP = 30;

export function LivingCanvas() {
    const ref = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = ref.current;
        const host = canvas?.parentElement;
        const ctx = canvas?.getContext('2d');
        if (!canvas || !host || !ctx) return;
        const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        let W = 0, H = 0;
        // Placeholders until the theme's colours are read from CSS, a few lines below.
        let ink = { dot: 'gray', accent: 'royalblue' };
        let mouse: { x: number; y: number } | null = null;
        const light = { x: 0, y: 0, k: 0 };          // where the light is, and how strongly (0 to 1)
        let raf = 0, visible = true;

        const colours = () => {
            const cs = getComputedStyle(canvas);
            ink = { dot: cs.getPropertyValue('--text-2').trim() || ink.dot, accent: cs.getPropertyValue('--accent').trim() || ink.accent };
        };
        const size = () => {
            const r = host.getBoundingClientRect();
            const dpr = Math.min(window.devicePixelRatio || 1, 2);
            W = Math.max(1, Math.round(r.width)); H = Math.max(1, Math.round(r.height));
            canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        };

        const frame = (now: number) => {
            const R = Math.max(150, Math.min(W, H) * 0.28);
            // The light follows the cursor with a little lag; with no cursor it drifts slowly on its own.
            const tx = mouse ? mouse.x : W * (0.72 + 0.12 * Math.sin(now * 0.00012));
            const ty = mouse ? mouse.y : H * (0.5 + 0.18 * Math.cos(now * 0.00009));
            const tk = mouse ? 1 : 0.55;
            light.x += (tx - light.x) * 0.08; light.y += (ty - light.y) * 0.08; light.k += (tk - light.k) * 0.05;

            ctx.clearRect(0, 0, W, H);
            const glow = ctx.createRadialGradient(light.x, light.y, 0, light.x, light.y, R * 1.7);
            glow.addColorStop(0, ink.accent); glow.addColorStop(1, 'transparent');
            ctx.globalAlpha = 0.08 * light.k; ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);

            ctx.fillStyle = ink.dot;
            for (let y = STEP / 2; y < H; y += STEP) {
                for (let x = STEP / 2; x < W; x += STEP) {
                    const d = Math.hypot(x - light.x, y - light.y) / R;
                    const near = d < 1 ? (1 - d) * (1 - d) * light.k : 0;
                    ctx.globalAlpha = 0.22 + 0.5 * near;
                    const s = 1.6 + 1.4 * near;
                    ctx.fillRect(x - s / 2, y - s / 2, s, s);
                }
            }
            ctx.globalAlpha = 1;
            raf = !still && visible && !document.hidden ? requestAnimationFrame(frame) : 0;
        };
        const start = () => { if (!raf && !still && visible && !document.hidden) raf = requestAnimationFrame(frame); };

        const move = (e: PointerEvent) => { const r = host.getBoundingClientRect(); mouse = { x: e.clientX - r.left, y: e.clientY - r.top }; };
        const leave = () => { mouse = null; };

        const ro = new ResizeObserver(() => { size(); if (still) frame(performance.now()); });
        ro.observe(host);
        const io = new IntersectionObserver(([en]) => { visible = en.isIntersecting; if (visible) start(); }, { threshold: 0 });
        io.observe(host);
        const onVis = () => { if (!document.hidden) start(); };
        const repaint = () => { colours(); if (still) frame(performance.now()); };
        const mo = new MutationObserver(repaint);
        mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        const mq = window.matchMedia('(prefers-color-scheme: dark)');
        mq.addEventListener('change', repaint);

        colours(); size();
        if (!still) {
            host.addEventListener('pointermove', move); host.addEventListener('pointerleave', leave);
            document.addEventListener('visibilitychange', onVis);
        }
        light.x = W * 0.72; light.y = H * 0.5; light.k = 0.55;
        if (still) frame(performance.now()); else start();

        return () => {
            cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); mo.disconnect(); mq.removeEventListener('change', repaint);
            host.removeEventListener('pointermove', move); host.removeEventListener('pointerleave', leave);
            document.removeEventListener('visibilitychange', onVis);
        };
    }, []);

    return <canvas ref={ref} className="lp-canvas" aria-hidden="true" />;
}
