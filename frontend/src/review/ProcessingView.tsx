import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

interface Props {
    wid: string;
    status: 'queued' | 'processing';
    stage: string | null;
    progress: { done: number; total: number };
    createdAt: string;
}

/** The steps a file goes through, in order, as the server reports them. `stage` is what the server last said it was doing. */
const STEPS: { stage: string; title: string; detail: string }[] = [
    { stage: 'preparing', title: 'Prepare the pages', detail: 'Scans get a text layer, so every value can be found and highlighted on the page.' },
    { stage: 'pages', title: 'Read every page', detail: 'Digital pages are copied by code. Scans go through OCR, and to a vision model only where OCR is unsure.' },
    { stage: 'documents', title: 'Sort into documents, extract', detail: 'Pages are grouped into documents, and each one has its fields, tables and boxes read and checked.' },
];
const REST = { stage: 'rest', title: 'Read the rest', detail: 'Reading what the templates do not cover.' };
const MAX_CELLS = 120;       // beyond this many pages the grid would be noise: the bar alone says it
const WORKING = 4;           // pages the server reads at once, shown as "in progress"

const seconds = (n: number) => (n < 90 ? `${Math.max(0, Math.round(n))} s` : `${Math.floor(n / 60)} min ${String(Math.round(n % 60)).padStart(2, '0')} s`);

/** Created time as the server sends it: UTC without a zone marker. */
function startedAt(iso: string): number {
    const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
    return Number.isFinite(t) ? t : Date.now();
}

/** What the right pane shows while a file is still being read: where it is, what is happening, and how far along. */
export function ProcessingView({ wid, status, stage, progress, createdAt }: Props) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
    const [started] = useState(() => startedAt(createdAt));
    const steps = stage === 'rest' ? [...STEPS, REST] : STEPS;
    const current = status === 'queued' || !stage ? -1 : Math.max(0, steps.findIndex(s => s.stage === stage));
    const elapsed = Math.max(0, (now - started) / 1000);

    // the pace of the page reading, measured from when this screen first saw it (so a late visitor still gets an honest figure)
    const [pace, setPace] = useState<{ t: number; done: number } | null>(null);
    if (stage === 'pages' && progress.total > 0 && (!pace || progress.done < pace.done)) setPace({ t: now, done: progress.done });      // adjusted while rendering: it settles after one pass
    const gained = pace ? progress.done - pace.done : 0;
    const per = pace && gained >= 2 ? (now - pace.t) / 1000 / gained : 0;
    const left = stage === 'pages' && per > 0 ? per * (progress.total - progress.done) : 0;

    const total = progress.total;
    // the page count is only reported while pages are prepared and read; later "total" counts documents, so remember it
    const [pages, setPages] = useState(0);
    if ((stage === 'preparing' || stage === 'pages') && total > 0 && total !== pages) setPages(total);
    const pct = stage === 'pages' && total ? Math.round((progress.done / total) * 100) : stage === 'documents' || stage === 'rest' ? (total ? Math.round((progress.done / total) * 100) : 0) : 0;
    const headline = status === 'queued' ? 'Waiting to start' : current >= 0 ? steps[current].title : 'Starting';
    const detail = status === 'queued' ? 'This file is queued and begins as soon as there is room.' : current >= 0 ? steps[current].detail : '';

    return (
        <div className="pv" role="status" aria-live="polite">
            <div className="pv__top">
                <div className="pv__page" aria-hidden="true"><span className="pv__scan" /></div>
                <div className="pv__text">
                    <p className="pv__eyebrow">{status === 'queued' ? 'In the queue' : 'Working on your file'}</p>
                    <h2 className="pv__headline">{headline}<span className="pv__dots" aria-hidden="true"><i /><i /><i /></span></h2>
                    <p className="pv__detail">{detail}</p>
                </div>
            </div>

            <ol className="pv__steps">
                {steps.map((s, i) => {
                    const state = i < current ? 'done' : i === current ? 'now' : 'next';
                    return (
                        <li key={s.stage} className={`pv__step pv__step--${state}`}>
                            <span className="pv__mark" aria-hidden="true">{state === 'done' ? '✓' : i + 1}</span>
                            <span className="pv__stepname">{s.title}</span>
                            {state === 'now' && total > 0 && <span className="pv__count">{s.stage === 'documents' || s.stage === 'rest' ? `${Math.min(progress.done + 1, total)} of ${total}` : `${progress.done} of ${total} pages`}</span>}
                            {state === 'done' && <span className="pv__count">done</span>}
                        </li>);
                })}
            </ol>

            {(stage === 'pages' || stage === 'documents' || stage === 'rest') && total > 0 && (
                <div className="pv__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Progress">
                    <span style={{ width: `${Math.max(pct, 3)}%` }} />
                </div>)}

            {pages > 0 && pages <= MAX_CELLS && (
                <div className="pv__grid" aria-label={stage === 'pages' ? `${progress.done} of ${pages} pages read` : `${pages} pages`}>
                    {Array.from({ length: pages }, (_, i) => {
                        const state = stage === 'documents' || stage === 'rest' ? 'done' : stage === 'pages' ? (i < progress.done ? 'done' : i < progress.done + WORKING ? 'work' : 'wait') : 'wait';
                        return <i key={i} className={`pv__cell pv__cell--${state}`} title={`Page ${i + 1}`} />;
                    })}
                </div>)}

            <p className="pv__meta">
                <span>{seconds(elapsed)} so far</span>
                {left > 0 && <span>about {seconds(left)} left</span>}
                {pages > 0 && <span>{pages} {pages === 1 ? 'page' : 'pages'}</span>}
            </p>
            <p className="pv__note">You can leave this screen. The run keeps going on the server and the file appears in <Link to={`/app/w/${wid}`}>your documents</Link> when it is done.</p>
        </div>
    );
}
