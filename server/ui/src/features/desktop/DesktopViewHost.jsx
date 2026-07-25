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

function ViewIdentity({ view, iconClass, titleClass }) {
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

/** Shared chrome for the two placements that render a title bar. */
function ViewHostHeader({
    visible,
    view,
    actions,
    placement,
    dragHandlers = {},
    onExitFullscreen = null,
}) {
    const floating = placement === DESKTOP_ACTION_PLACEMENTS.FLOATING;
    const headerClass = floating
        ? styles.floatingHeader
        : styles.fullscreenHeader;
    const visibleClass = floating
        ? styles.floatingHeaderVisible
        : styles.fullscreenHeaderVisible;
    const identityClass = floating
        ? styles.floatingIdentity
        : styles.fullscreenIdentity;
    const iconClass = floating
        ? styles.floatingIcon
        : styles.fullscreenIcon;
    const titleClass = floating
        ? styles.floatingTitle
        : styles.fullscreenTitle;
    const actionsClass = floating
        ? styles.floatingActions
        : styles.fullscreenActions;
    const testIdPrefix = floating
        ? 'floating-view-header'
        : 'fullscreen-view-header';
    const viewKey = view.testid || view.id;

    return (
        <header
            className={[
                headerClass,
                visible ? visibleClass : '',
            ].filter(Boolean).join(' ')}
            aria-hidden={!visible}
            data-testid={`${testIdPrefix}-${viewKey}`}
            {...dragHandlers}
        >
            {visible && (
                <>
                    <div className={identityClass}>
                        <ViewIdentity
                            view={view}
                            iconClass={iconClass}
                            titleClass={titleClass}
                        />
                    </div>
                    <div className={actionsClass}>
                        <DesktopViewActionBar
                            actions={actions}
                            placement={placement}
                        />
                        {onExitFullscreen && (
                            <button
                                type="button"
                                className={styles.restoreView}
                                onClick={onExitFullscreen}
                                title="Exit full screen"
                                aria-label="Exit full screen"
                                data-testid={`restore-view-${viewKey}`}
                            >
                                <i className="bi bi-fullscreen-exit" />
                            </button>
                        )}
                    </div>
                </>
            )}
        </header>
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
            data-view-owner-id={view.testMetadata?.ownerId || ''}
            data-view-resource-id={view.testMetadata?.resourceId || ''}
            data-tab-group-id={floating ? 'floating' : (tabGroupId || 'hidden')}
            data-active={active ? 'true' : 'false'}
            data-floating={floating ? 'true' : 'false'}
            data-fullscreen={fullscreen ? 'true' : 'false'}
            data-maximized={fullscreen ? 'true' : 'false'}
        >
            <ViewHostHeader
                visible={floating && !fullscreen}
                view={view}
                actions={actions}
                placement={DESKTOP_ACTION_PLACEMENTS.FLOATING}
                dragHandlers={{
                    onPointerDown: startDrag,
                    onPointerMove: drag,
                    onPointerUp: endDrag,
                    onPointerCancel: endDrag,
                }}
            />

            <ViewHostHeader
                visible={fullscreen}
                view={view}
                actions={actions}
                placement={DESKTOP_ACTION_PLACEMENTS.FULLSCREEN}
                onExitFullscreen={() => commands.setFullscreenView(null)}
            />

            {content}
        </div>
    );
}

// A live split drag re-renders DesktopLayout to move the divider. Stable host
// props keep domain renderers asleep until a property of their own View
// actually changes.
export default memo(DesktopViewHost);
