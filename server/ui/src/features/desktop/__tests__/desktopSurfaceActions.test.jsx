import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import DesktopSurfaceActionBar from '../DesktopSurfaceActionBar.jsx';
import {
    createDesktopSurfaceActions,
    DESKTOP_ACTION_PLACEMENTS,
} from '../desktopSurfaceActions.js';
import { DESKTOP_PANE_IDS } from '../desktopWindowReducer.js';

const CUSTOM_APP = {
    id: 'custom-app:text-lab',
    kind: 'custom-app',
    label: 'Text Lab',
    closable: true,
};
const CHAT = {
    id: 'destination:conversation',
    kind: 'conversation',
    label: 'Chat',
    closable: true,
};

function commands() {
    return {
        moveSurface: vi.fn(),
        enterFullscreen: vi.fn(),
        reloadCustomApp: vi.fn(),
        openArtifactConversation: vi.fn(),
        closeSurface: vi.fn(),
        closeOtherSurfaces: vi.fn(),
        closeSurfacesToRight: vi.fn(),
    };
}

function actions(surface = CUSTOM_APP, commandSet = commands()) {
    return {
        commandSet,
        items: createDesktopSurfaceActions({
            surface,
            paneId: DESKTOP_PANE_IDS.RIGHT,
            pane: {
                surfaceIds: [CHAT.id, CUSTOM_APP.id],
                surfaces: [CHAT, CUSTOM_APP],
            },
            commands: commandSet,
        }),
    };
}

describe('desktop surface actions', () => {
    it('uses the same model for placement and feature toolbar commands', () => {
        const { commandSet, items } = actions();
        render(
            <DesktopSurfaceActionBar
                actions={items}
                placement={DESKTOP_ACTION_PLACEMENTS.TAB}
            />,
        );

        fireEvent.click(screen.getByTestId(
            'move-surface-custom-app:text-lab-left',
        ));
        fireEvent.click(screen.getByTestId(
            'reload-surface-custom-app:text-lab',
        ));
        fireEvent.click(screen.getByTestId(
            'maximize-surface-custom-app:text-lab',
        ));

        expect(commandSet.moveSurface).toHaveBeenCalledWith(
            CUSTOM_APP.id,
            DESKTOP_PANE_IDS.LEFT,
        );
        expect(commandSet.reloadCustomApp).toHaveBeenCalledWith(CUSTOM_APP.id);
        expect(commandSet.enterFullscreen).toHaveBeenCalledWith(CUSTOM_APP.id);
    });

    it('keeps enter-fullscreen out of fullscreen chrome', () => {
        const { items } = actions();
        render(
            <DesktopSurfaceActionBar
                actions={items}
                placement={DESKTOP_ACTION_PLACEMENTS.FULLSCREEN}
            />,
        );

        expect(screen.queryByTestId(
            'maximize-surface-custom-app:text-lab',
        )).not.toBeInTheDocument();
        expect(screen.getByTestId(
            'reload-surface-custom-app:text-lab',
        )).toBeInTheDocument();
    });

    it('provides bulk close commands with contextual enablement', () => {
        const { commandSet, items } = actions(CHAT);
        const closeOthers = items.find((item) => item.id === 'close-others');
        const closeRight = items.find((item) => item.id === 'close-right');

        expect(closeOthers.disabled).toBe(false);
        expect(closeRight.disabled).toBe(false);
        closeOthers.execute();
        closeRight.execute();
        expect(commandSet.closeOtherSurfaces).toHaveBeenCalledWith(
            DESKTOP_PANE_IDS.RIGHT,
            CHAT.id,
        );
        expect(commandSet.closeSurfacesToRight).toHaveBeenCalledWith(
            DESKTOP_PANE_IDS.RIGHT,
            CHAT.id,
        );
    });

    it('contributes source-conversation navigation for artifact surfaces', () => {
        const artifact = {
            id: 'artifact-1',
            filename: 'notes.md',
            conversation_id: 'conversation-1',
        };
        const commandSet = commands();
        const { items } = actions({
            id: 'artifact:artifact-1',
            kind: 'artifact-file',
            label: 'notes.md',
            artifact,
            closable: true,
        }, commandSet);
        const openSource = items.find(
            (item) => item.id === 'open-source-conversation',
        );

        openSource.execute();
        expect(commandSet.openArtifactConversation).toHaveBeenCalledWith(artifact);
    });
});
