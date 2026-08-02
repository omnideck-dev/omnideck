import { useCallback, useEffect, useState } from 'react';
import { useOmnideckHost } from '../features/app/OmnideckHost.jsx';
import styles from './SoftwareUpdateNotice.module.css';
import DownloadIcon from './icons/DownloadIcon';

/**
 * Tells you a newer version of Omnideck is ready, and gets out of the way.
 *
 * Nothing here blocks what you were doing: the notice sits in a corner until it
 * is answered, and it can be turned off for good — after which updates are
 * still found, and Settings is the only place that mentions them.
 *
 * Renders nothing outside the desktop application, which is the only place that
 * can install anything. Running Omnideck from the command line never sees it.
 */
export default function SoftwareUpdateNotice() {
    const [update, setUpdate] = useState(null);
    const [wanted, setWanted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [dismissed, setDismissed] = useState(false);
    const host = useOmnideckHost();

    useEffect(() => {
        if (!host?.onUpdate) return undefined;
        const stopListening = host.onUpdate(setUpdate);
        // An update found before this page existed was announced to nobody, so
        // it has to be asked for rather than waited on.
        let current = true;
        host.currentUpdate?.()
            .then((found) => { if (current) setUpdate(found); })
            .catch(() => {});
        fetch('/api/settings')
            .then((response) => response.json())
            .then((settings) => {
                if (current) setWanted(settings.software_updates_notify !== false);
            })
            .catch(() => {});
        return () => {
            current = false;
            stopListening();
        };
    }, [host]);

    const install = useCallback(async () => {
        setBusy(true);
        try {
            // Installing replaces what is running, so the window leaves for the
            // progress screen and this notice goes with it.
            await host.installUpdate();
        } catch {
            setBusy(false);
        }
    }, [host]);

    // Later means the same thing in every case: install it the next time
    // omnideck is opened, when nothing is running to interrupt. With automatic
    // updates on that is already what would happen; with them off, this asks
    // for it once without turning them back on.
    const later = useCallback(async () => {
        setBusy(true);
        try {
            await host.deferUpdate();
        } catch {
            setBusy(false);
        }
    }, [host]);

    const skip = useCallback(async () => {
        setBusy(true);
        try {
            await host.skipUpdate();
        } catch {
            setBusy(false);
        }
    }, [host]);

    // Turning the notice off is a preference, not an answer about this version:
    // the update stays available and Settings goes on offering it.
    const stopShowing = useCallback(async () => {
        setBusy(true);
        setDismissed(true);
        try {
            await fetch('/api/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ software_updates_notify: false }),
            });
        } catch {
            setDismissed(false);
            setBusy(false);
        }
    }, [host]);

    // An update already answered with Later is settled; Settings still has it.
    if (!update || update.deferred || !wanted || dismissed) return null;

    return (
        <aside className={styles.notice} data-testid="software-update-notice">
            <div className={styles.icon}>
                <DownloadIcon />
            </div>
            <div className={styles.body}>
                <p className={styles.title}>Omnideck {update.version} is ready</p>
                <p className={styles.detail}>
                    Installing takes a few minutes and closes what you have open.
                    Later installs it the next time you open omnideck.
                </p>
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
                        onClick={later}
                        disabled={busy}
                    >
                        Later
                    </button>
                </div>
                <div className={styles.choices}>
                    <button
                        type="button"
                        className={styles.link}
                        onClick={skip}
                        disabled={busy}
                    >
                        Skip this version
                    </button>
                    <button
                        type="button"
                        className={styles.link}
                        onClick={stopShowing}
                        disabled={busy}
                    >
                        Don&rsquo;t show these again
                    </button>
                </div>
                <p className={styles.footnote}>
                    Updates stay available in Settings.
                </p>
            </div>
        </aside>
    );
}
