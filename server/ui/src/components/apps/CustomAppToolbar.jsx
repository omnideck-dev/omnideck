import Button from '../primitives/Button.jsx';
import styles from './CustomAppToolbar.module.css';

export default function CustomAppToolbar({
    app,
    origin,
    isHome,
    onOpenApps,
    onOpenChat,
    onToggleHome,
    onReload,
}) {
    return (
        <div className={styles.toolbar}>
            {origin === 'apps' ? (
                <Button variant="ghost" onClick={onOpenApps} data-testid="custom-app-back">
                    <i className="bi bi-arrow-left" /> Custom Apps
                </Button>
            ) : null}
            <div className={styles.identity}>
                <i className={`bi ${app.icon}`} />
                <strong>{app.title}</strong>
                {origin === 'home'
                    ? <span className={styles.homeBadge}><i className="bi bi-house-fill" /> Home</span>
                    : <span className={styles.appKind}>Experimental Custom App</span>}
            </div>
            {origin === 'home' && (
                <Button variant="ghost" onClick={onOpenApps} data-testid="home-open-apps">
                    <i className="bi bi-grid" /> Custom Apps
                </Button>
            )}
            <Button variant="filled" onClick={onOpenChat} data-testid="custom-app-chat">
                <i className="bi bi-stars" /> Chat with Agent
            </Button>
            <Button
                variant="ghost"
                onClick={onToggleHome}
                data-testid={origin === 'home' ? 'home-app-remove' : 'custom-app-home-toggle'}
            >
                <i className={`bi ${isHome ? 'bi-house-dash' : 'bi-house-add'}`} />
                {isHome ? 'Remove from Home' : 'Set as Home'}
            </Button>
            <Button
                variant="ghost"
                onClick={onReload}
                title="Reload Custom App"
                data-testid={origin === 'home' ? 'home-app-reload' : 'custom-app-reload'}
            >
                <i className="bi bi-arrow-clockwise" /> Reload
            </Button>
        </div>
    );
}

export function CustomAppReloadAction({ onReload }) {
    return (
        <Button
            variant="ghost"
            onClick={onReload}
            title="Reload Custom App"
            aria-label="Reload app"
            data-testid="custom-app-tab-reload"
        >
            <i className="bi bi-arrow-clockwise" />
        </Button>
    );
}

export function CustomAppError({ message }) {
    return message ? <div className={styles.error}>{message}</div> : null;
}
