import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { FileControlsProvider } from '../FileControls.jsx';
import FilePreview from '../FilePreview.jsx';

const ITEM = { filename: 'notes.txt', content_type: 'text/plain', content: btoa('hello') };

it('shows a Download button by default', () => {
    render(<FilePreview item={ITEM} />);
    expect(screen.getByTestId('file-download')).toBeInTheDocument();
});

it('replaces the Download button with the action that file controls supply', () => {
    const Share = vi.fn(({ item, download }) => <button onClick={download}>Share {item.filename}</button>);
    render(<FileControlsProvider controls={{ preview: { Actions: Share } }}><FilePreview item={ITEM} /></FileControlsProvider>);
    expect(screen.queryByTestId('file-download')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Share notes.txt' })).toBeInTheDocument();
    expect(Share.mock.lastCall[0]).toEqual(expect.objectContaining({ item: ITEM, download: expect.any(Function) }));
});

it('passes a download that saves the file', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const Share = ({ download }) => <button onClick={download}>Save</button>;
    render(<FileControlsProvider controls={{ preview: { Actions: Share } }}><FilePreview item={ITEM} /></FileControlsProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
});
