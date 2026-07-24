import {
    fireEvent,
    render,
    screen,
    within,
} from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { createDesktopSurfaceActions } from '../desktopSurfaceActions.js';
import { DESKTOP_PANE_IDS } from '../desktopWindowReducer.js';

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

const { default: DesktopWindowLayout } = await import('../DesktopWindowLayout.jsx');

const CHAT = { id: 'destination:conversation', label: 'Chat', kind: 'conversation' };
const APP = { id: 'custom-app:text-lab', label: 'Text Lab', kind: 'custom-app' };

function model({
    leftIds = [CHAT.id],
    rightIds = [APP.id],
    leftActive = CHAT.id,
    rightActive = APP.id,
    floatingWindow = null,
} = {}) {
    const surfacesById = { [CHAT.id]: CHAT, [APP.id]: APP };
    const pane = (surfaceIds, activeSurfaceId) => ({
        surfaceIds,
        activeSurfaceId,
        surfaces: surfaceIds.map((id) => surfacesById[id]),
    });
    return {
        panes: {
            left: pane(leftIds, leftActive),
            right: pane(rightIds, rightActive),
        },
        surfaces: [CHAT, APP],
        surfacesById,
        floatingWindowsBySurfaceId: floatingWindow
            ? { [floatingWindow.surfaceId]: floatingWindow }
            : {},
        focusedFloatingSurfaceId: floatingWindow?.surfaceId || null,
        splitRatio: 40,
        fullscreenSurfaceId: null,
    };
}

it('renders both sides with the same pane component and connects split resizing', () => {
    const setSplitRatio = vi.fn();
    render(
        <DesktopWindowLayout
            model={model()}
            commands={{ setSplitRatio }}
            onSelectSurface={vi.fn()}
            onCloseSurface={vi.fn()}
            renderSurface={(surface) => <div>{surface.label} content</div>}
        />,
    );

    expect(screen.getByTestId('desktop-pane-left')).toHaveAttribute('data-pane-id', 'left');
    expect(screen.getByTestId('desktop-pane-right')).toHaveAttribute('data-pane-id', 'right');
    fireEvent.click(screen.getByTestId('split-handle'));
    expect(setSplitRatio).toHaveBeenCalledWith(65);
});

it('shows the existing surface host full screen without remounting it', () => {
    const baseModel = model();
    const setFullscreenSurface = vi.fn();
    const props = {
        commands: { setSplitRatio: vi.fn(), setFullscreenSurface },
        onSelectSurface: vi.fn(),
        onCloseSurface: vi.fn(),
        getSurfaceActions: () => [{
            id: 'surface-action',
            label: 'Surface action',
            ariaLabel: 'Surface action',
            icon: 'bi-arrow-clockwise',
            execute: vi.fn(),
            placements: ['fullscreen'],
            testid: 'surface-action',
        }],
        renderSurface: (surface) => <div>{surface.label} content</div>,
    };
    const { rerender } = render(
        <DesktopWindowLayout model={baseModel} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;

    rerender(
        <DesktopWindowLayout
            model={{ ...baseModel, fullscreenSurfaceId: APP.id }}
            {...props}
        />,
    );

    expect(screen.getByText('Text Lab content').parentElement).toBe(appHost);
    expect(appHost).toHaveAttribute('data-fullscreen', 'true');
    expect(appHost).toHaveAttribute('data-maximized', 'true');
    const fullscreenHeader = screen.getByTestId(
        `fullscreen-surface-header-${APP.id}`,
    );
    expect(within(fullscreenHeader).getByText('Text Lab')).toBeInTheDocument();
    expect(within(fullscreenHeader).getByRole(
        'button',
        { name: 'Surface action' },
    )).toBeInTheDocument();
    expect(screen.getAllByRole(
        'button',
        { name: 'Surface action' },
    )).toHaveLength(1);
    expect(screen.getByTestId('desktop-pane-right').parentElement).toHaveAttribute(
        'aria-hidden',
        'true',
    );
    fireEvent.click(within(fullscreenHeader).getByTestId(
        `restore-surface-${APP.id}`,
    ));
    expect(setFullscreenSurface).toHaveBeenCalledWith(null);
});

it('keeps one keyed surface host while its placement changes', () => {
    const props = {
        commands: { setSplitRatio: vi.fn() },
        onSelectSurface: vi.fn(),
        onCloseSurface: vi.fn(),
        renderSurface: (surface) => <div>{surface.label} content</div>,
    };
    const { rerender } = render(
        <DesktopWindowLayout model={model()} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;

    rerender(
        <DesktopWindowLayout
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
    expect(appHost).toHaveAttribute('data-pane-id', 'left');
});

it('keeps the keyed surface host while it floats and exposes window chrome', () => {
    const floatSurface = vi.fn();
    const moveSurface = vi.fn();
    const focusFloatingSurface = vi.fn();
    const updateFloatingBounds = vi.fn();
    const baseModel = model();
    const props = {
        commands: {
            setSplitRatio: vi.fn(),
            setFullscreenSurface: vi.fn(),
            focusFloatingSurface,
            updateFloatingBounds,
        },
        onSelectSurface: vi.fn(),
        onFocusSurface: vi.fn(),
        onCloseSurface: vi.fn(),
        getSurfaceActions: (surface, paneId, options) => (
            createDesktopSurfaceActions({
                surface,
                paneId,
                pane: paneId ? baseModel.panes[paneId] : null,
                floating: options?.floating,
                commands: {
                    moveSurface,
                    floatSurface,
                    enterFullscreen: vi.fn(),
                    reloadCustomApp: vi.fn(),
                    closeSurface: vi.fn(),
                    closeOtherSurfaces: vi.fn(),
                    closeSurfacesToRight: vi.fn(),
                },
            })
        ),
        renderSurface: (surface) => <div>{surface.label} content</div>,
    };
    const { rerender } = render(
        <DesktopWindowLayout model={baseModel} {...props} />,
    );
    const appHost = screen.getByText('Text Lab content').parentElement;
    const floatingWindow = {
        surfaceId: APP.id,
        x: 80,
        y: 64,
        width: 600,
        height: 400,
        zIndex: 1,
    };

    rerender(
        <DesktopWindowLayout
            model={model({
                rightIds: [],
                rightActive: null,
                floatingWindow,
            })}
            {...props}
        />,
    );

    expect(screen.getByText('Text Lab content').parentElement).toBe(appHost);
    expect(appHost).toHaveAttribute('data-pane-id', 'floating');
    expect(appHost).toHaveAttribute('data-floating', 'true');
    expect(appHost).toHaveStyle({
        left: '80px',
        top: '64px',
        width: '600px',
        height: '400px',
    });
    const floatingHeader = screen.getByTestId(
        `floating-surface-header-${APP.id}`,
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
    expect(focusFloatingSurface).toHaveBeenCalledWith(APP.id);
    expect(updateFloatingBounds).toHaveBeenCalledWith(APP.id, {
        x: 120,
        y: 94,
    });
    fireEvent.click(screen.getByTestId(
        `dock-surface-${APP.id}-left`,
    ));
    expect(moveSurface).toHaveBeenCalledWith(APP.id, DESKTOP_PANE_IDS.LEFT);
});
