import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
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
});
