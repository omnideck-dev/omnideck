import {
    useCallback,
    useEffect,
    useState,
} from 'react';

import SplitHandle from '../../components/SplitHandle.jsx';
import DesktopTabGroup from './DesktopTabGroup.jsx';
import DesktopViewHost from './DesktopViewHost.jsx';
import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import { tabGroupContainingView } from './desktopLayoutSelectors.js';
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
    onFocusView,
    onCloseView,
    getViewActions,
    renderView,
}) {
    const [liveSplitRatio, setLiveSplitRatio] = useState(null);

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
    const split = leftVisible && rightVisible;
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

            {rightVisible && (
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
                const activeInTabGroup = Boolean(
                    tabGroupId && model.tabGroups[tabGroupId].activeViewId === view.id,
                );
                const floatingView = model.floatingByViewId?.[
                    view.id
                ] || null;
                const fullscreen = model.fullscreenViewId === view.id;
                return (
                    <DesktopViewHost
                        key={view.id}
                        view={view}
                        tabGroupId={tabGroupId}
                        activeInTabGroup={activeInTabGroup}
                        floatingView={floatingView}
                        focusedFloating={
                            model.focusedFloatingViewId === view.id
                        }
                        fullscreen={fullscreen}
                        commands={commands}
                        onFocusView={onFocusView}
                        getViewActions={getViewActions}
                        renderView={renderView}
                    />
                );
            })}
        </div>
    );
}
