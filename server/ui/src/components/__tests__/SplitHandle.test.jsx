import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import SplitHandle from '../SplitHandle.jsx';

test('reports drag position relative to the full tab-group container', () => {
    const onDrag = vi.fn();
    const onDragEnd = vi.fn();
    render(
        <div data-testid="layout">
            <SplitHandle onDrag={onDrag} onDragEnd={onDragEnd} />
        </div>,
    );
    const layout = screen.getByTestId('layout');
    layout.getBoundingClientRect = () => ({
        left: 100,
        width: 1000,
    });

    fireEvent.mouseDown(screen.getByRole(
        'separator',
        { name: 'Resize tab groups' },
    ));
    fireEvent.mouseMove(document, { clientX: 600 });
    fireEvent.mouseMove(document, { clientX: 750 });
    fireEvent.mouseUp(document);

    expect(onDrag).toHaveBeenNthCalledWith(1, 50);
    expect(onDrag).toHaveBeenNthCalledWith(2, 65);
    expect(onDragEnd).toHaveBeenCalledOnce();
    expect(onDragEnd).toHaveBeenCalledWith(65);
});
