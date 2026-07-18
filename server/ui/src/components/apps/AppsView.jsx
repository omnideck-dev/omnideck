import { useCallback, useEffect, useState } from 'react';

import Button from '../primitives/Button.jsx';
import styles from './AppsView.module.css';

const NOOP = () => {};

/** File-based app library. The shell owns every open app and its iframe. */
export default function AppsView({
    homeAppSlug = null,
    onHomeAppChange = NOOP,
    onOpenApp = NOOP,
    onOpenAppBesideChat = NOOP,
}) {
    const [apps, setApps] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const loadApps = useCallback(() => {
        setLoading(true);
        setError('');
        fetch('/api/folder-apps')
            .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.error?.message || 'Could not load apps');
                setApps(body.apps || []);
                if (body.home_app_slug !== homeAppSlug) onHomeAppChange(body.home_app_slug || null);
            })
            .catch((err) => setError(err.message))
            .finally(() => setLoading(false));
    }, [homeAppSlug, onHomeAppChange]);

    useEffect(() => { loadApps(); }, [loadApps]);

    return (
        <div className={styles.view} data-testid="apps-view">
            <div className={styles.toolbar}>
                <h1 className={styles.title}>
                    <i className="bi bi-grid" /> Apps
                    {!loading && <span className={styles.count}>· {apps.length}</span>}
                </h1>
                <span className={styles.rootHint}>Folders in ~/apps</span>
                <Button variant="ghost" onClick={loadApps} data-testid="folder-apps-refresh">
                    <i className="bi bi-arrow-clockwise" /> Refresh
                </Button>
            </div>
            <div className={styles.scroll}>
                {error && <div className={styles.error}>{error}</div>}
                {!loading && !error && apps.length === 0 && (
                    <div className={styles.empty}>
                        <i className="bi bi-folder-plus" />
                        <strong>No folder apps found</strong>
                        <span>Add a folder containing omnideck.json and web/index.html.</span>
                    </div>
                )}
                {apps.length > 0 && (
                    <div className={styles.grid}>
                        {apps.map((app) => (
                            <div key={app.slug} className={styles.cardShell}>
                                <button
                                    type="button"
                                    className={styles.card}
                                    onClick={() => onOpenApp(app)}
                                    data-testid="folder-app-card"
                                >
                                    <div className={styles.cardIcon}><i className={`bi ${app.icon}`} /></div>
                                    <div className={styles.cardBody}>
                                        <strong>{app.title}</strong>
                                        <p>{app.description || 'A file-based Omnideck app.'}</p>
                                        <div className={styles.meta}>
                                            <span><i className="bi bi-folder2" /> {app.slug}</span>
                                            {app.has_actions && <span><i className="bi bi-filetype-py" /> Python</span>}
                                            {!app.editable && <span><i className="bi bi-box-seam" /> Sample</span>}
                                            {app.slug === homeAppSlug && (
                                                <span className={styles.homeBadge}><i className="bi bi-house-fill" /> Home</span>
                                            )}
                                        </div>
                                    </div>
                                    <i className={`bi bi-chevron-right ${styles.chevron}`} />
                                </button>
                                <Button
                                    variant="ghost"
                                    className={styles.besideChat}
                                    onClick={() => onOpenAppBesideChat(app)}
                                    data-testid={`folder-app-open-split-${app.slug}`}
                                >
                                    <i className="bi bi-layout-split" /> Open beside Chat
                                </Button>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
