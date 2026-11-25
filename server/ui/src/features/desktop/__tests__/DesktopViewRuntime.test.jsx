import { memo } from 'react';
import { act, render, renderHook } from '@testing-library/react';
import {
    afterEach, describe, expect, it, vi,
} from 'vitest';


const {
    DesktopViewRuntimeProvider,
    useDesktopViewCatalog,
    useDesktopViewCommands,
    useFocusedViewId,
    useVisibleViewIds,
} = await import('../DesktopViewRuntime.jsx');

const CONVERSATION = {
    id: 'destination:conversation',
    type: 'conversation',
};
const ARTIFACT = {
    id: 'artifact:report',
    type: 'artifact-file',
};

function model({
    conversationTabGroupId = 'left',
    focusedFloatingViewId = null,
    focusedTabGroupId = conversationTabGroupId,
} = {}) {
    return {
        floatingByViewId: {},
        fullscreenViewId: null,
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
        focusedFloatingViewId,
        focusedTabGroupId,
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

    it('prefers floating focus and falls back to the focused tab group', () => {
        const layoutCommands = commandSpies();
        let currentModel = model();
        const wrapper = ({ children }) => (
            <DesktopViewRuntimeProvider
                desktopLayout={{
                    model: currentModel,
                    commands: layoutCommands,
                }}
            >
                {children}
            </DesktopViewRuntimeProvider>
        );
        const { result, rerender } = renderHook(useFocusedViewId, { wrapper });

        expect(result.current).toBe(CONVERSATION.id);

        currentModel = model({ focusedFloatingViewId: ARTIFACT.id });
        rerender();

        expect(result.current).toBe(ARTIFACT.id);
    });

    it('does not wake catalog consumers when only focus or bounds change', () => {
        const layoutCommands = commandSpies();
        const baseModel = model();
        let catalogRenders = 0;
        let focusRenders = 0;
        const CatalogConsumer = memo(function CatalogConsumer() {
            useDesktopViewCatalog();
            catalogRenders += 1;
            return null;
        });
        const FocusConsumer = memo(function FocusConsumer() {
            useFocusedViewId();
            focusRenders += 1;
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
                <FocusConsumer />
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
                        focusedFloatingViewId: ARTIFACT.id,
                    },
                    commands: layoutCommands,
                }}
            >
                <CatalogConsumer />
                <FocusConsumer />
            </DesktopViewRuntimeProvider>,
        );

        expect(catalogRenders).toBe(1);
        expect(focusRenders).toBe(2);
    });
    it('exposes both panes and honors floating and fullscreen views', () => {
        const base = model();
        let currentModel = {
            ...base,
            openViewsById: { ...base.openViewsById, [ARTIFACT.id]: ARTIFACT },
            tabGroups: {
                ...base.tabGroups,
                right: { viewIds: [ARTIFACT.id], activeViewId: ARTIFACT.id },
            },
        };
        const wrapper = ({ children }) => (
            <DesktopViewRuntimeProvider desktopLayout={{ model: currentModel, commands: commandSpies() }}>
                {children}
            </DesktopViewRuntimeProvider>
        );
        const { result, rerender } = renderHook(useVisibleViewIds, { wrapper });
        expect(result.current).toEqual([CONVERSATION.id, ARTIFACT.id]);
        currentModel = {
            ...currentModel,
            floatingByViewId: { [ARTIFACT.id]: { viewId: ARTIFACT.id } },
        };
        rerender();
        expect(result.current).toEqual([CONVERSATION.id, ARTIFACT.id]);
        currentModel = { ...currentModel, fullscreenViewId: ARTIFACT.id };
        rerender();
        expect(result.current).toEqual([ARTIFACT.id]);
        currentModel = { ...currentModel, fullscreenViewId: null };
        rerender();
        expect(result.current).toEqual([CONVERSATION.id, ARTIFACT.id]);
    });

});
