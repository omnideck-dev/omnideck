import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';

import SidebarReorderMenu from '../../../components/SidebarReorderMenu.jsx';
import useSidebarReorder from '../../../components/useSidebarReorder.js';
import {
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
} from '../../navigation/DesktopNavigation.jsx';
import navigationItemStyles from '../../navigation/sidebar/SidebarNavigationItem.module.css';
import { useCustomApps } from '../CustomApps.jsx';
import styles from './PinnedAppsSidebarSection.module.css';

export default function PinnedAppsSidebarSection({ collapsed }) {
    const customApps = useCustomApps();
    const navigation = useDesktopNavigationCommands();
    const navigationTarget = useCurrentNavigationTarget();
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

    if (!customApps.enabled || pinnedApps.length === 0) return null;

    return (
        <section
            ref={sectionRef}
            className={[
                styles.pinnedSection,
                collapsed ? styles.collapsed : '',
            ].filter(Boolean).join(' ')}
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
                                dragging ? navigationItemStyles.dragging : '',
                            ].filter(Boolean).join(' ')}
                            data-reorder-id={app.slug}
                        >
                            <button
                                type="button"
                                className={[
                                    navigationItemStyles.item,
                                    collapsed ? navigationItemStyles.collapsed : '',
                                    styles.pinnedApp,
                                ].filter(Boolean).join(' ')}
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
                                {!collapsed && (
                                    <span className={navigationItemStyles.label}>
                                        {app.title}
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
