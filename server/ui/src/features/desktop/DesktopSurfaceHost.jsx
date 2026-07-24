import {
    useCallback,
    useEffect,
    useRef,
} from 'react';

import DesktopSurfaceActionBar from './DesktopSurfaceActionBar.jsx';
import { DESKTOP_ACTION_PLACEMENTS } from './desktopSurfaceActions.js';
import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';
import styles from './DesktopWindowLayout.module.css';

const MIN_VISIBLE_TITLE_WIDTH = 120;
const MIN_VISIBLE_TITLE_HEIGHT = 36;

function surfaceIdentity(surface, iconClass, titleClass) {
    return (
        <>
            <span className={iconClass}>
                {surface.iconElement || (
                    <i className={`bi ${surface.icon || 'bi-window'}`} />
                )}
            </span>
            <span className={titleClass} title={surface.label}>
                {surface.label}
            </span>
        </>
    );
}

/**
 * One stable host for a surface in docked, floating, or full-screen placement.
 *
 * Placement changes only CSS and chrome around the keyed content, so an
 * iframe or feature component remains mounted while it moves.
 */
export default function DesktopSurfaceHost({
    surface,
    paneId,
    activeInPane,
    floatingWindow,
    focusedFloating,
    fullscreen,
    commands,
    onFocusSurface,
    getSurfaceActions,
    renderSurface,
}) {
    const hostRef = useRef(null);
    const dragRef = useRef(null);
    const floating = Boolean(floatingWindow);
    const active = Boolean(floating || (paneId && activeInPane));

    const focusSurface = useCallback(() => {
        if (!floating) return;
        commands.focusFloatingSurface(surface.id);
        onFocusSurface?.(surface.id);
    }, [
        commands.focusFloatingSurface,
        floating,
        onFocusSurface,
        surface.id,
    ]);
    const focusEmbeddedSurface = useCallback((event) => {
        if (event.target.tagName === 'IFRAME') focusSurface();
    }, [focusSurface]);

    const clampPosition = useCallback((x, y) => {
        const viewportWidth = window.visualViewport?.width
            || window.innerWidth
            || document.documentElement.clientWidth;
        const viewportHeight = window.visualViewport?.height
            || window.innerHeight
            || document.documentElement.clientHeight;
        if (!viewportWidth || !viewportHeight) {
            return { x: Math.max(0, x), y: Math.max(0, y) };
        }
        return {
            x: Math.max(
                0,
                Math.min(
                    x,
                    viewportWidth - MIN_VISIBLE_TITLE_WIDTH,
                ),
            ),
            y: Math.max(
                0,
                Math.min(
                    y,
                    viewportHeight - MIN_VISIBLE_TITLE_HEIGHT,
                ),
            ),
        };
    }, []);

    const startDrag = useCallback((event) => {
        if (
            !floatingWindow
            || fullscreen
            || event.button !== 0
            || event.target.closest?.('button')
        ) {
            return;
        }
        event.preventDefault();
        dragRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            x: floatingWindow.x,
            y: floatingWindow.y,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
    }, [floatingWindow, fullscreen]);

    const drag = useCallback((event) => {
        const current = dragRef.current;
        if (!current || current.pointerId !== event.pointerId) return;
        const position = clampPosition(
            current.x + event.clientX - current.startX,
            current.y + event.clientY - current.startY,
        );
        commands.updateFloatingBounds(surface.id, position);
    }, [
        clampPosition,
        commands.updateFloatingBounds,
        surface.id,
    ]);

    const endDrag = useCallback((event) => {
        if (dragRef.current?.pointerId !== event.pointerId) return;
        dragRef.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
    }, []);

    useEffect(() => {
        if (!floating || fullscreen) return undefined;
        const keepTitleReachable = () => {
            const position = clampPosition(
                floatingWindow.x,
                floatingWindow.y,
            );
            if (
                position.x !== floatingWindow.x
                || position.y !== floatingWindow.y
            ) {
                commands.updateFloatingBounds(surface.id, position);
            }
        };
        keepTitleReachable();
        window.addEventListener('resize', keepTitleReachable);
        return () => window.removeEventListener('resize', keepTitleReachable);
    }, [
        clampPosition,
        commands.updateFloatingBounds,
        floating,
        floatingWindow?.x,
        floatingWindow?.y,
        fullscreen,
        surface.id,
    ]);

    useEffect(() => {
        if (!floating || fullscreen || typeof ResizeObserver === 'undefined') {
            return undefined;
        }
        const host = hostRef.current;
        if (!host) return undefined;
        const observer = new ResizeObserver(() => {
            const width = host.offsetWidth;
            const height = host.offsetHeight;
            if (
                width > 0
                && height > 0
                && (
                    Math.abs(width - floatingWindow.width) > 1
                    || Math.abs(height - floatingWindow.height) > 1
                )
            ) {
                commands.updateFloatingBounds(surface.id, { width, height });
            }
        });
        observer.observe(host);
        return () => observer.disconnect();
    }, [
        commands.updateFloatingBounds,
        floating,
        floatingWindow?.height,
        floatingWindow?.width,
        fullscreen,
        surface.id,
    ]);

    const actions = getSurfaceActions?.(
        surface,
        paneId,
        { floating },
    ) || [];
    const floatingStyle = floating && !fullscreen
        ? {
            left: floatingWindow.x,
            top: floatingWindow.y,
            width: floatingWindow.width,
            height: floatingWindow.height,
            // Keep all floating windows below the shared full-screen layer.
            zIndex: 20 + Math.min(floatingWindow.zIndex, 400),
        }
        : undefined;

    return (
        <div
            ref={hostRef}
            className={[
                styles.surfaceHost,
                paneId === DESKTOP_PANE_IDS.LEFT ? styles.leftSurface : '',
                paneId === DESKTOP_PANE_IDS.RIGHT ? styles.rightSurface : '',
                floating ? styles.floatingSurface : '',
                focusedFloating ? styles.focusedFloatingSurface : '',
                active ? styles.activeSurface : styles.hiddenSurface,
                fullscreen ? styles.fullscreenSurface : '',
            ].filter(Boolean).join(' ')}
            style={floatingStyle}
            role={floating && !fullscreen ? 'region' : undefined}
            aria-label={floating && !fullscreen
                ? `${surface.label} floating window`
                : undefined}
            onPointerDownCapture={focusSurface}
            onFocusCapture={focusEmbeddedSurface}
            data-testid={`desktop-surface-${surface.testid || surface.id}`}
            data-surface-id={surface.id}
            data-surface-kind={surface.kind}
            data-surface-owner-id={surface.agentId || surface.resourceId || ''}
            data-surface-resource-id={surface.resourceId || ''}
            data-pane-id={floating ? 'floating' : (paneId || 'hidden')}
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
                data-testid={`floating-surface-header-${surface.testid || surface.id}`}
            >
                {floating && !fullscreen && (
                    <>
                        <div className={styles.floatingIdentity}>
                            {surfaceIdentity(
                                surface,
                                styles.floatingIcon,
                                styles.floatingTitle,
                            )}
                        </div>
                        <div className={styles.floatingActions}>
                            <DesktopSurfaceActionBar
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
                data-testid={`fullscreen-surface-header-${surface.testid || surface.id}`}
            >
                {fullscreen && (
                    <>
                        <div className={styles.fullscreenIdentity}>
                            {surfaceIdentity(
                                surface,
                                styles.fullscreenIcon,
                                styles.fullscreenTitle,
                            )}
                        </div>
                        <div className={styles.fullscreenActions}>
                            <DesktopSurfaceActionBar
                                actions={actions}
                                placement={DESKTOP_ACTION_PLACEMENTS.FULLSCREEN}
                            />
                            <button
                                type="button"
                                className={styles.restoreSurface}
                                onClick={() => commands.setFullscreenSurface(null)}
                                title="Exit full screen"
                                aria-label="Exit full screen"
                                data-testid={`restore-surface-${surface.testid || surface.id}`}
                            >
                                <i className="bi bi-fullscreen-exit" />
                            </button>
                        </div>
                    </>
                )}
            </header>

            {renderSurface(surface, {
                active,
                paneId,
                floating,
            })}
        </div>
    );
}
