import React, {
    useCallback,
    useMemo,
    useState,
} from 'react';
import AudioPlayer from './AudioPlayer.jsx';
import ConversationsPanel from './ConversationsPanel.jsx';
import SidebarReorderMenu from './SidebarReorderMenu.jsx';
import { useTheme } from '../contexts/Theme.jsx';
import { useCustomApps } from '../features/customApps/CustomApps.jsx';
import PinnedAppsSidebarSection from '../features/customApps/sidebar/PinnedAppsSidebarSection.jsx';
import {
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
} from '../features/navigation/DesktopNavigation.jsx';
import navigationItemStyles from '../features/navigation/sidebar/SidebarNavigationItem.module.css';
import useSidebarReorder from './useSidebarReorder.js';
import styles from './Sidebar.module.css';

const COLLAPSE_KEY = 'computron_sidebar_collapsed';
const NAV_ORDER_KEY = 'omnideck_sidebar_navigation_order';

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
const DEFAULT_NAV_ORDER = NAV_ITEMS.map((item) => item.id);

function _normalizeNavigationOrder(order) {
    const knownIds = new Set(DEFAULT_NAV_ORDER);
    const normalized = [];
    if (Array.isArray(order)) {
        order.forEach((id) => {
            if (!knownIds.delete(id)) return;
            normalized.push(id);
        });
    }
    DEFAULT_NAV_ORDER.forEach((id) => {
        if (knownIds.delete(id)) normalized.push(id);
    });
    return normalized;
}

function _readCollapsed() {
    try {
        return localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch {
        return false;
    }
}

function _readNavigationOrder() {
    try {
        return _normalizeNavigationOrder(
            JSON.parse(localStorage.getItem(NAV_ORDER_KEY) || '[]'),
        );
    } catch {
        return [...DEFAULT_NAV_ORDER];
    }
}

function _persistNavigationOrder(order) {
    try {
        localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order));
    } catch {
        // Reordering still works for the session when localStorage is unavailable.
    }
}

/**
 * Left navigation rail. Collapses to an icon-only strip or expands to
 * show labels, the OMNIDECK wordmark, pinned Apps, and conversations.
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
    const [navigationOrder, setNavigationOrder] = useState(_readNavigationOrder);
    const [navigationMenu, setNavigationMenu] = useState(null);
    const closeNavigationMenu = useCallback(() => setNavigationMenu(null), []);
    const navItemsById = useMemo(
        () => new Map(NAV_ITEMS.map((item) => [item.id, item])),
        [],
    );
    const orderedNavigationItems = navigationOrder
        .map((id) => navItemsById.get(id))
        .filter((item) => {
            if (item.feature === 'customApps') return customApps.enabled;
            return true;
        });
    const visibleNavigationIds = orderedNavigationItems.map((item) => item.id);
    const reorderVisibleNavigation = useCallback((nextVisibleIds) => {
        setNavigationOrder((current) => {
            const visibleIds = new Set(nextVisibleIds);
            let visibleIndex = 0;
            const next = current.map((id) => (
                visibleIds.has(id) ? nextVisibleIds[visibleIndex++] : id
            ));
            _persistNavigationOrder(next);
            return next;
        });
    }, []);
    const navigationReorder = useSidebarReorder({
        ids: visibleNavigationIds,
        onReorder: reorderVisibleNavigation,
    });

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

            <nav ref={navigationReorder.containerRef} className={styles.nav}>
                {orderedNavigationItems.map((item) => {
                    const active = activeItemId === item.id;
                    return (
                        <button
                            key={item.id}
                            ref={(element) => navigationReorder.registerItem(item.id, element)}
                            className={[
                                navigationItemStyles.item,
                                active ? navigationItemStyles.active : '',
                                collapsed ? navigationItemStyles.collapsed : '',
                                navigationReorder.draggingId === item.id
                                    ? navigationItemStyles.dragging
                                    : '',
                            ].filter(Boolean).join(' ')}
                            onPointerDown={(event) => (
                                navigationReorder.onItemPointerDown(item.id, item.label, event)
                            )}
                            onKeyDown={(event) => (
                                navigationReorder.onItemKeyDown(item.id, item.label, event)
                            )}
                            onClick={(event) => {
                                if (navigationReorder.consumeClick(item.id, event)) return;
                                activateNavigationItem(item);
                            }}
                            onContextMenu={(event) => {
                                event.preventDefault();
                                setNavigationMenu({
                                    id: item.id,
                                    label: item.label,
                                    x: event.clientX,
                                    y: event.clientY,
                                });
                            }}
                            title={item.label}
                            aria-label={item.label}
                            aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                            data-reorder-id={item.id}
                            data-testid={`sidebar-nav-${item.id}`}
                        >
                            <i className={`bi ${item.icon}`} />
                            {!collapsed && (
                                <span className={navigationItemStyles.label}>
                                    {item.label}
                                </span>
                            )}
                            {!collapsed && (
                                <span
                                    className={navigationItemStyles.dragHandle}
                                    aria-hidden="true"
                                >
                                    <i className="bi bi-grip-vertical" />
                                </span>
                            )}
                        </button>
                    );
                })}
            </nav>

            <span className={styles.srOnly} role="status" aria-live="polite">
                {navigationReorder.announcement}
            </span>

            {navigationMenu && (
                <SidebarReorderMenu
                    label={navigationMenu.label}
                    x={navigationMenu.x}
                    y={navigationMenu.y}
                    canMoveUp={visibleNavigationIds.indexOf(navigationMenu.id) > 0}
                    canMoveDown={
                        visibleNavigationIds.indexOf(navigationMenu.id) >= 0
                        && visibleNavigationIds.indexOf(navigationMenu.id)
                            < visibleNavigationIds.length - 1
                    }
                    onMoveUp={() => {
                        navigationReorder.moveItem(
                            navigationMenu.id,
                            -1,
                            navigationMenu.label,
                        );
                        closeNavigationMenu();
                    }}
                    onMoveDown={() => {
                        navigationReorder.moveItem(
                            navigationMenu.id,
                            1,
                            navigationMenu.label,
                        );
                        closeNavigationMenu();
                    }}
                    onClose={closeNavigationMenu}
                />
            )}

            {customApps.enabled && (
                <PinnedAppsSidebarSection collapsed={collapsed} />
            )}

            {collapsed ? (
                <>
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
                    <div
                        className={styles.grow}
                        data-testid="sidebar-collapsed-spacer"
                    />
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
