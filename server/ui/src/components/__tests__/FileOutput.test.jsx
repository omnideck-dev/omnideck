import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import FileOutput from '../FileOutput.jsx';

afterEach(() => vi.restoreAllMocks());

it('downloads a file whose name contains URL punctuation', () => {
    let anchor;
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
        anchor = this;
    });
    render(<FileOutput item={{ filename: 'Invoice #123.pdf', path: '/home/omnideck/Invoice #123.pdf', content_type: 'application/pdf' }} />);
    fireEvent.click(screen.getByTestId('file-download-btn'));
    expect(click).toHaveBeenCalledOnce();
    expect(anchor.getAttribute('href')).toBe('/home/omnideck/Invoice%20%23123.pdf');
    expect(anchor.download).toBe('Invoice #123.pdf');
});
