import { useRef, useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import Menu from '../Menu.jsx';

function Harness({ items, initialFocus }) {
    const [open, setOpen] = useState(true);
    const triggerRef = useRef(null);
    return <>
        <button type="button">Before</button>
        <button type="button" ref={triggerRef} onClick={() => setOpen(true)}>Actions</button>
        <button type="button">After</button>
        {open && <Menu triggerRef={triggerRef} onClose={() => setOpen(false)} label="Actions" items={items} initialFocus={initialFocus} />}
    </>;
}

const items = (onSelect = vi.fn()) => [
    { id: 'one', label: 'One', onSelect },
    { id: 'two', label: 'Two', disabled: true, onSelect },
    { id: 'three', label: 'Three', shortcut: '/three', onSelect },
    { id: 'four', label: 'Four', icon: 'bi-x', onSelect },
];
const item = (name) => screen.getByRole('menuitem', { name: new RegExp(name) });
const press = (key, options = {}) => fireEvent.keyDown(document.activeElement, { key, ...options });

describe('Menu', () => {
    it('focuses the first item, or the one asked for, when it opens', () => {
        const { unmount } = render(<Harness items={items()} />);
        expect(item('One')).toHaveFocus();
        unmount();
        render(<Harness items={items()} initialFocus={2} />);
        expect(item('Four')).toHaveFocus();
    });

    it('moves with arrows past disabled items and wraps', () => {
        render(<Harness items={items()} />);
        press('ArrowDown');
        expect(item('Three')).toHaveFocus();
        press('ArrowDown');
        press('ArrowDown');
        expect(item('One')).toHaveFocus();
        press('ArrowUp');
        expect(item('Four')).toHaveFocus();
    });

    it('jumps with Home and End', () => {
        render(<Harness items={items()} />);
        press('End');
        expect(item('Four')).toHaveFocus();
        press('Home');
        expect(item('One')).toHaveFocus();
    });

    it('closes on Escape and returns focus to the trigger', () => {
        render(<Harness items={items()} />);
        press('Escape');
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Actions' })).toHaveFocus();
    });

    it('closes on Tab and moves on from the trigger', () => {
        const { unmount } = render(<Harness items={items()} />);
        press('Tab');
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'After' })).toHaveFocus();
        unmount();
        render(<Harness items={items()} />);
        press('Tab', { shiftKey: true });
        expect(screen.getByRole('button', { name: 'Before' })).toHaveFocus();
    });

    it('runs the picked item after closing and shows its shortcut', () => {
        const onSelect = vi.fn();
        render(<Harness items={items(onSelect)} />);
        expect(item('Three')).toHaveTextContent('/three');
        fireEvent.click(item('Three'));
        expect(onSelect).toHaveBeenCalledTimes(1);
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Actions' })).toHaveFocus();
    });

    it('arms a confirm item on the first click and runs it on the second', async () => {
        const onConfirm = vi.fn();
        render(<Harness items={[{ id: 'delete', label: 'Delete…', separatorBefore: true, confirm: { confirmLabel: 'Delete this?', onConfirm } }]} />);
        expect(screen.getByRole('separator')).toBeInTheDocument();
        fireEvent.click(item('Delete'));
        expect(onConfirm).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('menuitem', { name: 'Delete this?' }));
        expect(onConfirm).toHaveBeenCalledTimes(1);
    });
});
