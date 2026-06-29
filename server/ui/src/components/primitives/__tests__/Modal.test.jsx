import { render, screen, fireEvent } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import Modal from '../Modal.jsx';

test('renders its children inside the panel', () => {
    render(<Modal testId="m"><p>body</p></Modal>);
    const panel = screen.getByTestId('m');
    expect(panel).toHaveAttribute('role', 'dialog');
    expect(panel).toContainElement(screen.getByText('body'));
});

test('Escape dismisses the modal', () => {
    const onClose = vi.fn();
    render(<Modal testId="m" onClose={onClose}>x</Modal>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
});

test('clicking the scrim dismisses, clicking the panel does not', () => {
    const onClose = vi.fn();
    const { container } = render(<Modal testId="m" onClose={onClose}>x</Modal>);
    fireEvent.click(screen.getByTestId('m'));
    expect(onClose).not.toHaveBeenCalled();
    // The scrim is the panel's parent; clicking it closes.
    fireEvent.click(container.firstChild);
    expect(onClose).toHaveBeenCalledTimes(1);
});

test('width prop overrides the panel width', () => {
    render(<Modal testId="m" width={560}>x</Modal>);
    expect(screen.getByTestId('m')).toHaveStyle({ width: '560px' });
});
