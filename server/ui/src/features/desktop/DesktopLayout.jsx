import {
    useCallback,
    useEffect,
    useState,
} from 'react';

import SplitHandle from '../../components/SplitHandle.jsx';
import useIsMobileViewport from '../../hooks/useIsMobileViewport.js';
import DesktopTabGroup from './DesktopTabGroup.jsx';
import DesktopViewHost from './DesktopViewHost.jsx';
import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import { tabGroupContainingView, visibleTabGroupIds, visibleViewIds } from './desktopLayoutSelectors.js';
import styles from './DesktopLayout.module.css';

/**
 * Renders two equivalent tab groups and floating views over one stable
 * view layer.
 *
 * Every open view has one keyed host. Moving it changes its grid
 * column instead of its React parent, preserving iframe and component state.
 */
export default function DesktopLayout({
    model,
    commands,
    onSelectView,
    onCloseView,
    getViewActions,
    renderView,
}) {
    const [liveSplitRatio, setLiveSplitRatio] = useState(null);
    const isMobile = useIsMobileViewport();

    useEffect(() => {
        if (!model.fullscreenViewId) return undefined;
        const restoreOnEscape = (event) => {
            if (event.key === 'Escape') commands.setFullscreenView(null);
        };
        document.addEventListener('keydown', restoreOnEscape);
        return () => document.removeEventListener('keydown', restoreOnEscape);
    }, [commands.setFullscreenView, model.fullscreenViewId]);

    const leftTabGroup = model.tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT];
    const rightTabGroup = model.tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT];
    const leftVisible = leftTabGroup.viewIds.length > 0;
    const rightVisible = rightTabGroup.viewIds.length > 0;
    const shownTabGroups = visibleTabGroupIds(model, isMobile);
    const visibleIds = visibleViewIds(model, isMobile);
    const split = shownTabGroups.length === 2;
    const showRightTabGroup = shownTabGroups.includes(DESKTOP_TAB_GROUP_IDS.RIGHT);

    useEffect(() => {
        // Both panes can end up populated on mobile — restored two-pane
        // layout state, or a desktop window resized down below the mobile
        // breakpoint. Merge the hidden pane into the visible one so its
        // views stay reachable instead of stranding them with no chrome to
        // select or move them from. Uses the dedicated merge command, not
        // moveView: moveView is built for an explicit user placement change
        // (it activates the moved view and clears floating focus), and this
        // is an automatic reconciliation that must not silently steal the
        // active tab or unrelated floating focus out from under the user.
        if (!isMobile || !leftVisible || !rightVisible) return;
        commands.mergeTabGroup(
            DESKTOP_TAB_GROUP_IDS.RIGHT,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        );
    }, [commands, isMobile, leftVisible, rightVisible]);
    const fullscreenActive = Boolean(model.fullscreenViewId);
    const visibleSplitRatio = liveSplitRatio ?? model.splitRatio;
    const gridTemplateColumns = split
        ? `${visibleSplitRatio}fr 9px ${100 - visibleSplitRatio}fr`
        : (leftVisible ? '1fr 0 0' : '0 0 1fr');
    const commitSplitRatio = useCallback((ratio) => {
        // The local value drives every mousemove. Release it in the same event
        // that commits once to the reducer, avoiding a frame at the old ratio.
        setLiveSplitRatio(null);
        commands.setSplitRatio(ratio);
    }, [commands.setSplitRatio]);

    useEffect(() => {
        if (!split) setLiveSplitRatio(null);
    }, [split]);

    return (
        <div
            className={styles.layout}
            style={{ gridTemplateColumns }}
            data-testid="desktop-layout"
            data-layout="horizontal-split"
            data-split={split ? 'true' : 'false'}
        >
            {leftVisible && (
                <div
                    className={[
                        styles.leftTabGroup,
                        fullscreenActive ? styles.tabGroupChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    aria-hidden={fullscreenActive}
                >
                    <DesktopTabGroup
                        tabGroupId={DESKTOP_TAB_GROUP_IDS.LEFT}
                        tabGroup={leftTabGroup}
                        split={split}
                        onSelectView={onSelectView}
                        onCloseView={onCloseView}
                        getViewActions={getViewActions}
                        fullscreenViewId={model.fullscreenViewId}
                    />
                </div>
            )}

            {split && (
                <SplitHandle
                    className={[
                        styles.splitHandle,
                        fullscreenActive ? styles.tabGroupChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    onDrag={setLiveSplitRatio}
                    onDragEnd={commitSplitRatio}
                />
            )}

            {showRightTabGroup && (
                <div
                    className={[
                        styles.rightTabGroup,
                        fullscreenActive ? styles.tabGroupChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    aria-hidden={fullscreenActive}
                >
                    <DesktopTabGroup
                        tabGroupId={DESKTOP_TAB_GROUP_IDS.RIGHT}
                        tabGroup={rightTabGroup}
                        split={split}
                        onSelectView={onSelectView}
                        onCloseView={onCloseView}
                        getViewActions={getViewActions}
                        fullscreenViewId={model.fullscreenViewId}
                    />
                </div>
            )}

            {model.openViews.map((view) => {
                const tabGroupId = tabGroupContainingView(model.tabGroups, view.id);
                const floatingView = model.floatingByViewId?.[
                    view.id
                ] || null;
                const fullscreen = model.fullscreenViewId === view.id;
                return (
                    <DesktopViewHost
                        key={view.id}
                        view={view}
                        tabGroupId={tabGroupId}
                        visible={visibleIds.includes(view.id)}
                        floatingView={floatingView}
                        focusedFloating={
                            model.focusedFloatingViewId === view.id
                        }
                        fullscreen={fullscreen}
                        commands={commands}
                        getViewActions={getViewActions}
                        renderView={renderView}
                    />
                );
            })}
        </div>
    );
}
