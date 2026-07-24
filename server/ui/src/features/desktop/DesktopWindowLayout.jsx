import { useEffect } from 'react';

import SplitHandle from '../../components/SplitHandle.jsx';
import DesktopPane from './DesktopPane.jsx';
import DesktopSurfaceActionBar from './DesktopSurfaceActionBar.jsx';
import { DESKTOP_ACTION_PLACEMENTS } from './desktopSurfaceActions.js';
import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';
import styles from './DesktopWindowLayout.module.css';

function paneContainingSurface(panes, surfaceId) {
    return Object.entries(panes).find(([, pane]) => (
        pane.surfaceIds.includes(surfaceId)
    ))?.[0] || null;
}

/**
 * Renders two equivalent tab stacks over one stable surface layer.
 *
 * Every registered surface has one keyed host. Moving it changes its grid
 * column instead of its React parent, preserving iframe and component state.
 */
export default function DesktopWindowLayout({
    model,
    commands,
    onSelectSurface,
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
                const active = Boolean(
                    paneId && model.panes[paneId].activeSurfaceId === surface.id,
                );
                const fullscreen = model.fullscreenSurfaceId === surface.id;
                return (
                    <div
                        key={surface.id}
                        className={[
                            styles.surfaceHost,
                            paneId === DESKTOP_PANE_IDS.LEFT ? styles.leftSurface : '',
                            paneId === DESKTOP_PANE_IDS.RIGHT ? styles.rightSurface : '',
                            active ? styles.activeSurface : styles.hiddenSurface,
                            fullscreen ? styles.fullscreenSurface : '',
                        ].filter(Boolean).join(' ')}
                        data-testid={`desktop-surface-${surface.testid || surface.id}`}
                        data-surface-id={surface.id}
                        data-surface-kind={surface.kind}
                        data-surface-owner-id={surface.agentId || surface.resourceId || ''}
                        data-surface-resource-id={surface.resourceId || ''}
                        data-pane-id={paneId || 'hidden'}
                        data-active={active ? 'true' : 'false'}
                        data-fullscreen={fullscreen ? 'true' : 'false'}
                        data-maximized={fullscreen ? 'true' : 'false'}
                    >
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
                                        <span className={styles.fullscreenIcon}>
                                            {surface.iconElement || (
                                                <i className={`bi ${surface.icon || 'bi-window'}`} />
                                            )}
                                        </span>
                                        <span
                                            className={styles.fullscreenTitle}
                                            title={surface.label}
                                        >
                                            {surface.label}
                                        </span>
                                    </div>
                                    <div className={styles.fullscreenActions}>
                                        <DesktopSurfaceActionBar
                                            actions={getSurfaceActions?.(
                                                surface,
                                                paneId,
                                            ) || []}
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
                        {renderSurface(surface, { active, paneId })}
                    </div>
                );
            })}
        </div>
    );
}
