import React, {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';
import AudioPlayer from './AudioPlayer.jsx';
import ConversationsPanel from './ConversationsPanel.jsx';
import SidebarReorderMenu from './SidebarReorderMenu.jsx';
import { useTheme } from '../contexts/Theme.jsx';
import { useCustomApps } from '../features/customApps/CustomApps.jsx';
import {
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
} from '../features/navigation/DesktopNavigation.jsx';
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

function PinnedAppsSection({
    collapsed,
    customApps,
    navigation,
    navigationTarget,
}) {
    const [pickerOpen, setPickerOpen] = useState(false);
    const [itemMenu, setItemMenu] = useState(null);
    const sectionRef = useRef(null);
    const appsBySlug = useMemo(
        () => new Map(customApps.catalog.apps.map((app) => [app.slug, app])),
        [customApps.catalog.apps],
    );
    const pinnedApps = customApps.pinnedAppSlugs
        .map((slug) => appsBySlug.get(slug))
        .filter(Boolean);
    const pinnedSlugs = useMemo(
        () => new Set(customApps.pinnedAppSlugs),
        [customApps.pinnedAppSlugs],
    );
    const availableApps = customApps.catalog.apps.filter(
        (app) => !pinnedSlugs.has(app.slug),
    );
    const pinnedIds = pinnedApps.map((app) => app.slug);
    const reorder = useSidebarReorder({
        ids: pinnedIds,
        onReorder: customApps.reorderPinnedApps,
    });
    const closeItemMenu = useCallback(() => setItemMenu(null), []);

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

    if (pinnedApps.length === 0) return null;

    return (
        <section
            ref={sectionRef}
            className={styles.pinnedSection}
            data-testid="sidebar-pinned-section"
        >
            {!collapsed && (
                <div className={styles.sectionHeader}>
                    <span>Apps</span>
                    <button
                        type="button"
                        className={styles.sectionAction}
                        onClick={() => setPickerOpen((open) => !open)}
                        title="Pin an App"
                        aria-label="Pin an App"
                        aria-haspopup="menu"
                        aria-expanded={pickerOpen}
                        data-testid="sidebar-pinned-add"
                    >
                        <i className="bi bi-plus-lg" />
                    </button>
                </div>
            )}

            <div ref={reorder.containerRef} className={styles.pinnedList}>
                {pinnedApps.map((app) => {
                    const active = navigationTarget?.kind === 'custom-app'
                        && navigationTarget.appSlug === app.slug;
                    const dragging = reorder.draggingId === app.slug;
                    return (
                        <div
                            key={app.slug}
                            ref={(element) => reorder.registerItem(app.slug, element)}
                            className={[
                                styles.pinnedItem,
                                active ? styles.active : '',
                                dragging ? styles.dragging : '',
                            ].filter(Boolean).join(' ')}
                            data-reorder-id={app.slug}
                        >
                            <button
                                type="button"
                                className={`${styles.navItem} ${styles.pinnedApp}`}
                                onPointerDown={(event) => (
                                    reorder.onItemPointerDown(app.slug, app.title, event)
                                )}
                                onKeyDown={(event) => (
                                    reorder.onItemKeyDown(app.slug, app.title, event)
                                )}
                                onClick={(event) => {
                                    if (reorder.consumeClick(app.slug, event)) return;
                                    if (active) navigation.openChat();
                                    else navigation.openCustomApp(app.slug);
                                }}
                                onContextMenu={(event) => {
                                    event.preventDefault();
                                    setItemMenu({
                                        id: app.slug,
                                        label: app.title,
                                        x: event.clientX,
                                        y: event.clientY,
                                    });
                                }}
                                title={app.title}
                                aria-label={app.title}
                                aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                                data-reorder-id={app.slug}
                                data-testid={`sidebar-pinned-app-${app.slug}`}
                            >
                                <i className={`bi ${app.icon || 'bi-window'}`} />
                                {!collapsed && <span className={styles.navLabel}>{app.title}</span>}
                                {!collapsed && (
                                    <span className={styles.dragHandle} aria-hidden="true">
                                        <i className="bi bi-grip-vertical" />
                                    </span>
                                )}
                            </button>
                        </div>
                    );
                })}
            </div>

            <span className={styles.srOnly} role="status" aria-live="polite">
                {reorder.announcement}
            </span>

            {!collapsed && pickerOpen && (
                <div
                    className={styles.pinPicker}
                    role="menu"
                    aria-label="Apps available to pin"
                    data-testid="sidebar-pinned-picker"
                >
                    {customApps.catalog.loading && (
                        <div className={styles.pinPickerStatus}>Loading Apps…</div>
                    )}
                    {!customApps.catalog.loading && availableApps.length === 0 && (
                        <div className={styles.pinPickerStatus}>All Apps are pinned</div>
                    )}
                    {availableApps.map((app) => (
                        <button
                            key={app.slug}
                            type="button"
                            role="menuitem"
                            className={styles.pinPickerItem}
                            onClick={() => {
                                customApps.pinApp(app.slug);
                                setPickerOpen(false);
                            }}
                            data-testid={`sidebar-pin-option-${app.slug}`}
                        >
                            <i className={`bi ${app.icon || 'bi-window'}`} />
                            <span>{app.title}</span>
                        </button>
                    ))}
                </div>
            )}

            {itemMenu && (
                <SidebarReorderMenu
                    label={itemMenu.label}
                    x={itemMenu.x}
                    y={itemMenu.y}
                    canMoveUp={pinnedIds.indexOf(itemMenu.id) > 0}
                    canMoveDown={
                        pinnedIds.indexOf(itemMenu.id) >= 0
                        && pinnedIds.indexOf(itemMenu.id) < pinnedIds.length - 1
                    }
                    onMoveUp={() => {
                        reorder.moveItem(itemMenu.id, -1, itemMenu.label);
                        closeItemMenu();
                    }}
                    onMoveDown={() => {
                        reorder.moveItem(itemMenu.id, 1, itemMenu.label);
                        closeItemMenu();
                    }}
                    onUnpin={() => {
                        customApps.unpinApp(itemMenu.id);
                        closeItemMenu();
                    }}
                    onClose={closeItemMenu}
                />
            )}
        </section>
    );
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
                                styles.navItem,
                                active ? styles.active : '',
                                navigationReorder.draggingId === item.id ? styles.dragging : '',
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
                            {!collapsed && <span className={styles.navLabel}>{item.label}</span>}
                            {!collapsed && (
                                <span className={styles.dragHandle} aria-hidden="true">
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
                <PinnedAppsSection
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
