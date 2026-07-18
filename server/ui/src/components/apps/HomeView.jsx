import { useEffect, useState } from 'react';

import Button from '../primitives/Button.jsx';
import styles from './HomeView.module.css';

/** Resolve a configured Home app, then hand it to the shell-level workspace. */
export default function HomeView({ slug, onOpenApps, onHomeAppChange, onOpenApp }) {
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError('');
        fetch('/api/custom-apps')
            .then(async (response) => {
                const body = await response.json();
                if (!response.ok) throw new Error(body.error?.message || 'Could not load Home app');
                const app = (body.apps || []).find((candidate) => candidate.slug === slug);
                if (!app) throw new Error(`The Custom App “${slug}” could not be found.`);
                if (!cancelled) onOpenApp(app);
            })
            .catch((err) => { if (!cancelled) setError(err.message); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [slug, onOpenApp]);

    const removeFromHome = async () => {
        const response = await fetch('/api/custom-apps/home', { method: 'DELETE' });
        const body = await response.json();
        if (!response.ok) {
            setError(body.error?.message || 'Could not remove Home app');
            return;
        }
        onHomeAppChange(null);
        onOpenApps();
    };

    if (!loading && error) {
        return (
            <div className={styles.view} data-testid="home-view">
                <div className={styles.recovery} data-testid="home-app-unavailable">
                    <i className="bi bi-house-exclamation" />
                    <strong>Your Home app is unavailable</strong>
                    <span>{error}</span>
                    <div>
                        <Button onClick={onOpenApps}>Choose another app</Button>
                        <Button variant="ghost" onClick={removeFromHome}>Use Chat as Home</Button>
                    </div>
                </div>
            </div>
        );
    }

    return <div className={styles.view} data-testid="home-view" />;
}
