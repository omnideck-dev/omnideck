import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DesktopViewActionBar from '../DesktopViewActionBar.jsx';
import {
    createDesktopViewActions,
    DESKTOP_ACTION_PLACEMENTS,
} from '../desktopViewActions.js';
import { DESKTOP_TAB_GROUP_IDS } from '../desktopLayoutReducer.js';

const CUSTOM_APP = {
    id: 'custom-app:text-lab',
    type: 'custom-app',
    label: 'Text Lab',
    actions: ['reload'],
    closable: true,
};
const CHAT = {
    id: 'destination:conversation',
    type: 'conversation',
    label: 'Chat',
    closable: true,
};

function commands() {
    return {
        moveView: vi.fn(),
        floatView: vi.fn(),
        enterFullscreen: vi.fn(),
        requestViewAction: vi.fn(),
        closeView: vi.fn(),
        closeOtherViews: vi.fn(),
        closeViewsToRight: vi.fn(),
    };
}

function actions(view = CUSTOM_APP, commandSet = commands()) {
    return {
        commandSet,
        items: createDesktopViewActions({
            view,
            tabGroupId: DESKTOP_TAB_GROUP_IDS.RIGHT,
            tabGroup: {
                viewIds: [CHAT.id, CUSTOM_APP.id],
                views: [CHAT, CUSTOM_APP],
            },
            commands: commandSet,
        }),
    };
}

describe('desktop view actions', () => {
    it('uses the same menu model for placement and feature commands', () => {
        const { commandSet, items } = actions();
        const menuItems = items.filter(
            (item) => item.placements.includes(
                DESKTOP_ACTION_PLACEMENTS.MENU,
            ),
        );

        menuItems.find((item) => item.id === 'move').execute();
        menuItems.find((item) => item.id === 'reload').execute();
        menuItems.find((item) => item.id === 'fullscreen').execute();

        expect(commandSet.moveView).toHaveBeenCalledWith(
            CUSTOM_APP.id,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        );
        expect(commandSet.requestViewAction).toHaveBeenCalledWith(
            'reload',
            CUSTOM_APP,
        );
        expect(commandSet.enterFullscreen).toHaveBeenCalledWith(CUSTOM_APP.id);
    });

    it('keeps enter-fullscreen out of fullscreen chrome', () => {
        const { items } = actions();
        render(
            <DesktopViewActionBar
                actions={items}
                placement={DESKTOP_ACTION_PLACEMENTS.FULLSCREEN}
            />,
        );

        expect(screen.queryByTestId(
            'maximize-view-custom-app:text-lab',
        )).not.toBeInTheDocument();
        expect(screen.getByTestId(
            'reload-view-custom-app:text-lab',
        )).toBeInTheDocument();
    });

    it('offers floating placement from a tab and dock commands from window chrome', () => {
        const { commandSet, items } = actions();
        items.find((item) => item.id === 'float').execute();
        expect(commandSet.floatView).toHaveBeenCalledWith(CUSTOM_APP.id);

        const floatingItems = createDesktopViewActions({
            view: CUSTOM_APP,
            tabGroupId: null,
            tabGroup: null,
            floating: true,
            commands: commandSet,
        });
        render(
            <DesktopViewActionBar
                actions={floatingItems}
                placement={DESKTOP_ACTION_PLACEMENTS.FLOATING}
            />,
        );

        fireEvent.click(screen.getByTestId(
            'dock-view-custom-app:text-lab-left',
        ));
        fireEvent.click(screen.getByTestId(
            'dock-view-custom-app:text-lab-right',
        ));
        expect(commandSet.moveView).toHaveBeenCalledWith(
            CUSTOM_APP.id,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        );
        expect(commandSet.moveView).toHaveBeenCalledWith(
            CUSTOM_APP.id,
            DESKTOP_TAB_GROUP_IDS.RIGHT,
        );
    });

    it('provides bulk close commands with contextual enablement', () => {
        const { commandSet, items } = actions(CHAT);
        const closeOthers = items.find((item) => item.id === 'close-others');
        const closeRight = items.find((item) => item.id === 'close-right');

        expect(closeOthers.disabled).toBe(false);
        expect(closeRight.disabled).toBe(false);
        closeOthers.execute();
        closeRight.execute();
        expect(commandSet.closeOtherViews).toHaveBeenCalledWith(
            DESKTOP_TAB_GROUP_IDS.RIGHT,
            CHAT.id,
        );
        expect(commandSet.closeViewsToRight).toHaveBeenCalledWith(
            DESKTOP_TAB_GROUP_IDS.RIGHT,
            CHAT.id,
        );
    });

    it('contributes source-conversation navigation for artifact views', () => {
        const artifact = {
            id: 'artifact-1',
            filename: 'notes.md',
            conversation_id: 'conversation-1',
        };
        const commandSet = commands();
        const { items } = actions({
            id: 'artifact:artifact-1',
            type: 'artifact-file',
            label: 'notes.md',
            artifact,
            actions: ['open-source-conversation'],
            closable: true,
        }, commandSet);
        const openSource = items.find(
            (item) => item.id === 'open-source-conversation',
        );

        openSource.execute();
        expect(commandSet.requestViewAction).toHaveBeenCalledWith(
            'open-source-conversation',
            expect.objectContaining({ artifact }),
        );
    });
});
