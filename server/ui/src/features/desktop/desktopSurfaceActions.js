import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';

const TAB = 'tab';
const FULLSCREEN = 'fullscreen';
const FLOATING = 'floating';
const MENU = 'menu';

function action({
    id,
    label,
    ariaLabel = label,
    icon,
    execute,
    placements = [TAB, FULLSCREEN, FLOATING, MENU],
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
 * One command model shared by tab, floating, full-screen, and menu chrome.
 *
 * Placement operations are generic. Feature owners contribute only the
 * commands their surface kind supports.
 */
export function createDesktopSurfaceActions({
    surface,
    paneId,
    pane,
    floating = false,
    commands,
}) {
    const surfaceKey = surface.testid || surface.id;
    const targetPaneId = paneId === DESKTOP_PANE_IDS.LEFT
        ? DESKTOP_PANE_IDS.RIGHT
        : DESKTOP_PANE_IDS.LEFT;
    const surfaceIndex = pane?.surfaceIds.indexOf(surface.id) ?? -1;
    const otherClosable = pane?.surfaces.some(
        (candidate) => (
            candidate.id !== surface.id
            && candidate.closable !== false
        ),
    ) || false;
    const closableToRight = (pane?.surfaces || [])
        .slice(surfaceIndex + 1)
        .some((candidate) => candidate.closable !== false);

    const actions = [];
    if (floating) {
        actions.push(
            action({
                id: 'dock-left',
                label: 'Dock in left pane',
                ariaLabel: `Dock ${surface.label} in left pane`,
                icon: 'bi-box-arrow-left',
                execute: () => commands.moveSurface(
                    surface.id,
                    DESKTOP_PANE_IDS.LEFT,
                ),
                placements: [FLOATING],
                testid: `dock-surface-${surfaceKey}-left`,
            }),
            action({
                id: 'dock-right',
                label: 'Dock in right pane',
                ariaLabel: `Dock ${surface.label} in right pane`,
                icon: 'bi-box-arrow-right',
                execute: () => commands.moveSurface(
                    surface.id,
                    DESKTOP_PANE_IDS.RIGHT,
                ),
                placements: [FLOATING],
                testid: `dock-surface-${surfaceKey}-right`,
            }),
        );
    } else {
        actions.push(action({
            id: 'move',
            label: `Move to ${targetPaneId} pane`,
            ariaLabel: `Move ${surface.label} to ${targetPaneId} pane`,
            icon: targetPaneId === DESKTOP_PANE_IDS.LEFT
                ? 'bi-box-arrow-left'
                : 'bi-box-arrow-right',
            execute: () => commands.moveSurface(surface.id, targetPaneId),
            testid: `move-surface-${surfaceKey}-${targetPaneId}`,
        }));
        actions.push(action({
            id: 'float',
            label: 'Open as floating window',
            ariaLabel: `Open ${surface.label} as a floating window`,
            icon: 'bi-window-stack',
            execute: () => commands.floatSurface(surface.id),
            placements: [TAB, MENU],
            testid: `float-surface-${surfaceKey}`,
        }));
    }
    actions.push(
        action({
            id: 'fullscreen',
            label: 'Enter full screen',
            ariaLabel: `Show ${surface.label} full screen`,
            icon: 'bi-arrows-fullscreen',
            execute: () => commands.enterFullscreen(surface.id),
            placements: floating ? [FLOATING] : [TAB, MENU],
            testid: `maximize-surface-${surfaceKey}`,
        }),
    );

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
            label: floating ? 'Close window' : 'Close tab',
            icon: 'bi-x-lg',
            execute: () => commands.closeSurface(paneId, surface.id),
            placements: floating ? [FLOATING] : [MENU],
            testid: floating
                ? `close-floating-surface-${surfaceKey}`
                : undefined,
            separatorBefore: true,
        }));
    }
    if (floating) return actions;

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
    FLOATING,
    MENU,
};
