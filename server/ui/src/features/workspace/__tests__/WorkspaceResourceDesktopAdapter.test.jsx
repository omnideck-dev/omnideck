import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    focusedViewId: null,
    sessionState: {
        activeConversationId: 'conversation-1',
        isStreaming: false,
    },
    useActiveWorkspaceResource: vi.fn(() => ({
        browser: { agentId: null },
    })),
    renderedView: vi.fn(() => null),
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: vi.fn(),
    useConversationSessionState: () => mocks.sessionState,
}));

vi.mock('../../app/AppEffects.jsx', () => ({
    useAppEffectDispatch: vi.fn(),
}));

vi.mock('../../desktop/DesktopViewRuntime.jsx', () => ({
    useDesktopViewCommands: vi.fn(),
    useDesktopViewCatalog: vi.fn(),
    useFocusedViewId: () => mocks.focusedViewId,
}));

vi.mock('../useActiveWorkspaceResource.js', () => ({
    default: mocks.useActiveWorkspaceResource,
}));

vi.mock('../useWorkspaceResourceDesktopViews.js', () => ({
    default: vi.fn(),
}));

vi.mock('../WorkspaceResourceView.jsx', () => ({
    default: mocks.renderedView,
}));

const { default: WorkspaceResourceDesktopView } = await import(
    '../WorkspaceResourceDesktopAdapter.jsx'
);

function browserView({ isRoot }) {
    return {
        id: isRoot
            ? 'workspace-resource:conversation-1:root:browser'
            : 'workspace-resource:conversation-1:child-1:browser',
        type: 'workspace-resource',
        agentId: isRoot ? 'root-1' : 'child-1',
        resourceId: 'browser',
        isRoot,
    };
}

describe('WorkspaceResourceDesktopView', () => {
    beforeEach(() => {
        mocks.focusedViewId = null;
        mocks.useActiveWorkspaceResource.mockClear();
        mocks.renderedView.mockClear();
    });

    it('gives the focused root Browser the one control session', () => {
        const view = browserView({ isRoot: true });
        mocks.focusedViewId = view.id;

        render(<WorkspaceResourceDesktopView view={view} active={false} />);

        expect(mocks.useActiveWorkspaceResource).toHaveBeenCalledWith({
            conversationId: 'conversation-1',
            isStreaming: false,
            activeView: view,
        });
        // Rendering activity is independent from exclusive session ownership.
        expect(mocks.renderedView).toHaveBeenCalledWith(
            expect.objectContaining({ active: false }),
            expect.anything(),
        );
    });

    it('keeps a focused sub-agent Browser read-only while still rendering it', () => {
        const view = browserView({ isRoot: false });
        mocks.focusedViewId = view.id;

        render(<WorkspaceResourceDesktopView view={view} active />);

        expect(mocks.useActiveWorkspaceResource).toHaveBeenCalledWith({
            conversationId: 'conversation-1',
            isStreaming: false,
            activeView: null,
        });
        expect(mocks.renderedView).toHaveBeenCalledWith(
            expect.objectContaining({ active: true }),
            expect.anything(),
        );
    });
});
