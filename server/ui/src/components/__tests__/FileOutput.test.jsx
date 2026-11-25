import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FileControlsProvider } from '../FileControls.jsx';
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

it('downloads a file it cannot preview when the card is tapped', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const onPreview = vi.fn();
    render(<FileOutput item={{ filename: 'site.zip', path: '/home/omnideck/site.zip', content_type: 'application/zip' }} onPreview={onPreview} />);
    fireEvent.click(screen.getByText('site.zip'));
    expect(click).toHaveBeenCalledOnce();
    expect(onPreview).not.toHaveBeenCalled();
});

it('renders the buttons and tap action that file controls supply', () => {
    const open = vi.fn();
    const controls = { card: { Actions: ({ item }) => <button>Send {item.filename}</button>, open } };
    const item = { filename: 'notes.md', path: '/home/omnideck/notes.md', content_type: 'text/markdown' };
    render(<FileControlsProvider controls={controls}><FileOutput item={item} /></FileControlsProvider>);
    expect(screen.queryByTestId('file-download-btn')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send notes.md' })).toBeInTheDocument();
    fireEvent.click(screen.getByText('notes.md'));
    expect(open).toHaveBeenCalledWith(expect.objectContaining({ item, previewable: true }));
});
