/** "2 hours ago" for a server timestamp (the API sends naive UTC). */
export function timeAgo(iso: string, now: number = Date.now()): string {
    const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
    if (Number.isNaN(t)) return '';
    const sec = Math.round((t - now) / 1000);
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    const steps: [Intl.RelativeTimeFormatUnit, number][] = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [unit, secs] of steps) if (Math.abs(sec) >= secs) return rtf.format(Math.round(sec / secs), unit);
    return 'just now';
}
