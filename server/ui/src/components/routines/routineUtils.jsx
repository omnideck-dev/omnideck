/**
 * Utility functions for Routines UI components.
 * Status icons, formatting helpers, and common patterns.
 */

// Status Icon component (reused across routines)
export function StatusIcon({ status, size = 14 }) {
    const color = {
        active: 'var(--text-primary)',
        completed: 'var(--success)',
        running: 'var(--accent)',
        failed: 'var(--danger)',
        pending: 'var(--text-tertiary)',
        paused: 'var(--warning)',
    }[status] || 'var(--text-tertiary)';

    return (
        <svg width={size} height={size} viewBox="0 0 14 14" fill={color}>
            <circle cx="7" cy="7" r="6" stroke="none" />
        </svg>
    );
}

// Format a timestamp relative to now (e.g., "2h ago")
export function formatTime(timestamp) {
    if (!timestamp) return '-';
    
    const date = typeof timestamp === 'string' ? new Date(timestamp) : new Date(timestamp * 1000);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 60) return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHour < 24) return `${diffHour}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Format duration between two timestamps
export function formatDuration(start, end) {
    if (!start || !end) return null;
    
    const startMs = typeof start === 'string' ? new Date(start).getTime() : start * 1000;
    const endMs = typeof end === 'string' ? new Date(end).getTime() : end * 1000;
    const diffSec = Math.floor((endMs - startMs) / 1000);
    
    if (diffSec < 60) return `${diffSec}s`;
    const min = Math.floor(diffSec / 60);
    const sec = diffSec % 60;
    if (min < 60) return `${min}m ${sec}s`;
    const hour = Math.floor(min / 60);
    const remMin = min % 60;
    return `${hour}h ${remMin}m`;
}

// Format a future timestamp relative to now (e.g., "in 2h")
export function formatTimeUntil(timestamp) {
    if (!timestamp) return '-';

    const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;
    const now = new Date();
    const diffMs = date - now;
    if (diffMs <= 0) return 'now';
    const diffMin = Math.floor(diffMs / 60000);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffMin < 1) return '<1m';
    if (diffMin < 60) return `in ${diffMin}m`;
    if (diffHour < 24) return `in ${diffHour}h ${diffMin % 60}m`;
    return `in ${diffDay}d`;
}

const _DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function _isNum(s) {
    return /^\d+$/.test(s);
}

function _time12(hour, minute) {
    const h = parseInt(hour, 10);
    const m = parseInt(minute, 10);
    const ampm = h < 12 ? 'AM' : 'PM';
    const h12 = h % 12 || 12;
    return m === 0 ? `${h12} ${ampm}` : `${h12}:${String(m).padStart(2, '0')} ${ampm}`;
}

function _ordinal(n) {
    const v = parseInt(n, 10);
    const s = ['th', 'st', 'nd', 'rd'];
    const k = v % 100;
    return `${v}${s[(k - 20) % 10] || s[k] || s[0]}`;
}

/**
 * Turn a cron expression into a human-friendly schedule for end users —
 * they should never see raw cron. Covers the common shapes; anything more
 * exotic falls back to "Custom schedule" (the raw cron stays available as a
 * tooltip at the call site).
 */
export function formatCron(cron) {
    if (!cron) return '-';
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return 'Custom schedule';
    const [min, hour, dom, mon, dow] = parts;

    const everyN = (field) => {
        const m = /^\*\/(\d+)$/.exec(field);
        return m ? parseInt(m[1], 10) : null;
    };

    // Sub-hour cadences.
    if (min === '*' && hour === '*') return 'Every minute';
    const everyMin = everyN(min);
    if (everyMin && hour === '*') return `Every ${everyMin} minutes`;
    const everyHour = everyN(hour);
    if (_isNum(min) && everyHour) return `Every ${everyHour} hours`;
    if (_isNum(min) && hour === '*') {
        return min === '0' ? 'Every hour' : `Hourly at :${String(min).padStart(2, '0')}`;
    }

    // From here we need a concrete time of day.
    if (!_isNum(min) || !_isNum(hour)) return 'Custom schedule';
    const at = _time12(hour, min);

    // Day-of-week schedules — only when not also constrained by a specific
    // day-of-month or month (those combos aren't worth modeling).
    if (dow !== '*') {
        if (dom !== '*' || mon !== '*') return 'Custom schedule';
        if (dow === '1-5') return `Weekdays at ${at}`;
        if (dow === '0,6' || dow === '6,0' || dow === '0,7') return `Weekends at ${at}`;
        const days = dow.split(',');
        if (days.every((d) => _isNum(d) && +d <= 7)) {
            const names = days.map((d) => _DAYS[+d % 7]);
            return `${names.join('/')} at ${at}`;
        }
        return 'Custom schedule';
    }

    // Day-of-month (monthly).
    if (dom !== '*' && _isNum(dom) && mon === '*') {
        return `Monthly on the ${_ordinal(dom)} at ${at}`;
    }

    // Plain daily.
    if (dom === '*' && mon === '*') return `Daily at ${at}`;

    return 'Custom schedule';
}
