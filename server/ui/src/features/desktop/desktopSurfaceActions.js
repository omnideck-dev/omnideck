import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';

const TAB = 'tab';
const FULLSCREEN = 'fullscreen';
const MENU = 'menu';

function action({
    id,
    label,
    ariaLabel = label,
    icon,
    execute,
    placements = [TAB, FULLSCREEN, MENU],
    testid,
    disabled = false,
    separatorBefore = false,
}) {
    return {
        id,
        label,
        ariaLabel,
        icon,
        execute,
        placements,
        testid,
        disabled,
        separatorBefore,
    };
}

/**
 * One command model shared by tab chrome, full-screen chrome, and tab menus.
 *
 * Placement operations are generic. Feature owners contribute only the
 * commands their surface kind supports.
 */
export function createDesktopSurfaceActions({
    surface,
    paneId,
    pane,
    commands,
}) {
    const surfaceKey = surface.testid || surface.id;
    const targetPaneId = paneId === DESKTOP_PANE_IDS.LEFT
        ? DESKTOP_PANE_IDS.RIGHT
        : DESKTOP_PANE_IDS.LEFT;
    const surfaceIndex = pane.surfaceIds.indexOf(surface.id);
    const otherClosable = pane.surfaces.some(
        (candidate) => (
            candidate.id !== surface.id
            && candidate.closable !== false
        ),
    );
    const closableToRight = pane.surfaces
        .slice(surfaceIndex + 1)
        .some((candidate) => candidate.closable !== false);

    const actions = [
        action({
            id: 'move',
            label: `Move to ${targetPaneId} pane`,
            ariaLabel: `Move ${surface.label} to ${targetPaneId} pane`,
            icon: targetPaneId === DESKTOP_PANE_IDS.LEFT
                ? 'bi-box-arrow-left'
                : 'bi-box-arrow-right',
            execute: () => commands.moveSurface(surface.id, targetPaneId),
            testid: `move-surface-${surfaceKey}-${targetPaneId}`,
        }),
        action({
            id: 'fullscreen',
            label: 'Enter full screen',
            ariaLabel: `Show ${surface.label} full screen`,
            icon: 'bi-arrows-fullscreen',
            execute: () => commands.enterFullscreen(surface.id),
            placements: [TAB, MENU],
            testid: `maximize-surface-${surfaceKey}`,
        }),
    ];

    if (surface.kind === 'custom-app') {
        actions.push(action({
            id: 'reload',
            label: 'Reload',
            ariaLabel: `Reload ${surface.label}`,
            icon: 'bi-arrow-clockwise',
            execute: () => commands.reloadCustomApp(surface.id),
            testid: `reload-surface-${surfaceKey}`,
        }));
    }

    if (
        surface.kind === 'artifact-file'
        && surface.artifact?.id
        && surface.artifact?.conversation_id
    ) {
        actions.push(action({
            id: 'open-source-conversation',
            label: 'Open source conversation',
            icon: 'bi-chat-left-text',
            execute: () => commands.openArtifactConversation(surface.artifact),
            testid: 'artifact-open-conversation',
        }));
    }

    if (surface.closable !== false) {
        actions.push(action({
            id: 'close',
            label: 'Close tab',
            icon: 'bi-x-lg',
            execute: () => commands.closeSurface(paneId, surface.id),
            placements: [MENU],
            separatorBefore: true,
        }));
    }
    actions.push(
        action({
            id: 'close-others',
            label: 'Close other tabs',
            icon: 'bi-x-square',
            execute: () => commands.closeOtherSurfaces(paneId, surface.id),
            placements: [MENU],
            disabled: !otherClosable,
        }),
        action({
            id: 'close-right',
            label: 'Close tabs to the right',
            icon: 'bi-arrow-bar-right',
            execute: () => commands.closeSurfacesToRight(paneId, surface.id),
            placements: [MENU],
            disabled: !closableToRight,
        }),
    );

    return actions;
}

export const DESKTOP_ACTION_PLACEMENTS = {
    TAB,
    FULLSCREEN,
    MENU,
};
