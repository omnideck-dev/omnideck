import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react';

import TabContextMenu from './TabContextMenu.jsx';
import styles from './TabStrip.module.css';

/** Accessible, scrollable tab chrome with a shared action menu. */
export default function TabStrip({
    tabs,
    activeTab,
    onTabChange,
    onCloseTab,
    testIds = {},
}) {
    const {
        panel: panelTestId = 'tab-strip',
        tabBar: tabBarTestId = 'tab-bar',
    } = testIds;
    const tabListRef = useRef(null);
    const activeTabRef = useRef(null);
    const [tabMenu, setTabMenu] = useState(null);
    const [tabOverflow, setTabOverflow] = useState({
        hasOverflow: false,
        canScrollLeft: false,
        canScrollRight: false,
    });
    const closeTabMenu = useCallback(() => setTabMenu(null), []);

    const openTabMenu = useCallback((tab, position) => {
        if (!tab.menuActions?.length) return;
        setTabMenu({
            tabId: tab.id,
            position,
        });
    }, []);

    const updateTabOverflow = useCallback(() => {
        const tabList = tabListRef.current;
        if (!tabList) return;

        const maxScrollLeft = Math.max(0, tabList.scrollWidth - tabList.clientWidth);
        const next = {
            hasOverflow: maxScrollLeft > 1,
            canScrollLeft: tabList.scrollLeft > 1,
            canScrollRight: tabList.scrollLeft < maxScrollLeft - 1,
        };
        setTabOverflow((current) => (
            current.hasOverflow === next.hasOverflow
            && current.canScrollLeft === next.canScrollLeft
            && current.canScrollRight === next.canScrollRight
                ? current
                : next
        ));
    }, []);

    const setTabScrollLeft = useCallback((left, behavior = 'smooth') => {
        const tabList = tabListRef.current;
        if (!tabList) return;
        if (typeof tabList.scrollTo === 'function') {
            tabList.scrollTo({ left, behavior });
        } else {
            tabList.scrollLeft = left;
            updateTabOverflow();
        }
    }, [updateTabOverflow]);

    const scrollTabs = useCallback((direction) => {
        const tabList = tabListRef.current;
        if (!tabList) return;
        const distance = Math.max(160, Math.round(tabList.clientWidth * 0.7));
        setTabScrollLeft(tabList.scrollLeft + direction * distance);
    }, [setTabScrollLeft]);

    const revealActiveTab = useCallback(() => {
        const tabList = tabListRef.current;
        const activeElement = activeTabRef.current;
        if (!tabList || !activeElement) return;

        const listRect = tabList.getBoundingClientRect();
        const activeRect = activeElement.getBoundingClientRect();
        let delta = 0;
        if (activeRect.left < listRect.left - 1) {
            delta = activeRect.left - listRect.left;
        } else if (activeRect.right > listRect.right + 1) {
            delta = activeRect.right - listRect.right;
        }
        if (delta === 0) return;

        const maxScrollLeft = Math.max(0, tabList.scrollWidth - tabList.clientWidth);
        tabList.scrollLeft = Math.max(
            0,
            Math.min(maxScrollLeft, tabList.scrollLeft + delta),
        );
        updateTabOverflow();
    }, [updateTabOverflow]);

    const handleTabWheel = useCallback((event) => {
        const tabList = tabListRef.current;
        if (!tabList || !tabOverflow.hasOverflow) return;
        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY)
            ? event.deltaX
            : event.deltaY;
        const maxScrollLeft = tabList.scrollWidth - tabList.clientWidth;
        const canMove = (delta < 0 && tabList.scrollLeft > 0)
            || (delta > 0 && tabList.scrollLeft < maxScrollLeft);
        if (!canMove) return;
        event.preventDefault();
        tabList.scrollLeft += delta;
        updateTabOverflow();
    }, [tabOverflow.hasOverflow, updateTabOverflow]);

    useLayoutEffect(() => {
        const tabList = tabListRef.current;
        if (!tabList) return undefined;

        const handleResize = () => {
            revealActiveTab();
            updateTabOverflow();
        };
        revealActiveTab();
        updateTabOverflow();

        const resizeObserver = typeof ResizeObserver === 'undefined'
            ? null
            : new ResizeObserver(handleResize);
        resizeObserver?.observe(tabList);
        Array.from(tabList.children).forEach((tab) => resizeObserver?.observe(tab));
        window.addEventListener('resize', handleResize);
        return () => {
            resizeObserver?.disconnect();
            window.removeEventListener('resize', handleResize);
        };
    }, [
        activeTab,
        revealActiveTab,
        tabs.length,
        updateTabOverflow,
    ]);

    const menuTab = tabMenu
        ? tabs.find((tab) => tab.id === tabMenu.tabId)
        : null;
    useEffect(() => {
        if (tabMenu && !menuTab) closeTabMenu();
    }, [closeTabMenu, menuTab, tabMenu]);

    return (
        <div className={styles.tabStrip} data-testid={panelTestId}>
            <div className={styles.tabBar} data-testid={tabBarTestId}>
                <button
                    type="button"
                    className={`${styles.tabScrollButton} ${tabOverflow.hasOverflow ? '' : styles.tabScrollButtonHidden}`}
                    onClick={() => scrollTabs(-1)}
                    disabled={!tabOverflow.hasOverflow || !tabOverflow.canScrollLeft}
                    title="Scroll tabs left"
                    aria-label="Scroll tabs left"
                    aria-hidden={!tabOverflow.hasOverflow}
                    tabIndex={tabOverflow.hasOverflow ? 0 : -1}
                    data-testid={`${tabBarTestId}-scroll-left`}
                >
                    <i className="bi bi-chevron-left" aria-hidden="true" />
                </button>
                <div
                    ref={tabListRef}
                    className={styles.tabList}
                    role="tablist"
                    aria-label="Open views"
                    onScroll={updateTabOverflow}
                    onWheel={handleTabWheel}
                >
                    {tabs.map((tab, tabIndex) => {
                        const isActive = tab.id === activeTab;
                        return (
                            <div
                                ref={isActive ? activeTabRef : null}
                                key={tab.id}
                                className={`${styles.tab} ${isActive ? styles.tabActive : ''}`}
                                onContextMenu={(event) => {
                                    if (!tab.menuActions?.length) return;
                                    event.preventDefault();
                                    event.stopPropagation();
                                    openTabMenu(tab, {
                                        x: event.clientX,
                                        y: event.clientY,
                                    });
                                }}
                            >
                                <button
                                    className={`${styles.tabSelection} ${isActive ? styles.tabActive : ''}`}
                                    onClick={() => onTabChange(tab.id)}
                                    onKeyDown={(event) => {
                                        const lastIndex = tabs.length - 1;
                                        const targetIndex = {
                                            ArrowLeft: (
                                                tabIndex === 0
                                                    ? lastIndex
                                                    : tabIndex - 1
                                            ),
                                            ArrowRight: (
                                                tabIndex === lastIndex
                                                    ? 0
                                                    : tabIndex + 1
                                            ),
                                            Home: 0,
                                            End: lastIndex,
                                        }[event.key];
                                        if (targetIndex !== undefined) {
                                            event.preventDefault();
                                            const targetTab = tabs[targetIndex];
                                            onTabChange(targetTab.id);
                                            const buttons = tabListRef.current
                                                ?.querySelectorAll('[role="tab"]');
                                            buttons?.[targetIndex]?.focus();
                                            return;
                                        }
                                        const opensContextMenu = event.key === 'ContextMenu'
                                            || (event.shiftKey && event.key === 'F10');
                                        if (!opensContextMenu || !tab.menuActions?.length) return;
                                        event.preventDefault();
                                        const rect = event.currentTarget.getBoundingClientRect();
                                        openTabMenu(tab, {
                                            x: rect.left,
                                            y: rect.bottom,
                                        });
                                    }}
                                    role="tab"
                                    aria-selected={isActive}
                                    tabIndex={isActive ? 0 : -1}
                                    title={tab.label}
                                    aria-haspopup={tab.menuActions?.length ? 'menu' : undefined}
                                    data-testid={`view-tab-${tab.testid || tab.id}`}
                                >
                                    <span className={styles.tabIcon}>{tab.icon}</span>
                                    <span className={styles.tabLabel}>{tab.label}</span>
                                </button>
                                {isActive && tab.menuActions?.length > 0 && (
                                    <button
                                        type="button"
                                        className={styles.tabMenuButton}
                                        onClick={(event) => {
                                            event.stopPropagation();
                                            const rect = event.currentTarget
                                                .getBoundingClientRect();
                                            openTabMenu(tab, {
                                                x: rect.left,
                                                y: rect.bottom,
                                            });
                                        }}
                                        title="Tab actions"
                                        aria-label={`Actions for ${tab.label} tab`}
                                        aria-haspopup="menu"
                                        aria-expanded={tabMenu?.tabId === tab.id}
                                        data-testid={`view-tab-actions-${tab.testid || tab.id}`}
                                    >
                                        <i
                                            className="bi bi-three-dots"
                                            aria-hidden="true"
                                        />
                                    </button>
                                )}
                                {tab.closable !== false
                                    && !tab.menuActions?.length && (
                                    <button
                                        className={styles.tabClose}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            onCloseTab(tab.id);
                                        }}
                                        title="Close tab"
                                        aria-label={`Close ${tab.label} tab`}
                                        data-testid={`close-view-tab-${tab.testid || tab.id}`}
                                    >
                                        ×
                                    </button>
                                    )}
                            </div>
                        );
                    })}
                </div>
                <button
                    type="button"
                    className={`${styles.tabScrollButton} ${tabOverflow.hasOverflow ? '' : styles.tabScrollButtonHidden}`}
                    onClick={() => scrollTabs(1)}
                    disabled={!tabOverflow.hasOverflow || !tabOverflow.canScrollRight}
                    title="Scroll tabs right"
                    aria-label="Scroll tabs right"
                    aria-hidden={!tabOverflow.hasOverflow}
                    tabIndex={tabOverflow.hasOverflow ? 0 : -1}
                    data-testid={`${tabBarTestId}-scroll-right`}
                >
                    <i className="bi bi-chevron-right" aria-hidden="true" />
                </button>
            </div>
            {menuTab && (
                <TabContextMenu
                    actions={menuTab.menuActions}
                    position={tabMenu.position}
                    testid={`view-tab-menu-${menuTab.testid || menuTab.id}`}
                    onClose={closeTabMenu}
                />
            )}
        </div>
    );
}
