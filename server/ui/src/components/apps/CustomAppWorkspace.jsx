import { useState } from 'react';

import Button from '../primitives/Button.jsx';
import PreviewPanel from '../PreviewPanel.jsx';
import CustomAppHost from './CustomAppHost.jsx';
import styles from './CustomAppWorkspace.module.css';

/**
 * Shell-scoped app surface. It stays mounted while presentation changes
 * between full-space, hidden, and the shared chat/preview workspace.
 */
export default function CustomAppWorkspace({
    app,
    visible,
    layout,
    origin,
    homeAppSlug,
    tabs,
    activeTab,
    onTabChange,
    onCloseTab,
    onOpenChat,
    onComposeChat,
    onOpenApps,
    onHomeAppChange,
    children,
}) {
    const [reloadSignal, setReloadSignal] = useState(0);
    const [error, setError] = useState('');
    const appTabId = `app:${app.slug}`;
    const isHome = app.slug === homeAppSlug;
    const isFull = visible && layout === 'full';

    const toggleHome = async () => {
        setError('');
        const response = await fetch('/api/custom-apps/home', isHome
            ? { method: 'DELETE' }
            : {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ slug: app.slug }),
            });
        const body = await response.json();
        if (!response.ok) {
            setError(body.error?.message || 'Could not update Home app');
            return;
        }
        onHomeAppChange(body.home_app_slug || null);
        if (origin === 'home' && !body.home_app_slug) onOpenApps();
    };

    return (
        <div
            className={`${styles.workspace} ${isFull ? styles.full : styles.split} ${!visible ? styles.hidden : ''}`}
            data-testid={origin === 'home' ? 'home-view' : 'custom-app-workspace'}
        >
            {isFull && (
                <div className={styles.toolbar}>
                    {origin === 'apps' ? (
                        <Button variant="ghost" onClick={onOpenApps} data-testid="custom-app-back">
                            <i className="bi bi-arrow-left" /> Apps
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
                            <i className="bi bi-grid" /> Apps
                        </Button>
                    )}
                    <Button variant="filled" onClick={onOpenChat} data-testid="custom-app-chat">
                        <i className="bi bi-stars" /> Chat with Agent
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={toggleHome}
                        data-testid={origin === 'home' ? 'home-app-remove' : 'custom-app-home-toggle'}
                    >
                        <i className={`bi ${isHome ? 'bi-house-dash' : 'bi-house-add'}`} />
                        {isHome ? 'Remove from Home' : 'Set as Home'}
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() => setReloadSignal((value) => value + 1)}
                        title="Reload app files"
                        data-testid={origin === 'home' ? 'home-app-reload' : 'custom-app-reload'}
                    >
                        <i className="bi bi-arrow-clockwise" /> Reload
                    </Button>
                </div>
            )}
            {error && <div className={styles.error}>{error}</div>}
            <PreviewPanel
                tabs={tabs}
                activeTab={activeTab}
                onTabChange={onTabChange}
                onCloseTab={onCloseTab}
                hideTabs={!visible || layout !== 'split'}
                actions={activeTab === appTabId ? (
                    <Button
                        variant="ghost"
                        onClick={() => setReloadSignal((value) => value + 1)}
                        title="Reload app files"
                        aria-label="Reload app"
                        data-testid="custom-app-tab-reload"
                    >
                        <i className="bi bi-arrow-clockwise" />
                    </Button>
                ) : null}
            >
                <CustomAppHost
                    app={app}
                    reloadSignal={reloadSignal}
                    active={visible && activeTab === appTabId}
                    onOpenChat={onOpenChat}
                    onComposeChat={onComposeChat}
                />
                {children}
            </PreviewPanel>
        </div>
    );
}
