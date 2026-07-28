import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';
import AudioPlayer from './AudioPlayer.jsx';
import ConversationsPanel from './ConversationsPanel.jsx';
import { useTheme } from '../contexts/Theme.jsx';
import { useCustomApps } from '../features/customApps/CustomApps.jsx';
import {
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
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
        id: 'apps', icon: 'bi-grid', label: 'Apps', feature: 'customApps', command: 'openApps',
    },
];

function _readCollapsed() {
    try {
        return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
        return false;
    }
}

function DockedAppsSection({
    collapsed,
    customApps,
    navigation,
    navigationTarget,
}) {
    const [pickerOpen, setPickerOpen] = useState(false);
    const sectionRef = useRef(null);
    const dockedSlugs = useMemo(
        () => new Set(customApps.dockedAppSlugs),
        [customApps.dockedAppSlugs],
    );
    const dockedApps = customApps.catalog.apps.filter(
        (app) => dockedSlugs.has(app.slug),
    );
    const availableApps = customApps.catalog.apps.filter(
        (app) => !dockedSlugs.has(app.slug),
    );

    useEffect(() => {
        if (!pickerOpen) return undefined;
        const closeOnOutsideClick = (event) => {
            if (!sectionRef.current?.contains(event.target)) setPickerOpen(false);
        };
        const closeOnEscape = (event) => {
            if (event.key === 'Escape') setPickerOpen(false);
        };
        document.addEventListener('mousedown', closeOnOutsideClick);
        document.addEventListener('keydown', closeOnEscape);
        return () => {
            document.removeEventListener('mousedown', closeOnOutsideClick);
            document.removeEventListener('keydown', closeOnEscape);
        };
    }, [pickerOpen]);

    if (collapsed && dockedApps.length === 0) return null;

    return (
        <section
            ref={sectionRef}
            className={styles.dockedSection}
            data-testid="sidebar-docked-section"
        >
            {!collapsed && (
                <div className={styles.sectionHeader}>
                    <span>Apps</span>
                    <button
                        type="button"
                        className={styles.sectionAction}
                        onClick={() => setPickerOpen((open) => !open)}
                        title="Add docked app"
                        aria-label="Add docked app"
                        aria-haspopup="menu"
                        aria-expanded={pickerOpen}
                        data-testid="sidebar-docked-add"
                    >
                        <i className="bi bi-plus-lg" />
                    </button>
                </div>
            )}

            <div className={styles.dockedList}>
                {dockedApps.map((app) => {
                    const active = navigationTarget?.kind === 'custom-app'
                        && navigationTarget.appSlug === app.slug;
                    return (
                        <div
                            key={app.slug}
                            className={`${styles.dockedItem} ${active ? styles.active : ''}`}
                        >
                            <button
                                type="button"
                                className={`${styles.navItem} ${styles.dockedApp}`}
                                onClick={() => {
                                    if (active) navigation.openChat();
                                    else navigation.openCustomApp(app.slug);
                                }}
                                title={app.title}
                                aria-label={app.title}
                                data-testid={`sidebar-docked-app-${app.slug}`}
                            >
                                <i className={`bi ${app.icon || 'bi-window'}`} />
                                {!collapsed && <span className={styles.navLabel}>{app.title}</span>}
                            </button>
                            {!collapsed && (
                                <button
                                    type="button"
                                    className={styles.unpinApp}
                                    onClick={() => customApps.undockApp(app.slug)}
                                    title={`Unpin ${app.title}`}
                                    aria-label={`Unpin ${app.title}`}
                                    data-testid={`sidebar-undock-app-${app.slug}`}
                                >
                                    <i className="bi bi-pin-angle-fill" />
                                </button>
                            )}
                        </div>
                    );
                })}
            </div>

            {!collapsed && pickerOpen && (
                <div
                    className={styles.dockPicker}
                    role="menu"
                    aria-label="Apps available to dock"
                    data-testid="sidebar-docked-picker"
                >
                    {customApps.catalog.loading && (
                        <div className={styles.dockPickerStatus}>Loading Apps…</div>
                    )}
                    {!customApps.catalog.loading && availableApps.length === 0 && (
                        <div className={styles.dockPickerStatus}>All Apps are docked</div>
                    )}
                    {availableApps.map((app) => (
                        <button
                            key={app.slug}
                            type="button"
                            role="menuitem"
                            className={styles.dockPickerItem}
                            onClick={() => {
                                customApps.dockApp(app.slug);
                                setPickerOpen(false);
                            }}
                            data-testid={`sidebar-dock-option-${app.slug}`}
                        >
                            <i className={`bi ${app.icon || 'bi-window'}`} />
                            <span>{app.title}</span>
                        </button>
                    ))}
                </div>
            )}
        </section>
    );
}

/**
 * Left navigation rail. Collapses to an icon-only strip or expands to
 * show labels, the OMNIDECK wordmark, docked Apps, and conversations.
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
    const navigationTarget = useCurrentNavigationTarget();
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

    const activeItemId = NAV_ITEMS.some(
        (item) => item.id === navigationTarget?.kind,
    )
        ? navigationTarget.kind
        : null;
    const settingsActive = navigationTarget?.kind === 'settings';

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

            {customApps.enabled && (
                <DockedAppsSection
                    collapsed={collapsed}
                    customApps={customApps}
                    navigation={navigation}
                    navigationTarget={navigationTarget}
                />
            )}

            {collapsed ? (
                <>
                    <div className={styles.grow} />
                    <div className={styles.collapsedConversation}>
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
                        </button>
                    </div>
                </>
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
