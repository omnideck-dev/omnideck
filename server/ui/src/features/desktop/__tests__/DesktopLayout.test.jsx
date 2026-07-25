import {
    fireEvent,
    render,
    screen,
    within,
} from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { createDesktopViewActions } from '../desktopViewActions.js';
import { DESKTOP_TAB_GROUP_IDS } from '../desktopLayoutReducer.js';

vi.mock('../../../components/SplitHandle.jsx', () => ({
    default: ({ onDrag, className }) => (
        <button
            type="button"
            className={className}
            data-testid="split-handle"
            onClick={() => onDrag(65)}
        >
            Resize
        </button>
    ),
}));

const { default: DesktopLayout } = await import('../DesktopLayout.jsx');

const CHAT = { id: 'destination:conversation', label: 'Chat', type: 'conversation' };
const APP = { id: 'custom-app:text-lab', label: 'Text Lab', type: 'custom-app' };

function model({
    leftIds = [CHAT.id],
    rightIds = [APP.id],
    leftActive = CHAT.id,
    rightActive = APP.id,
    floatingView = null,
} = {}) {
    const openViewsById = { [CHAT.id]: CHAT, [APP.id]: APP };
    const tabGroup = (viewIds, activeViewId) => ({
        viewIds,
        activeViewId,
        views: viewIds.map((id) => openViewsById[id]),
    });
    return {
        tabGroups: {
            left: tabGroup(leftIds, leftActive),
            right: tabGroup(rightIds, rightActive),
        },
        openViews: [CHAT, APP],
        openViewsById,
        floatingByViewId: floatingView
            ? { [floatingView.viewId]: floatingView }
            : {},
        focusedFloatingViewId: floatingView?.viewId || null,
        splitRatio: 40,
        fullscreenViewId: null,
    };
}

it('renders both sides with the same tabGroup component and connects split resizing', () => {
    const setSplitRatio = vi.fn();
    render(
        <DesktopLayout
            model={model()}
            commands={{ setSplitRatio }}
            onSelectView={vi.fn()}
            onCloseView={vi.fn()}
            renderView={(view) => <div>{view.label} content</div>}
        />,
    );

    expect(screen.getByTestId('desktop-tab-group-left'))
        .toHaveAttribute('data-tab-group-id', 'left');
    expect(screen.getByTestId('desktop-tab-group-right'))
        .toHaveAttribute('data-tab-group-id', 'right');
    fireEvent.click(screen.getByTestId('split-handle'));
    expect(setSplitRatio).toHaveBeenCalledWith(65);
});

it('shows the existing view host full screen without remounting it', () => {
    const baseModel = model();
    const setFullscreenView = vi.fn();
    const props = {
        commands: { setSplitRatio: vi.fn(), setFullscreenView },
        onSelectView: vi.fn(),
        onCloseView: vi.fn(),
        getViewActions: () => [{
            id: 'view-action',
            label: 'View action',
            ariaLabel: 'View action',
            icon: 'bi-arrow-clockwise',
            execute: vi.fn(),
            placements: ['fullscreen'],
            testid: 'view-action',
        }],
        renderView: (view) => <div>{view.label} content</div>,
    };
    const { rerender } = render(
        <DesktopLayout model={baseModel} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;

    rerender(
        <DesktopLayout
            model={{ ...baseModel, fullscreenViewId: APP.id }}
            {...props}
        />,
    );

    expect(screen.getByText('Text Lab content').parentElement).toBe(appHost);
    expect(appHost).toHaveAttribute('data-fullscreen', 'true');
    expect(appHost).toHaveAttribute('data-maximized', 'true');
    const fullscreenHeader = screen.getByTestId(
        `fullscreen-view-header-${APP.id}`,
    );
    expect(within(fullscreenHeader).getByText('Text Lab')).toBeInTheDocument();
    expect(within(fullscreenHeader).getByRole(
        'button',
        { name: 'View action' },
    )).toBeInTheDocument();
    expect(screen.getAllByRole(
        'button',
        { name: 'View action' },
    )).toHaveLength(1);
    expect(screen.getByTestId('desktop-tab-group-right').parentElement).toHaveAttribute(
        'aria-hidden',
        'true',
    );
    fireEvent.click(within(fullscreenHeader).getByTestId(
        `restore-view-${APP.id}`,
    ));
    expect(setFullscreenView).toHaveBeenCalledWith(null);
});

it('keeps one keyed view host while its placement changes', () => {
    const props = {
        commands: { setSplitRatio: vi.fn() },
        onSelectView: vi.fn(),
        onCloseView: vi.fn(),
        renderView: (view) => <div>{view.label} content</div>,
    };
    const { rerender } = render(
        <DesktopLayout model={model()} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;

    rerender(
        <DesktopLayout
            model={model({
                leftIds: [CHAT.id, APP.id],
                rightIds: [],
                leftActive: APP.id,
                rightActive: null,
            })}
            {...props}
        />,
    );

    expect(screen.getByText('Text Lab content').parentElement).toBe(appHost);
    expect(appHost).toHaveAttribute('data-tab-group-id', 'left');
});

it('keeps the keyed view host while it floats and exposes floating chrome', () => {
    const floatView = vi.fn();
    const moveView = vi.fn();
    const focusFloatingView = vi.fn();
    const updateFloatingBounds = vi.fn();
    const baseModel = model();
    const props = {
        commands: {
            setSplitRatio: vi.fn(),
            setFullscreenView: vi.fn(),
            focusFloatingView,
            updateFloatingBounds,
        },
        onSelectView: vi.fn(),
        onFocusView: vi.fn(),
        onCloseView: vi.fn(),
        getViewActions: (view, tabGroupId, options) => (
            createDesktopViewActions({
                view,
                tabGroupId,
                tabGroup: tabGroupId ? baseModel.tabGroups[tabGroupId] : null,
                floating: options?.floating,
                commands: {
                    moveView,
                    floatView,
                    enterFullscreen: vi.fn(),
                    requestViewAction: vi.fn(),
                    closeView: vi.fn(),
                    closeOtherViews: vi.fn(),
                    closeViewsToRight: vi.fn(),
                },
            })
        ),
        renderView: (view) => <div>{view.label} content</div>,
    };
    const { rerender } = render(
        <DesktopLayout model={baseModel} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;
    const floatingView = {
        viewId: APP.id,
        x: 80,
        y: 64,
        width: 600,
        height: 400,
        zIndex: 1,
    };

    rerender(
        <DesktopLayout
            model={model({
                rightIds: [],
                rightActive: null,
                floatingView,
            })}
            {...props}
        />,
    );

    expect(screen.getByText('Text Lab content').parentElement).toBe(appHost);
    expect(appHost).toHaveAttribute('data-tab-group-id', 'floating');
    expect(appHost).toHaveAttribute('data-floating', 'true');
    expect(appHost).toHaveStyle({
        left: '80px',
        top: '64px',
        width: '600px',
        height: '400px',
    });
    const floatingHeader = screen.getByTestId(
        `floating-view-header-${APP.id}`,
    );
    expect(within(floatingHeader).getByText('Text Lab')).toBeInTheDocument();
    const pointerEvent = (type, properties) => {
        const event = new Event(type, { bubbles: true, cancelable: true });
        for (const [key, value] of Object.entries(properties)) {
            Object.defineProperty(event, key, { value });
        }
        fireEvent(floatingHeader, event);
    };
    pointerEvent('pointerdown', {
        button: 0,
        pointerId: 1,
        clientX: 100,
        clientY: 90,
    });
    pointerEvent('pointermove', {
        pointerId: 1,
        clientX: 140,
        clientY: 120,
    });
    expect(focusFloatingView).toHaveBeenCalledWith(APP.id);
    expect(appHost).toHaveStyle({
        left: '120px',
        top: '94px',
    });
    expect(updateFloatingBounds).not.toHaveBeenCalled();
    pointerEvent('pointerup', {
        pointerId: 1,
        clientX: 140,
        clientY: 120,
    });
    expect(updateFloatingBounds).toHaveBeenCalledWith(APP.id, {
        x: 120,
        y: 94,
    });
    fireEvent.click(screen.getByTestId(
        `dock-view-${APP.id}-left`,
    ));
    expect(moveView).toHaveBeenCalledWith(APP.id, DESKTOP_TAB_GROUP_IDS.LEFT);
});
