import { useCallback, useEffect, useState } from 'react';
import styles from './SoftwareUpdateNotice.module.css';
import DownloadIcon from './icons/DownloadIcon';

/**
 * Tells you a newer version of Omnideck is ready, and gets out of the way.
 *
 * Nothing is installed without being asked for, and nothing here blocks what
 * you were doing: the notice sits in a corner until it is answered, and
 * outlives a reload because the desktop application re-sends it.
 *
 * Renders nothing outside the desktop application, which is the only place
 * that can install anything.
 */
export default function SoftwareUpdateNotice() {
    const [update, setUpdate] = useState(null);
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        const desktop = window.omnideckDesktop;
        if (!desktop?.onUpdate) return undefined;
        const stopListening = desktop.onUpdate(setUpdate);
        // An update found before this page existed was announced to nobody, so
        // it has to be asked for rather than waited on.
        let current = true;
        desktop.currentUpdate?.()
            .then((found) => { if (current) setUpdate(found); })
            .catch(() => {});
        return () => {
            current = false;
            stopListening();
        };
    }, []);

    const install = useCallback(async () => {
        setBusy(true);
        try {
            // Installing replaces what is running, so the window leaves for the
            // progress screen and this notice goes with it.
            await window.omnideckDesktop.installUpdate();
        } catch {
            setBusy(false);
        }
    }, []);

    const skip = useCallback(async () => {
        setBusy(true);
        try {
            await window.omnideckDesktop.skipUpdate();
        } catch {
            setBusy(false);
        }
    }, []);

    if (!update) return null;

    return (
        <aside className={styles.notice} data-testid="software-update-notice">
            <div className={styles.icon}>
                <DownloadIcon />
            </div>
            <div className={styles.body}>
                <p className={styles.title}>Omnideck {update.version} is ready</p>
                <p className={styles.detail}>
                    Installing takes a few minutes and closes what you have open.
                </p>
            </div>
            <div className={styles.actions}>
                <button
                    type="button"
                    className={styles.primary}
                    onClick={install}
                    disabled={busy}
                >
                    Update now
                </button>
                <button
                    type="button"
                    className={styles.quiet}
                    onClick={skip}
                    disabled={busy}
                >
                    Skip this version
                </button>
            </div>
        </aside>
    );
}
