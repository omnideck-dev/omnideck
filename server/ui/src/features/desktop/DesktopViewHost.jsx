import {
    useCallback,
    memo,
    useMemo,
    useRef,
} from 'react';

import DesktopViewActionBar from './DesktopViewActionBar.jsx';
import { DESKTOP_ACTION_PLACEMENTS } from './desktopViewActions.js';
import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import useFloatingViewBounds from './useFloatingViewBounds.js';
import styles from './DesktopLayout.module.css';

function viewIdentity(view, iconClass, titleClass) {
    return (
        <>
            <span className={iconClass}>
                {view.iconElement || (
                    <i className={`bi ${view.icon || 'bi-window'}`} />
                )}
            </span>
            <span className={titleClass} title={view.label}>
                {view.label}
            </span>
        </>
    );
}

/**
 * One stable host for a view in docked, floating, or full-screen placement.
 *
 * Placement changes only CSS and chrome around the keyed content, so an
 * iframe or domain component remains mounted while it moves.
 */
function DesktopViewHost({
    view,
    tabGroupId,
    activeInTabGroup,
    floatingView,
    focusedFloating,
    fullscreen,
    commands,
    getViewActions,
    renderView,
}) {
    const hostRef = useRef(null);
    const floating = Boolean(floatingView);
    const active = Boolean(floating || (tabGroupId && activeInTabGroup));
    const {
        bounds: liveBounds,
        drag,
        endDrag,
        startDrag,
    } = useFloatingViewBounds({
        viewId: view.id,
        floatingView,
        fullscreen,
        commands,
        hostRef,
    });

    const focusView = useCallback(() => {
        if (!floating) return;
        commands.focusFloatingView(view.id);
    }, [
        commands.focusFloatingView,
        floating,
        view.id,
    ]);
    const focusEmbeddedView = useCallback((event) => {
        if (event.target.tagName === 'IFRAME') focusView();
    }, [focusView]);

    const actions = getViewActions?.(
        view,
        tabGroupId,
        { floating },
    ) || [];
    const floatingStyle = floating && !fullscreen
        ? {
            left: liveBounds?.x ?? floatingView.x,
            top: liveBounds?.y ?? floatingView.y,
            width: liveBounds?.width ?? floatingView.width,
            height: liveBounds?.height ?? floatingView.height,
            // Keep all floating views below the shared full-screen layer.
            zIndex: 20 + floatingView.zIndex,
        }
        : undefined;
    const content = useMemo(() => renderView(view, {
        active,
        tabGroupId,
        floating,
    }), [
        active,
        floating,
        renderView,
        tabGroupId,
        view,
    ]);

    return (
        <div
            ref={hostRef}
            className={[
                styles.viewHost,
                tabGroupId === DESKTOP_TAB_GROUP_IDS.LEFT ? styles.leftView : '',
                tabGroupId === DESKTOP_TAB_GROUP_IDS.RIGHT ? styles.rightView : '',
                floating ? styles.floatingView : '',
                focusedFloating ? styles.focusedFloatingView : '',
                active ? styles.activeView : styles.hiddenView,
                fullscreen ? styles.fullscreenView : '',
            ].filter(Boolean).join(' ')}
            style={floatingStyle}
            role={floating && !fullscreen ? 'region' : undefined}
            aria-label={floating && !fullscreen
                ? `${view.label} floating view`
                : undefined}
            onPointerDownCapture={focusView}
            onFocusCapture={focusEmbeddedView}
            data-testid={`desktop-view-${view.testid || view.id}`}
            data-view-id={view.id}
            data-view-type={view.type}
            data-view-owner-id={view.agentId || view.resourceId || ''}
            data-view-resource-id={view.resourceId || ''}
            data-tab-group-id={floating ? 'floating' : (tabGroupId || 'hidden')}
            data-active={active ? 'true' : 'false'}
            data-floating={floating ? 'true' : 'false'}
            data-fullscreen={fullscreen ? 'true' : 'false'}
            data-maximized={fullscreen ? 'true' : 'false'}
        >
            <header
                className={[
                    styles.floatingHeader,
                    floating && !fullscreen
                        ? styles.floatingHeaderVisible
                        : '',
                ].filter(Boolean).join(' ')}
                aria-hidden={!floating || fullscreen}
                onPointerDown={startDrag}
                onPointerMove={drag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                data-testid={`floating-view-header-${view.testid || view.id}`}
            >
                {floating && !fullscreen && (
                    <>
                        <div className={styles.floatingIdentity}>
                            {viewIdentity(
                                view,
                                styles.floatingIcon,
                                styles.floatingTitle,
                            )}
                        </div>
                        <div className={styles.floatingActions}>
                            <DesktopViewActionBar
                                actions={actions}
                                placement={DESKTOP_ACTION_PLACEMENTS.FLOATING}
                            />
                        </div>
                    </>
                )}
            </header>

            <header
                className={[
                    styles.fullscreenHeader,
                    fullscreen ? styles.fullscreenHeaderVisible : '',
                ].filter(Boolean).join(' ')}
                aria-hidden={!fullscreen}
                data-testid={`fullscreen-view-header-${view.testid || view.id}`}
            >
                {fullscreen && (
                    <>
                        <div className={styles.fullscreenIdentity}>
                            {viewIdentity(
                                view,
                                styles.fullscreenIcon,
                                styles.fullscreenTitle,
                            )}
                        </div>
                        <div className={styles.fullscreenActions}>
                            <DesktopViewActionBar
                                actions={actions}
                                placement={DESKTOP_ACTION_PLACEMENTS.FULLSCREEN}
                            />
                            <button
                                type="button"
                                className={styles.restoreView}
                                onClick={() => commands.setFullscreenView(null)}
                                title="Exit full screen"
                                aria-label="Exit full screen"
                                data-testid={`restore-view-${view.testid || view.id}`}
                            >
                                <i className="bi bi-fullscreen-exit" />
                            </button>
                        </div>
                    </>
                )}
            </header>

            {content}
        </div>
    );
}

// A live split drag re-renders DesktopLayout to move the divider. Stable host
// props keep domain renderers asleep until a property of their own View
// actually changes.
export default memo(DesktopViewHost);
