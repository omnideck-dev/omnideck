import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../goals/ConversationGoalStatus.jsx', () => ({ default: () => null }));

const { default: PhoneConversationRow } = await import('../PhoneConversationRow.jsx');

const convo = { conversation_id: 'c1', title: 'Pricing for project tools', pinned: false };

function setup(props = {}) {
    const handlers = {
        onOpen: vi.fn(),
        onMenu: vi.fn(),
        onSwipe: vi.fn(),
        onTogglePin: vi.fn(),
        onArchive: vi.fn(),
        onDelete: vi.fn(),
    };
    const view = render(<PhoneConversationRow convo={convo} running={false} finished={false} swipeOffset={0} {...handlers} {...props} />);
    return { ...handlers, view, row: screen.getByTestId('phone-conversation-row') };
}

function pointer(row, type, clientX = 0, clientY = 0) {
    fireEvent(row, new MouseEvent(type, { bubbles: true, cancelable: true, button: 0, clientX, clientY }));
}

function drag(row, dx, dy = 0, { click = true } = {}) {
    pointer(row, 'pointerdown', 200, 100);
    pointer(row, 'pointermove', 200 + dx / 2, 100 + dy / 2);
    pointer(row, 'pointermove', 200 + dx, 100 + dy);
    pointer(row, 'pointerup', 200 + dx, 100 + dy);
    if (click) fireEvent.click(row);
}

function tap(row) {
    pointer(row, 'pointerdown', 10, 10);
    pointer(row, 'pointerup', 10, 10);
    fireEvent.click(row);
}

describe('PhoneConversationRow', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('opens the chat on tap', () => {
        const { row, onOpen } = setup();
        pointer(row, 'pointerdown', 10, 10);
        pointer(row, 'pointerup');
        fireEvent.click(row);
        expect(onOpen).toHaveBeenCalledOnce();
    });

    it('opens the row menu at the finger after a press and hold, without opening the chat', () => {
        const { row, onMenu, onOpen } = setup();
        pointer(row, 'pointerdown', 40, 60);
        act(() => vi.advanceTimersByTime(500));
        pointer(row, 'pointerup');
        fireEvent.click(row);
        expect(onMenu).toHaveBeenCalledWith({ left: 40, right: 40, top: 60, bottom: 60 });
        expect(onOpen).not.toHaveBeenCalled();
    });

    it('opens the row menu on right click', () => {
        const { row, onMenu } = setup();
        fireEvent.contextMenu(row, { clientX: 5, clientY: 6 });
        expect(onMenu).toHaveBeenCalledWith({ left: 5, right: 5, top: 6, bottom: 6 });
    });

    it('snaps open to Archive and Delete after a swipe left, without opening the chat', () => {
        const { row, onSwipe, onOpen } = setup();
        drag(row, -120);
        expect(onSwipe).toHaveBeenLastCalledWith(-160);
        expect(onOpen).not.toHaveBeenCalled();
    });

    it('snaps open to Pin after a swipe right', () => {
        const { row, onSwipe } = setup();
        drag(row, 70);
        expect(onSwipe).toHaveBeenLastCalledWith(84);
    });

    it('opens the chat on the next tap when the browser sent no click after a swipe', () => {
        const { row, onOpen } = setup();
        drag(row, -30, 0, { click: false });
        tap(row);
        expect(onOpen).toHaveBeenCalledOnce();
    });

    it('opens the chat on the next tap when the browser sent no click after a press and hold', () => {
        const { row, onOpen } = setup();
        pointer(row, 'pointerdown', 40, 60);
        act(() => vi.advanceTimersByTime(500));
        pointer(row, 'pointerup');
        tap(row);
        expect(onOpen).toHaveBeenCalledOnce();
    });

    it('snaps closed after a short swipe', () => {
        const { row, onSwipe } = setup();
        drag(row, -30);
        expect(onSwipe).toHaveBeenLastCalledWith(0);
    });

    it('leaves a vertical scroll alone', () => {
        const { row, onSwipe, onMenu } = setup();
        pointer(row, 'pointerdown', 200, 100);
        pointer(row, 'pointermove', 203, 140);
        act(() => vi.advanceTimersByTime(500));
        pointer(row, 'pointerup');
        expect(onSwipe).not.toHaveBeenCalled();
        expect(onMenu).not.toHaveBeenCalled();
    });

    it('closes an open row on tap instead of opening the chat', () => {
        const { row, onSwipe, onOpen } = setup({ swipeOffset: -160 });
        fireEvent.click(row);
        expect(onSwipe).toHaveBeenCalledWith(0);
        expect(onOpen).not.toHaveBeenCalled();
    });

    it('runs the revealed actions, and asks before deleting', async () => {
        vi.useRealTimers();
        const user = userEvent.setup();
        const { onArchive, onDelete, onTogglePin } = setup({ swipeOffset: -160 });
        await user.click(screen.getByTestId('phone-swipe-archive'));
        expect(onArchive).toHaveBeenCalledOnce();
        await user.click(screen.getByTestId('phone-swipe-delete'));
        expect(onDelete).not.toHaveBeenCalled();
        expect(screen.getByTestId('phone-swipe-delete')).toHaveTextContent('Confirm?');
        await user.click(screen.getByTestId('phone-swipe-delete'));
        expect(onDelete).toHaveBeenCalledOnce();
        await user.click(screen.getByTestId('phone-swipe-pin'));
        expect(onTogglePin).toHaveBeenCalledOnce();
    });

    it('labels the swipe action Unpin for a pinned chat and shows running work', () => {
        setup({ convo: { ...convo, pinned: true }, running: true });
        expect(screen.getByTestId('phone-swipe-pin')).toHaveTextContent('Unpin');
        expect(screen.getByRole('img', { name: 'Running' })).toBeInTheDocument();
    });
});
