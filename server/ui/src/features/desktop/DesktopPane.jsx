import TabbedPane from '../../components/TabbedPane.jsx';
import DesktopSurfaceActionBar from './DesktopSurfaceActionBar.jsx';
import { DESKTOP_ACTION_PLACEMENTS } from './desktopSurfaceActions.js';
import styles from './DesktopPane.module.css';

function surfaceTab(surface, actions) {
    return {
        id: surface.id,
        testid: surface.testid || surface.id,
        label: surface.label,
        icon: surface.iconElement || <i className={`bi ${surface.icon || 'bi-window'}`} />,
        actions: actions.length > 0
            ? (
                <DesktopSurfaceActionBar
                    actions={actions}
                    placement={DESKTOP_ACTION_PLACEMENTS.TAB}
                />
            )
            : null,
        menuActions: actions.filter(
            (action) => action.placements.includes(DESKTOP_ACTION_PLACEMENTS.MENU),
        ),
        closable: surface.closable,
    };
}

/** Tab chrome for one desktop pane; left and right use this same component. */
export default function DesktopPane({
    paneId,
    pane,
    split,
    onSelectSurface,
    onCloseSurface,
    getSurfaceActions,
    fullscreenSurfaceId = null,
}) {
    const tabs = pane.surfaces.map((surface) => surfaceTab(
        surface,
        surface.id === fullscreenSurfaceId
            ? []
            : getSurfaceActions?.(surface, paneId) || [],
    ));

    return (
        <section
            className={styles.pane}
            data-testid={`desktop-pane-${paneId}`}
            data-pane-id={paneId}
            data-layout={split ? 'split' : 'single'}
        >
            <TabbedPane
                tabs={tabs}
                activeTab={pane.activeSurfaceId}
                onTabChange={(surfaceId) => onSelectSurface(paneId, surfaceId)}
                onCloseTab={(surfaceId) => onCloseSurface(paneId, surfaceId)}
                testIds={{
                    panel: `desktop-pane-${paneId}-tabs`,
                    tabBar: `desktop-pane-${paneId}-tab-bar`,
                    content: `desktop-pane-${paneId}-content-slot`,
                }}
            />
        </section>
    );
}
