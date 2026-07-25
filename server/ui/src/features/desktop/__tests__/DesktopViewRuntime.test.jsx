import { memo } from 'react';
import { act, render, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
    DesktopViewRuntimeProvider,
    useDesktopViewCatalog,
    useDesktopViewCommands,
} from '../DesktopViewRuntime.jsx';

const CONVERSATION = {
    id: 'destination:conversation',
    type: 'conversation',
};
const ARTIFACT = {
    id: 'artifact:report',
    type: 'artifact-file',
};

function model({ conversationTabGroupId = 'left' } = {}) {
    return {
        openViews: [CONVERSATION],
        openViewsById: {
            [CONVERSATION.id]: CONVERSATION,
        },
        tabGroups: {
            left: {
                viewIds: conversationTabGroupId === 'left'
                    ? [CONVERSATION.id]
                    : [],
                activeViewId: conversationTabGroupId === 'left'
                    ? CONVERSATION.id
                    : null,
            },
            right: {
                viewIds: conversationTabGroupId === 'right'
                    ? [CONVERSATION.id]
                    : [],
                activeViewId: conversationTabGroupId === 'right'
                    ? CONVERSATION.id
                    : null,
            },
        },
    };
}

function commandSpies() {
    return {
        openView: vi.fn(),
        updateViews: vi.fn(),
        syncViews: vi.fn(),
        closeView: vi.fn(),
        closeViews: vi.fn(),
    };
}

describe('DesktopViewRuntime', () => {
    it('translates the narrow placement object to the layout command shape', () => {
        const layoutCommands = commandSpies();
        const wrapper = ({ children }) => (
            <DesktopViewRuntimeProvider
                desktopLayout={{
                    model: model(),
                    commands: layoutCommands,
                }}
            >
                {children}
            </DesktopViewRuntimeProvider>
        );
        const { result } = renderHook(useDesktopViewCommands, { wrapper });

        act(() => result.current.openView(ARTIFACT, {
            tabGroupId: 'right',
            activate: false,
        }));

        expect(layoutCommands.openView).toHaveBeenCalledWith(
            ARTIFACT,
            'right',
            { activate: false },
        );
    });

    it('keeps companion placement policy in the Desktop boundary', () => {
        const layoutCommands = commandSpies();
        const wrapper = ({ children }) => (
            <DesktopViewRuntimeProvider
                desktopLayout={{
                    model: model({ conversationTabGroupId: 'left' }),
                    commands: layoutCommands,
                }}
            >
                {children}
            </DesktopViewRuntimeProvider>
        );
        const { result } = renderHook(useDesktopViewCommands, { wrapper });

        expect(result.current.preferredTabGroupId()).toBe('right');
    });

    it('does not wake domain catalog consumers for bounds-only changes', () => {
        const layoutCommands = commandSpies();
        const baseModel = model();
        let renders = 0;
        const CatalogConsumer = memo(function CatalogConsumer() {
            useDesktopViewCatalog();
            renders += 1;
            return null;
        });
        const { rerender } = render(
            <DesktopViewRuntimeProvider
                desktopLayout={{
                    model: baseModel,
                    commands: layoutCommands,
                }}
            >
                <CatalogConsumer />
            </DesktopViewRuntimeProvider>,
        );

        rerender(
            <DesktopViewRuntimeProvider
                desktopLayout={{
                    model: {
                        ...baseModel,
                        floatingByViewId: {
                            sample: { x: 100, y: 80 },
                        },
                    },
                    commands: layoutCommands,
                }}
            >
                <CatalogConsumer />
            </DesktopViewRuntimeProvider>,
        );

        expect(renders).toBe(1);
    });
});
