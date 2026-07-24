import {
    fireEvent,
    render,
    screen,
    within,
} from '@testing-library/react';
import { expect, it, vi } from 'vitest';

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
