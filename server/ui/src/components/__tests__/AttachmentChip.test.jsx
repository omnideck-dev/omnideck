import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import AttachmentChip from '../AttachmentChip.jsx';

const DATA_URL = 'data:image/png;base64,iVBORw0KGgo=';

describe('AttachmentChip', () => {
    it('renders an image thumbnail when given a src', () => {
        render(<AttachmentChip src={DATA_URL} filename="shot.png" />);
        const img = screen.getByTestId('attachment-image');
        expect(img).toHaveAttribute('src', DATA_URL);
        expect(img).toHaveAttribute('alt', 'shot.png');
        // An image is a card too, not a bare thumbnail — it carries the filename.
        expect(screen.getByTitle('shot.png')).toBeInTheDocument();
        expect(screen.queryByTestId('attachment-file')).not.toBeInTheDocument();
    });

    it('renders a file card when there is no src', () => {
        render(<AttachmentChip filename="report.pdf" />);
        expect(screen.getByTestId('attachment-file')).toBeInTheDocument();
        expect(screen.getByTitle('report.pdf')).toBeInTheDocument();
        expect(screen.getByText('PDF')).toBeInTheDocument();
        expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
    });

    it('falls back to a type-icon card when a persisted image fails to load', () => {
        render(<AttachmentChip src="/uploads/gone.png" filename="gone.png" content_type="image/png" />);
        // Simulate the container path 404-ing on resume.
        fireEvent.error(screen.getByTestId('attachment-image'));
        expect(screen.queryByTestId('attachment-image')).not.toBeInTheDocument();
        expect(screen.getByTestId('attachment-file')).toBeInTheDocument();
        expect(screen.getByTitle('gone.png')).toBeInTheDocument();
    });

    it('middle-truncates a long filename but keeps the extension', () => {
        render(<AttachmentChip filename="really_long_report_final_v2.xlsx" />);
        // Full name is available on hover…
        expect(screen.getByTitle('really_long_report_final_v2.xlsx')).toBeInTheDocument();
        // …and the tail span keeps the extension so it is never clipped away.
        expect(screen.getByText(/\.xlsx$/)).toBeInTheDocument();
    });

    it('shows the size in the file meta when sizeBytes is given', () => {
        render(<AttachmentChip filename="notes.md" sizeBytes={2048} />);
        expect(screen.getByText('MD · 2 KB')).toBeInTheDocument();
    });

    it('omits the size when sizeBytes is absent', () => {
        render(<AttachmentChip filename="notes.md" />);
        expect(screen.getByText('MD')).toBeInTheDocument();
    });

    it('shows a remove control only when onRemove is given', async () => {
        const user = userEvent.setup();
        const onRemove = vi.fn();
        const { rerender } = render(<AttachmentChip src={DATA_URL} filename="a.png" />);
        expect(screen.queryByLabelText('Remove attachment')).not.toBeInTheDocument();

        rerender(<AttachmentChip src={DATA_URL} filename="a.png" onRemove={onRemove} />);
        await user.click(screen.getByLabelText('Remove attachment'));
        expect(onRemove).toHaveBeenCalledOnce();
    });

    it('fires onRemove from a file card', async () => {
        const user = userEvent.setup();
        const onRemove = vi.fn();
        render(<AttachmentChip filename="report.pdf" onRemove={onRemove} />);
        await user.click(screen.getByLabelText('Remove attachment'));
        expect(onRemove).toHaveBeenCalledOnce();
    });
});
