import { useCallback, useEffect, useState } from 'react';
import { useOmnideckHost } from '../features/app/OmnideckHost.jsx';
import { appReleaseNotesUrl } from '../utils/appReleaseNotes.js';
import styles from './SoftwareUpdateStatus.module.css';

/**
 * Whether an update is waiting, and the way to install it.
 *
 * This is the place updates are always mentioned, including for someone who
 * asked not to be told anywhere else. It is also the only way to look for one
 * without waiting for the next scheduled check.
 */
export default function SoftwareUpdateStatus() {
    const [update, setUpdate] = useState(null);
    const [checking, setChecking] = useState(false);
    const [installing, setInstalling] = useState(false);
    const [checked, setChecked] = useState(false);
    const [error, setError] = useState('');
    const host = useOmnideckHost();
    const notesUrl = update ? appReleaseNotesUrl(update.version) : null;

    useEffect(() => {
        let current = true;
        let announced = false;
        const stopListening = host?.onUpdate?.((found) => {
            announced = true;
            setUpdate(found);
            setChecked(false);
            setError('');
        });
        host?.currentUpdate?.()
            .then((found) => { if (current && !announced) setUpdate(found); })
            .catch(() => {});
        return () => {
            current = false;
            stopListening?.();
        };
    }, [host]);

    const check = useCallback(async () => {
        setChecking(true);
        setChecked(false);
        setError('');
        try {
            setUpdate(await host.checkForUpdate());
            setChecked(true);
        } catch {
            setError('Could not check for updates. Please try again.');
        } finally {
            setChecking(false);
        }
    }, [host]);

    const install = useCallback(async () => {
        setInstalling(true);
        setError('');
        try {
            await host.installUpdate();
        } catch {
            setError('Could not start the update. Please try again.');
            setInstalling(false);
        }
    }, [host]);

    return (
        <div
            className={styles.status}
            data-available={update ? 'true' : 'false'}
            data-testid="software-update-status"
        >
            <div className={styles.info}>
                <span className={styles.title}>
                    {update ? `Omnideck ${update.version} is ready` : checked ? 'Omnideck is up to date' : 'Check for updates'}
                </span>
                <span className={styles.desc}>
                    {error || (update
                        ? update.deferred
                            ? 'Installs the next time you open Omnideck. You can install it now instead.'
                            : 'Installing takes a few minutes and closes what you have open.'
                        : checked
                            ? 'No newer version is available yet.'
                            : 'Omnideck looks for updates on its own while it is open.')}
                </span>
            </div>
            {update ? (
                <div className={styles.actions}>
                    {notesUrl ? (
                        <a
                            className={styles.notes}
                            href={notesUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            What&rsquo;s new
                        </a>
                    ) : null}
                    <button
                        type="button"
                        className={styles.primary}
                        onClick={install}
                        disabled={installing}
                    >
                        Update now
                    </button>
                </div>
            ) : (
                <button
                    type="button"
                    className={styles.secondary}
                    onClick={check}
                    disabled={checking}
                >
                    {checking ? 'Checking…' : 'Check now'}
                </button>
            )}
        </div>
    );
}
