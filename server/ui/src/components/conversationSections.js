// Shared constants + pure helpers for the conversations sidebar panel. Kept
// free of JSX/DOM so the grouping logic can be reasoned about (and tested) on
// its own, apart from the components that render it.

export const BUCKET_ORDER = ['Today', 'Yesterday', 'Earlier'];
export const MAX_TITLE_LEN = 50;
export const MAX_FOLDER_NAME_LEN = 40;
export const MENU_WIDTH = 176;
export const DEFAULT_FOLDER_ICON = 'bi-folder';

// Curated Bootstrap icons offered in the folder icon picker. The server only
// validates the shape (`bi-*`), so this list is purely the frontend's palette.
export const FOLDER_ICONS = [
    'bi-folder', 'bi-briefcase', 'bi-code-slash', 'bi-book', 'bi-lightbulb',
    'bi-star', 'bi-heart', 'bi-flag', 'bi-bug', 'bi-rocket',
    'bi-music-note-beamed', 'bi-camera', 'bi-cpu', 'bi-gear', 'bi-graph-up-arrow',
    'bi-chat-dots', 'bi-journal-text', 'bi-kanban', 'bi-mortarboard', 'bi-controller',
    'bi-terminal', 'bi-box-seam', 'bi-tag', 'bi-house', 'bi-globe2',
    'bi-palette', 'bi-trophy', 'bi-basket',
];

// Persisted set of collapsed section keys. Keyed by stable section identity
// ('pinned', 'folder:<id>', 'Today'…) so a chat migrating between date buckets
// never carries a stale collapsed flag with it.
const COLLAPSE_KEY = 'omnideck_sidebar_collapsed_sections';

/** Bucket a conversation's start time into Today / Yesterday / Earlier. */
function dayBucket(iso) {
    if (!iso) return 'Earlier';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'Earlier';
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfYesterday = new Date(startOfToday);
    startOfYesterday.setDate(startOfYesterday.getDate() - 1);
    if (d >= startOfToday) return 'Today';
    if (d >= startOfYesterday) return 'Yesterday';
    return 'Earlier';
}

/** The visible label for a conversation row. */
export function label(convo) {
    return convo.title || convo.first_message || '(empty)';
}

/** A slim relative-age stamp (e.g. "3h", "2d") shown inline on search results. */
export function relativeAge(iso) {
    if (!iso) return '';
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return '';
    const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d`;
    const weeks = Math.round(days / 7);
    if (weeks < 5) return `${weeks}w`;
    const months = Math.round(days / 30);
    if (months < 12) return `${months}mo`;
    return `${Math.round(days / 365)}y`;
}

/** The value the rename input opens with — the visible label, sans placeholder. */
export function renameSeed(convo) {
    return convo.title || convo.first_message || '';
}

export function loadCollapsed() {
    try {
        const raw = localStorage.getItem(COLLAPSE_KEY);
        const parsed = JSON.parse(raw);
        return new Set(Array.isArray(parsed) ? parsed : []);
    } catch {
        return new Set();
    }
}

export function persistCollapsed(set) {
    try {
        localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...set]));
    } catch {
        // localStorage unavailable — collapse still works for the session.
    }
}

/**
 * Split the conversation list into ordered, collapsible sections: Pinned first,
 * then each custom folder (in the folders' own order), then the Today /
 * Yesterday / Earlier date buckets for everything left unfiled. A pinned chat
 * shows only under Pinned; a foldered chat shows only under its folder; the
 * rest fall through to the date buckets. Folders stay visible even when empty
 * (so they can be managed), except while searching, where empty ones hide.
 */
export function buildSections(items, folders, folderById, query) {
    const q = query.trim().toLowerCase();
    const filtered = q
        ? items.filter((c) => label(c).toLowerCase().includes(q))
        : items;

    const sections = [];

    const pinned = filtered.filter((c) => c.pinned);
    if (pinned.length) sections.push({ key: 'pinned', kind: 'pinned', label: 'Pinned', items: pinned });

    // Group the unpinned, filed conversations by folder.
    const byFolder = new Map();
    for (const c of filtered) {
        if (c.pinned) continue;
        const fid = c.folder_id && folderById.has(c.folder_id) ? c.folder_id : null;
        if (!fid) continue;
        if (!byFolder.has(fid)) byFolder.set(fid, []);
        byFolder.get(fid).push(c);
    }
    for (const folder of folders) {
        const folderItems = byFolder.get(folder.id) || [];
        if (q && folderItems.length === 0) continue;
        sections.push({ key: `folder:${folder.id}`, kind: 'folder', label: folder.name, folder, items: folderItems });
    }

    // Everything not pinned and not in a known folder keeps the date buckets.
    const byBucket = new Map();
    for (const c of filtered) {
        if (c.pinned) continue;
        if (c.folder_id && folderById.has(c.folder_id)) continue;
        const bucket = dayBucket(c.started_at);
        if (!byBucket.has(bucket)) byBucket.set(bucket, []);
        byBucket.get(bucket).push(c);
    }
    for (const b of BUCKET_ORDER) {
        if (byBucket.has(b)) sections.push({ key: b, kind: 'date', label: b, items: byBucket.get(b) });
    }
    return sections;
}
