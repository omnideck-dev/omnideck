import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import SplitHandle from '../SplitHandle.jsx';

test('reports drag position relative to the full pane container', () => {
    const onDrag = vi.fn();
    render(
        <div data-testid="layout">
            <SplitHandle onDrag={onDrag} />
        </div>,
    );
    const layout = screen.getByTestId('layout');
    layout.getBoundingClientRect = () => ({
        left: 100,
        width: 1000,
    });

    fireEvent.mouseDown(screen.getByRole('separator', { name: 'Resize panes' }));
    fireEvent.mouseMove(document, { clientX: 750 });
    fireEvent.mouseUp(document);

    expect(onDrag).toHaveBeenCalledWith(65);
});
