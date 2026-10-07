// Shared refresh state for disk-backed file previews, keyed by file path.
//
// The same file can be shown by more than one mounted preview at once. Each
// consumer would otherwise hold its own "changed on disk" flag and refresh version, so
// refreshing one would leave the other stale. Routing both through this store
// keeps every view of a given file in sync.

const _entries = new Map(); // path -> { version, stale }
const _listeners = new Map(); // path -> Set<callback>
const _watchers = new Map(); // path -> shared polling state
const _DEFAULT = { version: 0, stale: false };
const POLL_INTERVAL_MS = 4000;

function _active(watcher) {
    return _watchers.get(watcher.path) === watcher
        && watcher.visible > 0 && !document.hidden;
}

function _canProbe(watcher) {
    return _watchers.get(watcher.path) === watcher && watcher.consumers > 0
        && (watcher.baselineRequested || _active(watcher));
}

function _cancel(watcher) {
    clearTimeout(watcher.timer);
    watcher.timer = null;
    watcher.generation += 1;
    watcher.controller?.abort();
}

async function _probe(watcher) {
    if (!_canProbe(watcher) || watcher.controller) return;
    const controller = new AbortController();
    const generation = watcher.generation;
    watcher.controller = controller;
    watcher.immediate = false;
    watcher.baselineRequested = false;
    try {
        // A cached HEAD response can hide disk changes until heuristic expiry.
        const response = await fetch(watcher.path, {
            method: 'HEAD', cache: 'no-store', signal: controller.signal,
        });
        if (!response.ok || generation !== watcher.generation
            || _watchers.get(watcher.path) !== watcher) return;
        const validator = response.headers.get('ETag') || response.headers.get('Last-Modified');
        if (!validator) return;
        if (watcher.baseline === null) watcher.baseline = validator;
        else if (validator !== watcher.baseline) markStale(watcher.path);
    } catch { /* Transient failures, including the first probe, retry next tick. */ }
    finally {
        watcher.controller = null;
        // Schedule after completion, so slow requests cannot overlap. A resume
        // or refresh during an aborted request starts as soon as it settles.
        if (_canProbe(watcher)) {
            if (watcher.immediate || watcher.baselineRequested) _probe(watcher);
            else watcher.timer = setTimeout(() => _probe(watcher), POLL_INTERVAL_MS);
        }
    }
}

function _resume(watcher) {
    clearTimeout(watcher.timer);
    watcher.timer = null;
    watcher.immediate = true;
    _probe(watcher);
}

function _onVisibilityChange() {
    for (const watcher of _watchers.values()) {
        if (_active(watcher)) _resume(watcher);
        else _cancel(watcher);
    }
}

function _releaseUnused(path) {
    const watcher = _watchers.get(path);
    if (!watcher || watcher.consumers || _listeners.has(path)) return;
    _cancel(watcher);
    _watchers.delete(path);
    if (!_watchers.size) document.removeEventListener('visibilitychange', _onVisibilityChange);
}

// Each mounted preview holds a lease, including hidden previews. Keeping their
// baseline lets the first visible consumer catch up without silently accepting
// changes made while every view of the file was hidden.
export function watch(path, visible = true) {
    if (!path) return undefined;
    let watcher = _watchers.get(path);
    const created = !watcher;
    if (!watcher) {
        watcher = {
            path, consumers: 0, visible: 0, baseline: null,
            generation: 0, controller: null, timer: null, immediate: false,
            baselineRequested: true,
        };
        if (!_watchers.size) document.addEventListener('visibilitychange', _onVisibilityChange);
        _watchers.set(path, watcher);
    }
    watcher.consumers += 1;
    if (visible) {
        watcher.visible += 1;
    }
    // Restored hidden tabs already load their content. Seed a baseline once,
    // then stop until visible, so first activation can detect later changes.
    if (created || (visible && watcher.visible === 1)) _resume(watcher);
    return () => {
        watcher.consumers -= 1;
        if (visible) {
            watcher.visible -= 1;
            if (!watcher.visible) _cancel(watcher);
        }
        _releaseUnused(path);
    };
}

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
        _releaseUnused(path);
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
    const watcher = _watchers.get(path);
    if (watcher) {
        _cancel(watcher);
        watcher.baseline = null;
        watcher.baselineRequested = true;
        _resume(watcher);
    }
    _notify(path);
}

// Test-only: drop all watch state between cases.
export function _reset() {
    for (const watcher of _watchers.values()) _cancel(watcher);
    _watchers.clear();
    document.removeEventListener('visibilitychange', _onVisibilityChange);
    _entries.clear();
    _listeners.clear();
}
