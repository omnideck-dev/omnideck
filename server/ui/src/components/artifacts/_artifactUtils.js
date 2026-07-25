// Shared display helpers for artifact library surfaces.

// Bootstrap-icon class for an artifact, by MIME type then extension.
export function typeIcon(contentType, filename) {
    const ct = contentType || '';
    if (ct.startsWith('image/')) return 'bi-image';
    if (ct === 'application/pdf') return 'bi-filetype-pdf';
    const ext = (filename.split('.').pop() || '').toLowerCase();
    const byExt = {
        md: 'bi-markdown', markdown: 'bi-markdown',
        html: 'bi-filetype-html', htm: 'bi-filetype-html',
        csv: 'bi-filetype-csv', json: 'bi-filetype-json',
        pdf: 'bi-filetype-pdf', txt: 'bi-file-text',
    };
    return byExt[ext] || 'bi-file-earmark';
}

// The file extension including the dot (e.g. ".md"), or "" if none.
export function fileExt(filename) {
    const i = filename.lastIndexOf('.');
    return i > 0 ? filename.slice(i) : '';
}

// Compact "3 days ago" relative time from an ISO timestamp.
export function timeAgo(iso) {
    const then = Date.parse(iso);
    if (Number.isNaN(then)) return '';
    const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
    const units = [
        ['year', 31536000], ['month', 2592000], ['week', 604800],
        ['day', 86400], ['hour', 3600], ['minute', 60],
    ];
    for (const [name, size] of units) {
        const n = Math.floor(secs / size);
        if (n >= 1) return `${n} ${name}${n > 1 ? 's' : ''} ago`;
    }
    return 'just now';
}
