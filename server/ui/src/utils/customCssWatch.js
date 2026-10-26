// Live-refresh a stylesheet <link> when its file changes on disk.
//
// Same disk-watching idiom as useFileContent: poll HEAD for the file's
// ETag/Last-Modified and record the change in the shared fileWatchStore, keyed by
// the file's URL. The store's version drives the cache-busting query on the
// replacement link, so the browser refetches the updated file. A stylesheet has
// nothing to prompt about, so a detected change is refreshed straight away rather
// than left stale. This covers hand edits and agent edits alike.
//
// The new version is loaded in a second <link> placed right after the current
// one, and the current one is removed only once the new one has fully loaded
// (including any @import it pulls in, such as a web font stylesheet). Re-pointing
// the existing link's href instead would drop the live styles while the new file
// and its imports download, flashing the app's default theme.

import * as fileWatch from './fileWatchStore.js';

// How often to re-check the stylesheet while the tab is visible.
const POLL_INTERVAL_MS = 4000;

export function watchStylesheet(link, baseHref) {
    let cancelled = false;
    let baseline = null;
    let appliedVersion = 0;
    let current = link; // the <link> whose styles are live right now
    let pending = null; // its replacement, still loading

    const swapTo = (href) => {
        // A newer edit supersedes a replacement that hasn't finished loading.
        if (pending) pending.remove();

        const next = document.createElement('link');
        next.rel = 'stylesheet';
        next.href = href;
        pending = next;

        next.addEventListener('load', () => {
            if (pending !== next) return;
            pending = null;
            current.remove();
            current = next;
        }, { once: true });
        // Keep the working styles if the new version can't be loaded.
        next.addEventListener('error', () => {
            if (pending !== next) return;
            pending = null;
            next.remove();
        }, { once: true });

        // Same position in the document, so the cascade order is unchanged.
        if (current.isConnected) current.after(next);
        else document.head.appendChild(next);
    };

    // The store's version is the cache-bust nonce; version 0 is the pristine URL.
    const unsubscribe = fileWatch.subscribe(baseHref, () => {
        const { version } = fileWatch.getSnapshot(baseHref);
        if (version === appliedVersion) return; // e.g. markStale before refresh
        appliedVersion = version;
        swapTo(version ? `${baseHref}?v=${version}` : baseHref);
    });

    const probe = async () => {
        // no-store: without it the browser can answer HEAD from its cache and
        // the change goes unseen until the heuristic freshness window expires.
        const r = await fetch(baseHref, { method: 'HEAD', cache: 'no-store' });
        if (!r.ok) return null;
        return r.headers.get('ETag') || r.headers.get('Last-Modified');
    };

    probe().then((v) => { if (!cancelled) baseline = v; }).catch(() => {});

    const check = async () => {
        if (document.hidden) return;
        try {
            const v = await probe();
            if (cancelled || !v) return;
            if (baseline == null) {
                // The startup probe failed (e.g. the app was restarting as the page
                // loaded): take the baseline now instead of never watching.
                baseline = v;
            } else if (v !== baseline) {
                baseline = v; // re-baseline so this edit triggers exactly one refresh
                fileWatch.markStale(baseHref);
                fileWatch.refresh(baseHref);
            }
        } catch { /* transient network blip — retry next tick */ }
    };

    const timer = setInterval(check, POLL_INTERVAL_MS);
    // Catch up immediately when the user returns to the tab.
    const onVisible = () => { if (!document.hidden) check(); };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
        cancelled = true;
        clearInterval(timer);
        document.removeEventListener('visibilitychange', onVisible);
        unsubscribe();
        if (pending) pending.remove();
    };
}
