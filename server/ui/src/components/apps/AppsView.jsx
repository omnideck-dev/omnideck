import Button from '../primitives/Button.jsx';
import styles from './AppsView.module.css';

const NOOP = () => {};

/** Lists discovered Apps; the desktop owns opening and presentation. */
export default function AppsView({
    apps = [],
    loading = false,
    error = '',
    onRefresh = NOOP,
    onOpenApp = NOOP,
    pinnedAppSlugs = [],
    onPinApp = NOOP,
    onUnpinApp = NOOP,
}) {
    return (
        <div className={styles.view} data-testid="apps-view">
            <div className={styles.toolbar}>
                <h1 className={styles.title}>
                    <i className="bi bi-grid" /> Apps
                    {!loading && <span className={styles.count}>· {apps.length}</span>}
                </h1>
                <Button variant="ghost" onClick={onRefresh} data-testid="custom-apps-refresh">
                    <i className="bi bi-arrow-clockwise" /> Refresh
                </Button>
            </div>
            <div className={styles.scroll}>
                {error && <div className={styles.error}>{error}</div>}
                {!loading && !error && apps.length === 0 && (
                    <div className={styles.empty}>
                        <i className="bi bi-grid" />
                        <strong>No Apps yet</strong>
                        <span>Ask your Omnideck agent to build one for you.</span>
                    </div>
                )}
                {apps.length > 0 && (
                    <div className={styles.grid}>
                        {apps.map((app) => {
                            const pinned = pinnedAppSlugs.includes(app.slug);
                            return (
                                <div key={app.slug} className={styles.cardContainer}>
                                    <button
                                        type="button"
                                        className={styles.card}
                                        onClick={() => onOpenApp(app)}
                                        data-testid="custom-app-card"
                                    >
                                        <div className={styles.cardIcon}><i className={`bi ${app.icon}`} /></div>
                                        <div className={styles.cardBody}>
                                            <strong>{app.title}</strong>
                                            <p>{app.description || 'An App built for Omnideck.'}</p>
                                        </div>
                                    </button>
                                    <button
                                        type="button"
                                        className={`${styles.pinButton} ${pinned ? styles.pinned : ''}`}
                                        onClick={() => (
                                            pinned
                                                ? onUnpinApp(app.slug)
                                                : onPinApp(app.slug)
                                        )}
                                        title={pinned ? `Unpin ${app.title}` : `Pin ${app.title} to sidebar`}
                                        aria-label={pinned ? `Unpin ${app.title}` : `Pin ${app.title} to sidebar`}
                                        aria-pressed={pinned}
                                        data-testid={`custom-app-pin-${app.slug}`}
                                    >
                                        <i className={`bi ${pinned ? 'bi-pin-angle-fill' : 'bi-pin-angle'}`} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
}
