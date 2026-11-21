import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { PdfViewer, type Overlay, type PdfViewerHandle } from '../components/PdfViewer';

interface Props {
    url: string; headers?: Record<string, string>; overlays: Overlay[];
    viewerRef: RefObject<PdfViewerHandle | null>; visible: number;
    onVisiblePage: (n: number) => void; onError: (m: string) => void;
}

/** The source document with a small toolbar: page, zoom, fit to width. Opens fitted to the width of the pane. */
export function PdfPane({ url, headers, overlays, viewerRef, visible, onVisiblePage, onError }: Props) {
    const box = useRef<HTMLDivElement>(null);
    const [scale, setScale] = useState(1.1);
    const [pageWidth, setPageWidth] = useState(612);
    const [count, setCount] = useState(0);
    const width = useRef(612);          // the page's own width, for refitting
    const zoomed = useRef(false);       // once someone zooms by hand, the page is no longer refitted for them

    const fit = useCallback((w: number) => {
        const available = box.current?.clientWidth || 0;
        if (!available) return;         // the pane is hidden (a small screen showing the review): fit when it appears
        setScale(Math.max(0.4, Math.min(2.5, (available - (available < 700 ? 20 : 48)) / w)));
    }, []);
    // a pane that was hidden, or whose window changed size, is fitted again until the person zooms for themselves
    useEffect(() => {
        const el = box.current;
        if (!el || typeof ResizeObserver === 'undefined') return;
        let last = el.clientWidth;
        const watch = new ResizeObserver(() => {
            const now = el.clientWidth;
            if (now > 0 && now !== last) { last = now; if (!zoomed.current) fit(width.current); }
        });
        watch.observe(el);
        return () => watch.disconnect();
    }, [fit]);
    const go = (n: number) => viewerRef.current?.scrollToPage(Math.min(Math.max(1, n), Math.max(1, count)), true);

    return (
        <div className="pdfpane" ref={box}>
            <div className="pdftools" role="toolbar" aria-label="Document view">
                <button className="btn btn--tiny" onClick={() => go(visible - 1)} disabled={visible <= 1} aria-label="Previous page">‹</button>
                <span className="pdftools__page">Page {visible}{count ? ` of ${count}` : ''}</span>
                <button className="btn btn--tiny" onClick={() => go(visible + 1)} disabled={!count || visible >= count} aria-label="Next page">›</button>
                <span className="pdftools__gap" />
                <button className="btn btn--tiny" onClick={() => { zoomed.current = true; setScale(s => Math.max(0.4, +(s - 0.15).toFixed(2))); }} aria-label="Zoom out">−</button>
                <span className="pdftools__zoom">{Math.round(scale * 100)}%</span>
                <button className="btn btn--tiny" onClick={() => { zoomed.current = true; setScale(s => Math.min(3, +(s + 0.15).toFixed(2))); }} aria-label="Zoom in">+</button>
                <button className="btn btn--tiny" onClick={() => { zoomed.current = false; fit(pageWidth); }}>Fit width</button>
            </div>
            <div className="pdfpane__scroll">
                <PdfViewer ref={viewerRef} url={url} headers={headers} scale={scale} overlays={overlays}
                    onPageCount={(n, w) => { setCount(n); setPageWidth(w); width.current = w; fit(w); }} onVisiblePage={onVisiblePage} onError={onError} />
            </div>
        </div>
    );
}
