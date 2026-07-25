// Shared refresh state for disk-backed file previews, keyed by file path.
//
// The same file can be shown by more than one mounted preview at once. Each
// consumer would otherwise hold its own "changed on disk" flag and refresh version, so
// refreshing one would leave the other stale. Routing both through this store
// keeps every view of a given file in sync.

const _entries = new Map(); // path -> { version, stale }
const _listeners = new Map(); // path -> Set<callback>
const _DEFAULT = { version: 0, stale: false };

function _notify(path) {
    const ls = _listeners.get(path);
    if (ls) ls.forEach((fn) => fn());
}

export function subscribe(path, fn) {
    if (!path) return () => {};
    let ls = _listeners.get(path);
    if (!ls) {
        ls = new Set();
        _listeners.set(path, ls);
    }
    ls.add(fn);
    return () => {
        ls.delete(fn);
        if (ls.size === 0) _listeners.delete(path);
    };
}

export function getSnapshot(path) {
    return _entries.get(path) || _DEFAULT;
}

// Flag the file as changed on disk. Idempotent so redundant pollers don't churn.
export function markStale(path) {
    const cur = _entries.get(path) || _DEFAULT;
    if (cur.stale) return;
    _entries.set(path, { version: cur.version, stale: true });
    _notify(path);
}

// Bump the version (drives a refetch/cache-bust) and clear the stale flag.
export function refresh(path) {
    const cur = _entries.get(path) || _DEFAULT;
    _entries.set(path, { version: cur.version + 1, stale: false });
    _notify(path);
}

// Test-only: drop all watch state between cases.
export function _reset() {
    _entries.clear();
    _listeners.clear();
}
