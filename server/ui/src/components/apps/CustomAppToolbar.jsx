import Button from '../primitives/Button.jsx';
import styles from './CustomAppToolbar.module.css';

export default function CustomAppToolbar({
    app,
    isHome,
    onOpenApps,
    onOpenChat,
    onClose,
    onToggleHome,
    onReload,
}) {
    return (
        <div className={styles.toolbar}>
            <Button variant="ghost" onClick={onOpenApps} data-testid="custom-app-back">
                <i className="bi bi-arrow-left" /> Custom Apps
            </Button>
            <div className={styles.identity}>
                <i className={`bi ${app.icon}`} />
                <strong>{app.title}</strong>
                {isHome
                    ? <span className={styles.homeBadge}><i className="bi bi-house-fill" /> Home</span>
                    : <span className={styles.appKind}>Experimental Custom App</span>}
            </div>
            <Button variant="filled" onClick={onOpenChat} data-testid="custom-app-chat">
                <i className="bi bi-stars" /> Chat with Agent
            </Button>
            <Button variant="ghost" onClick={onClose} data-testid="custom-app-close">
                <i className="bi bi-x-lg" /> Close
            </Button>
            <Button
                variant="ghost"
                onClick={onToggleHome}
                data-testid="custom-app-home-toggle"
            >
                <i className={`bi ${isHome ? 'bi-house-dash' : 'bi-house-add'}`} />
                {isHome ? 'Remove from Home' : 'Set as Home'}
            </Button>
            <Button
                variant="ghost"
                onClick={onReload}
                title="Reload Custom App"
                data-testid="custom-app-reload"
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

export function CustomAppDockActions({ onExpand, onReload }) {
    return (
        <>
            <Button
                variant="ghost"
                onClick={onExpand}
                title="Expand Custom App"
                aria-label="Expand Custom App"
                data-testid="custom-app-expand"
            >
                <i className="bi bi-arrows-angle-expand" />
            </Button>
            <CustomAppReloadAction onReload={onReload} />
        </>
    );
}

export function CustomAppError({ message }) {
    return message ? <div className={styles.error}>{message}</div> : null;
}
