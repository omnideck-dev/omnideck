import React, { useCallback, useState } from 'react';
import AudioPlayer from './AudioPlayer.jsx';
import ConversationsPanel from './ConversationsPanel.jsx';
import { useTheme } from '../contexts/Theme.jsx';
import { useCustomApps } from '../features/customApps/CustomApps.jsx';
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../features/navigation/DesktopNavigation.jsx';
import styles from './Sidebar.module.css';

const COLLAPSE_KEY = 'computron_sidebar_collapsed';

// Panels reachable from the nav. Settings + theme live in the footer;
// conversations live inline in the recent list below the nav. The agent
// network view is opened from the chat title-bar pill, not a nav item.
// Memory and Custom Tools live under Settings, not in the nav.
const NAV_ITEMS = [
    {
        id: 'agents', icon: 'bi-robot', label: 'Agents', command: 'openAgents',
    },
    {
        id: 'routines', icon: 'bi-bullseye', label: 'Routines', command: 'openRoutines',
    },
    {
        id: 'artifacts', icon: 'bi-collection', label: 'Artifacts', command: 'openArtifacts',
    },
    {
        id: 'apps', icon: 'bi-grid', label: 'Custom Apps', feature: 'customApps', command: 'openApps',
    },
];

function _readCollapsed() {
    try {
        return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
        return false;
    }
}

/**
 * Left navigation rail. Collapses to an icon-only strip or expands to
 * show labels, the OMNIDECK wordmark, and a primary "New chat" button.
 * The collapsed/expanded choice is persisted to localStorage.
 */
export default function Sidebar({
    onNewConversation,
    desktopEnabled,
    onOpenDesktop,
    onLoadConversation,
    activeConversationId,
}) {
    const { dark, toggleTheme } = useTheme();
    const { destination } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const customApps = useCustomApps();
    const [collapsed, setCollapsed] = useState(_readCollapsed);

    const toggleCollapsed = useCallback(() => {
        setCollapsed((c) => {
            const next = !c;
            try {
                localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0');
            } catch {
                // localStorage unavailable — collapse still works for the session.
            }
            return next;
        });
    }, []);

    const activeItemId = NAV_ITEMS.some((item) => item.id === destination.kind)
        ? destination.kind
        : null;
    const settingsActive = destination.kind === 'settings';

    const activateNavigationItem = useCallback((item) => {
        if (activeItemId === item.id) {
            navigation.openChat();
            return;
        }
        navigation[item.command]();
    }, [activeItemId, navigation]);

    return (
        <aside
            className={`${styles.sidebar} ${collapsed ? styles.collapsed : styles.expanded}`}
            data-testid="sidebar"
            data-collapsed={collapsed}
        >
            <div className={styles.brand}>
                {!collapsed && <span className={styles.wordmark}>OMNIDECK</span>}
                <button
                    className={styles.iconBtn}
                    onClick={toggleCollapsed}
                    title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                    aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                    data-testid="sidebar-toggle"
                >
                    <i className={`bi ${collapsed ? 'bi-layout-sidebar' : 'bi-layout-sidebar-inset'}`} />
                </button>
            </div>

            <div className={styles.primary}>
                <button
                    className={styles.newChat}
                    onClick={onNewConversation}
                    title="New chat"
                    aria-label="New chat"
                    data-testid="sidebar-new-chat"
                >
                    <span className={styles.newChatIcon}>
                        <i className="bi bi-plus-lg" />
                    </span>
                    {!collapsed && <span>New chat</span>}
                </button>
            </div>

            <nav className={styles.nav}>
                {NAV_ITEMS.filter((item) => {
                    if (item.feature === 'customApps') return customApps.enabled;
                    return true;
                }).map((item) => {
                    const active = activeItemId === item.id;
                    return (
                        <button
                            key={item.id}
                            className={`${styles.navItem} ${active ? styles.active : ''}`}
                            onClick={() => activateNavigationItem(item)}
                            title={item.label}
                            aria-label={item.label}
                            data-testid={`sidebar-nav-${item.id}`}
                        >
                            <i className={`bi ${item.icon}`} />
                            {!collapsed && <span className={styles.navLabel}>{item.label}</span>}
                        </button>
                    );
                })}
            </nav>

            {collapsed ? (
                <div className={styles.grow} />
            ) : (
                <ConversationsPanel
                    onLoadConversation={onLoadConversation}
                    onNewConversation={onNewConversation}
                    activeConversationId={activeConversationId}
                />
            )}

            <div className={styles.footer}>
                <button
                    className={`${styles.iconBtn} ${!dark ? styles.themeOn : ''}`}
                    onClick={toggleTheme}
                    title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
                    aria-label="Toggle theme"
                    data-testid="sidebar-theme-toggle"
                >
                    <i className="bi bi-sun" />
                </button>
                <div className={styles.footerSpacer} />
                <AudioPlayer />
                {desktopEnabled && (
                    <button
                        className={styles.iconBtn}
                        onClick={onOpenDesktop}
                        title="Open desktop"
                        aria-label="Open desktop"
                        data-testid="sidebar-desktop"
                    >
                        <i className="bi bi-display" />
                    </button>
                )}
                <button
                    className={`${styles.iconBtn} ${settingsActive ? styles.active : ''}`}
                    onClick={() => {
                        if (settingsActive) navigation.openChat();
                        else navigation.openSettings();
                    }}
                    title="Settings"
                    aria-label="Settings"
                    data-testid="sidebar-settings"
                >
                    <i className="bi bi-gear" />
                </button>
            </div>
        </aside>
    );
}
