import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import DesktopDownloadFeedback from '../DesktopDownloadFeedback.jsx';
import { ToastProvider } from '../ToastProvider.jsx';

function renderFeedback() {
    return render(
        <ToastProvider>
            <DesktopDownloadFeedback />
        </ToastProvider>,
    );
}

describe('DesktopDownloadFeedback', () => {
    afterEach(() => {
        delete window.__omnideckPendingDownload;
    });

    it('uses the existing success toast after the native host finishes a download', () => {
        renderFeedback();
        act(() => window.dispatchEvent(new CustomEvent('omnideck:download', {
            detail: { filename: 'report.pdf', success: true },
        })));

        expect(screen.getByText('Download complete')).toBeInTheDocument();
        expect(screen.getByText('report.pdf was saved to Downloads.')).toBeInTheDocument();
    });

    it('uses the existing error toast after a native failure', () => {
        renderFeedback();
        act(() => window.dispatchEvent(new CustomEvent('omnideck:download', {
            detail: { filename: 'report.pdf', success: false },
        })));

        expect(screen.getByText('Download failed')).toBeInTheDocument();
        expect(screen.getByText('Could not save report.pdf.')).toBeInTheDocument();
    });

    it('consumes completion feedback retained before the listener mounted', () => {
        window.__omnideckPendingDownload = { filename: 'early.pdf', success: true };
        renderFeedback();

        expect(screen.getByText('Download complete')).toBeInTheDocument();
        expect(screen.getByText('early.pdf was saved to Downloads.')).toBeInTheDocument();
        expect(window.__omnideckPendingDownload).toBeUndefined();
    });
});
