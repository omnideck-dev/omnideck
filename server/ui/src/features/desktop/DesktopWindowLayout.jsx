import { useEffect } from 'react';

import SplitHandle from '../../components/SplitHandle.jsx';
import DesktopPane from './DesktopPane.jsx';
import DesktopSurfaceHost from './DesktopSurfaceHost.jsx';
import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';
import styles from './DesktopWindowLayout.module.css';

function paneContainingSurface(panes, surfaceId) {
    return Object.entries(panes).find(([, pane]) => (
        pane.surfaceIds.includes(surfaceId)
    ))?.[0] || null;
}

/**
 * Renders two equivalent tab stacks and floating windows over one stable
 * surface layer.
 *
 * Every registered surface has one keyed host. Moving it changes its grid
 * column instead of its React parent, preserving iframe and component state.
 */
export default function DesktopWindowLayout({
    model,
    commands,
    onSelectSurface,
    onFocusSurface,
    onCloseSurface,
    getSurfaceActions,
    renderSurface,
}) {
    useEffect(() => {
        if (!model.fullscreenSurfaceId) return undefined;
        const restoreOnEscape = (event) => {
            if (event.key === 'Escape') commands.setFullscreenSurface(null);
        };
        document.addEventListener('keydown', restoreOnEscape);
        return () => document.removeEventListener('keydown', restoreOnEscape);
    }, [commands.setFullscreenSurface, model.fullscreenSurfaceId]);

    const leftPane = model.panes[DESKTOP_PANE_IDS.LEFT];
    const rightPane = model.panes[DESKTOP_PANE_IDS.RIGHT];
    const leftVisible = leftPane.surfaceIds.length > 0;
    const rightVisible = rightPane.surfaceIds.length > 0;
    const split = leftVisible && rightVisible;
    const fullscreenActive = Boolean(model.fullscreenSurfaceId);
    const gridTemplateColumns = split
        ? `${model.splitRatio}fr 9px ${100 - model.splitRatio}fr`
        : (leftVisible ? '1fr 0 0' : '0 0 1fr');

    return (
        <div
            className={styles.layout}
            style={{ gridTemplateColumns }}
            data-testid="desktop-window-layout"
            data-layout="horizontal-split"
            data-split={split ? 'true' : 'false'}
        >
            {leftVisible && (
                <div
                    className={[
                        styles.leftPane,
                        fullscreenActive ? styles.paneChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    aria-hidden={fullscreenActive}
                >
                    <DesktopPane
                        paneId={DESKTOP_PANE_IDS.LEFT}
                        pane={leftPane}
                        split={split}
                        onSelectSurface={onSelectSurface}
                        onCloseSurface={onCloseSurface}
                        getSurfaceActions={getSurfaceActions}
                        fullscreenSurfaceId={model.fullscreenSurfaceId}
                    />
                </div>
            )}

            {split && (
                <SplitHandle
                    className={[
                        styles.splitHandle,
                        fullscreenActive ? styles.paneChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    onDrag={commands.setSplitRatio}
                />
            )}

            {rightVisible && (
                <div
                    className={[
                        styles.rightPane,
                        fullscreenActive ? styles.paneChromeHidden : '',
                    ].filter(Boolean).join(' ')}
                    aria-hidden={fullscreenActive}
                >
                    <DesktopPane
                        paneId={DESKTOP_PANE_IDS.RIGHT}
                        pane={rightPane}
                        split={split}
                        onSelectSurface={onSelectSurface}
                        onCloseSurface={onCloseSurface}
                        getSurfaceActions={getSurfaceActions}
                        fullscreenSurfaceId={model.fullscreenSurfaceId}
                    />
                </div>
            )}

            {model.surfaces.map((surface) => {
                const paneId = paneContainingSurface(model.panes, surface.id);
                const activeInPane = Boolean(
                    paneId && model.panes[paneId].activeSurfaceId === surface.id,
                );
                const floatingWindow = model.floatingWindowsBySurfaceId?.[
                    surface.id
                ] || null;
                const fullscreen = model.fullscreenSurfaceId === surface.id;
                return (
                    <DesktopSurfaceHost
                        key={surface.id}
                        surface={surface}
                        paneId={paneId}
                        activeInPane={activeInPane}
                        floatingWindow={floatingWindow}
                        focusedFloating={
                            model.focusedFloatingSurfaceId === surface.id
                        }
                        fullscreen={fullscreen}
                        commands={commands}
                        onFocusSurface={onFocusSurface}
                        getSurfaceActions={getSurfaceActions}
                        renderSurface={renderSurface}
                    />
                );
            })}
        </div>
    );
}
