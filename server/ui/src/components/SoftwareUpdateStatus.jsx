import { useCallback, useEffect, useState } from 'react';
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

    useEffect(() => {
        let current = true;
        window.omnideckDesktop?.currentUpdate?.()
            .then((found) => { if (current) setUpdate(found); })
            .catch(() => {});
        return () => { current = false; };
    }, []);

    const check = useCallback(async () => {
        setChecking(true);
        try {
            setUpdate(await window.omnideckDesktop.checkForUpdate());
            setChecked(true);
        } catch {
            // A check that could not reach anywhere says nothing rather than
            // claiming to be up to date.
        } finally {
            setChecking(false);
        }
    }, []);

    const install = useCallback(async () => {
        setInstalling(true);
        try {
            await window.omnideckDesktop.installUpdate();
        } catch {
            setInstalling(false);
        }
    }, []);

    return (
        <div
            className={styles.status}
            data-available={update ? 'true' : 'false'}
            data-testid="software-update-status"
        >
            <div className={styles.info}>
                <span className={styles.title}>
                    {update ? `Omnideck ${update.version} is ready` : 'Omnideck is up to date'}
                </span>
                <span className={styles.desc}>
                    {update
                        ? update.deferred
                            ? 'Installs the next time you open Omnideck. You can install it now instead.'
                            : 'Installing takes a few minutes and closes what you have open.'
                        : checked
                            ? 'No newer version is available yet.'
                            : 'Omnideck looks for updates on its own while it is open.'}
                </span>
            </div>
            {update ? (
                <button
                    type="button"
                    className={styles.primary}
                    onClick={install}
                    disabled={installing}
                >
                    Update now
                </button>
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
