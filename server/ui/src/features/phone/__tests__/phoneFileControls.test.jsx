import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FileControlsProvider } from '../../../components/FileControls.jsx';
import FileOutput from '../../../components/FileOutput.jsx';
import FilePreview from '../../../components/FilePreview.jsx';
import { ToastProvider } from '../../../components/ToastProvider.jsx';
import { PHONE_FILE_CONTROLS } from '../phoneFileControls.js';

const ZIP = { filename: 'site.zip', path: '/home/omnideck/site.zip', content_type: 'application/zip' };
const NOTES = { filename: 'notes.txt', content_type: 'text/plain', content: btoa('hello') };

function renderOnPhone(ui) {
    return render(
        <ToastProvider>
            <FileControlsProvider controls={PHONE_FILE_CONTROLS}>{ui}</FileControlsProvider>
        </ToastProvider>,
    );
}

describe('phone file controls', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('opens every file card on its own screen', async () => {
        const onPreview = vi.fn();
        renderOnPhone(<FileOutput item={ZIP} onPreview={onPreview} />);
        await userEvent.click(screen.getByText('site.zip'));
        expect(onPreview).toHaveBeenCalledWith(ZIP);
    });

    it('gives the file card one Download button that does not open the file', async () => {
        vi.stubGlobal('navigator', { ...navigator, canShare: undefined, share: undefined });
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        const onPreview = vi.fn();
        renderOnPhone(<FileOutput item={ZIP} onPreview={onPreview} />);
        expect(screen.getAllByRole('button')).toHaveLength(1);
        await userEvent.click(screen.getByTestId('file-download'));
        expect(click).toHaveBeenCalledOnce();
        expect(onPreview).not.toHaveBeenCalled();
        click.mockRestore();
    });

    it('gives the file card a Share button when the phone can share files', async () => {
        const share = vi.fn(async () => {});
        vi.stubGlobal('navigator', { ...navigator, canShare: () => true, share });
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['zip']) })));
        const onPreview = vi.fn();
        renderOnPhone(<FileOutput item={ZIP} onPreview={onPreview} />);
        await userEvent.click(screen.getByTestId('phone-file-share'));
        expect(share).toHaveBeenCalledWith(expect.objectContaining({ title: 'site.zip' }));
        expect(onPreview).not.toHaveBeenCalled();
    });

    it('offers Download in the file preview when the phone cannot share files', () => {
        vi.stubGlobal('navigator', { ...navigator, canShare: undefined, share: undefined });
        renderOnPhone(<FilePreview item={NOTES} />);
        expect(screen.getByTestId('file-download')).toBeInTheDocument();
        expect(screen.queryByTestId('phone-file-share')).not.toBeInTheDocument();
    });

    it('offers Share in place of Download when the phone can share files', async () => {
        const share = vi.fn(async () => {});
        vi.stubGlobal('navigator', { ...navigator, canShare: () => true, share });
        renderOnPhone(<FilePreview item={NOTES} />);
        expect(screen.queryByTestId('file-download')).not.toBeInTheDocument();
        await userEvent.click(screen.getByTestId('phone-file-share'));
        expect(share).toHaveBeenCalledWith(expect.objectContaining({ title: 'notes.txt' }));
    });
});
