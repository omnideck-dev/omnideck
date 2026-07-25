import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';

const FULLSCREEN = 'fullscreen';
const FLOATING = 'floating';
const MENU = 'menu';

function action({
    id,
    label,
    ariaLabel = label,
    icon,
    execute,
    placements = [FULLSCREEN, FLOATING, MENU],
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
 * Placement operations are generic. Domain owners contribute only the
 * commands their View type supports.
 */
export function createDesktopViewActions({
    view,
    tabGroupId,
    tabGroup,
    floating = false,
    commands,
}) {
    const viewKey = view.testid || view.id;
    const targetTabGroupId = tabGroupId === DESKTOP_TAB_GROUP_IDS.LEFT
        ? DESKTOP_TAB_GROUP_IDS.RIGHT
        : DESKTOP_TAB_GROUP_IDS.LEFT;
    const viewIndex = tabGroup?.viewIds.indexOf(view.id) ?? -1;
    const otherClosable = tabGroup?.views.some(
        (candidate) => (
            candidate.id !== view.id
            && candidate.closable !== false
        ),
    ) || false;
    const closableToRight = (tabGroup?.views || [])
        .slice(viewIndex + 1)
        .some((candidate) => candidate.closable !== false);

    const actions = [];
    if (floating) {
        actions.push(
            action({
                id: 'dock-left',
                label: 'Dock in left tab group',
                ariaLabel: `Dock ${view.label} in left tab group`,
                icon: 'bi-box-arrow-left',
                execute: () => commands.moveView(
                    view.id,
                    DESKTOP_TAB_GROUP_IDS.LEFT,
                ),
                placements: [FLOATING],
                testid: `dock-view-${viewKey}-left`,
            }),
            action({
                id: 'dock-right',
                label: 'Dock in right tab group',
                ariaLabel: `Dock ${view.label} in right tab group`,
                icon: 'bi-box-arrow-right',
                execute: () => commands.moveView(
                    view.id,
                    DESKTOP_TAB_GROUP_IDS.RIGHT,
                ),
                placements: [FLOATING],
                testid: `dock-view-${viewKey}-right`,
            }),
        );
    } else {
        actions.push(action({
            id: 'move',
            label: `Move to ${targetTabGroupId} tab group`,
            ariaLabel: `Move ${view.label} to ${targetTabGroupId} tab group`,
            icon: targetTabGroupId === DESKTOP_TAB_GROUP_IDS.LEFT
                ? 'bi-box-arrow-left'
                : 'bi-box-arrow-right',
            execute: () => commands.moveView(view.id, targetTabGroupId),
            testid: `move-view-${viewKey}-${targetTabGroupId}`,
        }));
        actions.push(action({
            id: 'float',
            label: 'Open as floating view',
            ariaLabel: `Open ${view.label} as a floating view`,
            icon: 'bi-window-stack',
            execute: () => commands.floatView(view.id),
            placements: [MENU],
            testid: `float-view-${viewKey}`,
        }));
    }
    actions.push(
        action({
            id: 'fullscreen',
            label: 'Enter full screen',
            ariaLabel: `Show ${view.label} full screen`,
            icon: 'bi-arrows-fullscreen',
            execute: () => commands.enterFullscreen(view.id),
            placements: floating ? [FLOATING] : [MENU],
            testid: `maximize-view-${viewKey}`,
        }),
    );

    if (view.actions?.includes('reload')) {
        actions.push(action({
            id: 'reload',
            label: 'Reload',
            ariaLabel: `Reload ${view.label}`,
            icon: 'bi-arrow-clockwise',
            execute: () => commands.requestViewAction('reload', view),
            testid: `reload-view-${viewKey}`,
        }));
    }

    if (view.actions?.includes('open-source-conversation')) {
        actions.push(action({
            id: 'open-source-conversation',
            label: 'Open source conversation',
            icon: 'bi-chat-left-text',
            execute: () => commands.requestViewAction(
                'open-source-conversation',
                view,
            ),
            testid: 'artifact-open-conversation',
        }));
    }

    if (view.closable !== false) {
        actions.push(action({
            id: 'close',
            label: floating ? 'Close floating view' : 'Close tab',
            icon: 'bi-x-lg',
            execute: () => commands.closeView(tabGroupId, view.id),
            placements: floating ? [FLOATING] : [MENU],
            testid: floating
                ? `close-floating-view-${viewKey}`
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
            execute: () => commands.closeOtherViews(tabGroupId, view.id),
            placements: [MENU],
            disabled: !otherClosable,
        }),
        action({
            id: 'close-right',
            label: 'Close tabs to the right',
            icon: 'bi-arrow-bar-right',
            execute: () => commands.closeViewsToRight(tabGroupId, view.id),
            placements: [MENU],
            disabled: !closableToRight,
        }),
    );

    return actions;
}

export const DESKTOP_ACTION_PLACEMENTS = {
    FULLSCREEN,
    FLOATING,
    MENU,
};
