import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import AgentEditorActions from '../AgentEditorActions.jsx';

function setup(props = {}) {
    const callbacks = { onDuplicate: vi.fn(), onExport: vi.fn(), onDelete: vi.fn().mockResolvedValue(undefined), ...props };
    render(<><button>Before</button><AgentEditorActions {...callbacks} /><button>After</button></>);
    return callbacks;
}

afterEach(() => vi.useRealTimers());

it('opens a menu and supports arrows, Home, End, and Escape focus return', async () => {
    const user = userEvent.setup();
    setup();
    const trigger = screen.getByRole('button', { name: 'More actions' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    trigger.focus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menu', { name: 'Agent actions' })).toBeInTheDocument();
    const duplicate = screen.getByRole('menuitem', { name: 'Duplicate' });
    const remove = screen.getByRole('menuitem', { name: 'Delete agent' });
    expect(duplicate).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Export…' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(remove).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(duplicate).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(remove).toHaveFocus();
    await user.keyboard('{Home}');
    expect(duplicate).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: 'Delete agent' })).toHaveFocus();
});

it('Tab and Shift+Tab leave the portaled menu in normal toolbar order', async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    await user.tab();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    await user.tab({ shift: true });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Before' })).toHaveFocus();
});

it('invokes Duplicate and Export once and closes the menu', async () => {
    const user = userEvent.setup();
    const { onDuplicate, onExport } = setup();
    const trigger = screen.getByRole('button', { name: 'More actions' });
    await user.click(trigger);
    await user.keyboard('{Enter}');
    expect(onDuplicate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    await user.click(trigger);
    await user.click(screen.getByRole('menuitem', { name: 'Export…' }));
    expect(onExport).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
});

it('keeps deletion in the menu until the second activation', async () => {
    const user = userEvent.setup();
    const { onDelete } = setup();
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    await user.click(screen.getByRole('menuitem', { name: 'Delete agent' }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.getByRole('menuitem', { name: 'Confirm delete?' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
});

it('disarms deletion after three seconds without deleting', () => {
    vi.useFakeTimers();
    const { onDelete } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete agent' }));
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole('menuitem', { name: 'Delete agent' })).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();
});

it('does not open while saving disables the trigger', async () => {
    const user = userEvent.setup();
    setup({ disabled: true });
    await user.click(screen.getByRole('button', { name: 'More actions' }));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
});
