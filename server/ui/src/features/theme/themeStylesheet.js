// Keeps the page's theme stylesheet in step with the saved theme.
//
// The saved theme has a version that changes exactly when its generated CSS
// does. The controller tracks two things separately: the version the server
// says is wanted, and the version whose styles are actually live. Only a
// successful load moves the applied version, so a failed load leaves the
// working appearance in place and the next attempt still sees a difference to
// close. Failed attempts retry on a growing delay with no further trigger.
//
// A replacement is loaded in a second <link> placed right after the current
// one, and the current one is removed only once the new one has loaded. Pointing
// the existing link at a new URL instead would drop the live styles while the
// new file downloads, flashing the default theme.

const THEME_STYLESHEET_URL = '/theme.css';
const THEME_VERSION_URL = '/api/theme';
const RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 15000, 30000];

async function fetchThemeVersion() {
    const response = await fetch(THEME_VERSION_URL, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Theme version request failed: ${response.status}`);
    const { version } = await response.json();
    if (typeof version !== 'string') throw new Error('Theme version response was malformed');
    return version;
}

/**
 * @param {object} options
 * @param {HTMLLinkElement} options.link The stylesheet link currently in the document.
 * @param {() => Promise<string>} [options.fetchVersion] Resolves the wanted theme version.
 * @param {(callback: () => void, delay: number) => unknown} [options.setTimer]
 * @param {(handle: unknown) => void} [options.clearTimer]
 * @returns {{refresh: () => Promise<void>, dispose: () => void}}
 */
export function createThemeStylesheet({
    link,
    fetchVersion = fetchThemeVersion,
    setTimer = (callback, delay) => setTimeout(callback, delay),
    clearTimer = (handle) => clearTimeout(/** @type {number} */ (handle)),
}) {
    let applied = null; // version whose styles are live; null until the first successful load
    let current = link; // the <link> whose styles are live right now
    let pending = null; // its replacement, while it loads
    let retryTimer = null;
    let failures = 0;
    let running = false;
    let again = false;
    let disposed = false;

    const cancelRetry = () => {
        if (retryTimer === null) return;
        clearTimer(retryTimer);
        retryTimer = null;
    };

    const scheduleRetry = () => {
        if (disposed || retryTimer !== null) return;
        const delay = RETRY_DELAYS_MS[Math.min(failures, RETRY_DELAYS_MS.length - 1)];
        failures += 1;
        retryTimer = setTimer(() => {
            retryTimer = null;
            refresh();
        }, delay);
    };

    /** Resolves true once `next` has loaded, false if it could not be loaded. */
    const load = (version) => new Promise((resolve) => {
        const next = document.createElement('link');
        next.rel = 'stylesheet';
        next.href = `${THEME_STYLESHEET_URL}?v=${encodeURIComponent(version)}`;
        next.addEventListener('load', () => resolve(next), { once: true });
        next.addEventListener('error', () => {
            next.remove();
            resolve(null);
        }, { once: true });
        pending = next;
        // Same position in the document, so the cascade order is unchanged.
        if (current.isConnected) current.after(next);
        else document.head.appendChild(next);
    });

    const sync = async () => {
        let wanted;
        try {
            wanted = await fetchVersion();
        } catch {
            scheduleRetry();
            return;
        }
        if (disposed) return;
        if (wanted === applied) {
            failures = 0;
            cancelRetry();
            return;
        }

        const loaded = await load(wanted);
        pending = null;
        if (disposed) {
            loaded?.remove();
            return;
        }
        if (loaded === null) {
            // The working styles stay; `applied` still differs from the wanted version.
            scheduleRetry();
            return;
        }
        current.remove();
        current = loaded;
        applied = wanted;
        failures = 0;
        cancelRetry();
    };

    async function refresh() {
        if (disposed) return;
        // A request that arrives mid-run is folded into one more pass afterwards.
        if (running) {
            again = true;
            return;
        }
        running = true;
        try {
            do {
                again = false;
                await sync();
            } while (again && !disposed);
        } finally {
            running = false;
        }
    }

    function dispose() {
        disposed = true;
        cancelRetry();
        pending?.remove();
        pending = null;
    }

    return { refresh, dispose };
}

let installed = null;

/**
 * Add the theme stylesheet to the document and keep it current. The link is
 * appended (not imported) so it lands after the bundled core styles; a later
 * <link> wins on equal specificity. Safe to call more than once.
 */
export function installThemeStylesheet() {
    if (installed) return installed;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = THEME_STYLESHEET_URL;
    document.head.appendChild(link);

    const controller = createThemeStylesheet({ link });
    // A tab that was in the background may have missed a change: check once on return.
    const onVisible = () => {
        if (!document.hidden) controller.refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    controller.refresh();
    installed = {
        refresh: controller.refresh,
        dispose: () => {
            document.removeEventListener('visibilitychange', onVisible);
            controller.dispose();
        },
    };
    return installed;
}

/** Ask the installed controller to re-check the saved theme. A no-op before installation. */
export function requestThemeRefresh() {
    return installed?.refresh();
}

/** Forget the installed controller. Tests use this to start from a clean document. */
export function resetInstalledThemeStylesheet() {
    installed?.dispose();
    installed = null;
}
