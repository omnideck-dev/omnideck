import Button from '../primitives/Button.jsx';
import styles from './HomeAppUnavailable.module.css';

/** Recovery surface for a configured Home app that no longer resolves. */
export default function HomeAppUnavailable({ message, onOpenApps, onClearHome }) {
    return (
        <div className={styles.view} data-testid="home-view">
            <div className={styles.recovery} data-testid="home-app-unavailable">
                <i className="bi bi-house-exclamation" />
                <strong>Your Home app is unavailable</strong>
                <span>{message}</span>
                <div>
                    <Button onClick={onOpenApps}>Choose another app</Button>
                    <Button variant="ghost" onClick={onClearHome}>Use Chat as Home</Button>
                </div>
            </div>
        </div>
    );
}
