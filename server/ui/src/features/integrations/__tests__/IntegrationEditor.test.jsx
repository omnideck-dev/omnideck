import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import IntegrationEditor from '../editor/IntegrationEditor.jsx';

const RECORD = {
    id: 'gmail_work',
    slug: 'gmail',
    label: 'Work mail',
    state: 'running',
    operation_grants: ['email.messages.get'],
    operations: [
        { id: 'email.messages.get', title: 'Read email message', description: 'Read one message.' },
        { id: 'email.messages.send', title: 'Send email', description: 'Send one message.' },
    ],
};
const ENTRY = {
    id: 'gmail',
    title: 'Gmail',
    operation_groups: [{
        id: 'email',
        title: 'Email',
        operation_ids: ['email.messages.get', 'email.messages.send'],
    }],
};

describe('IntegrationEditor', () => {
    it('opens on Tools and offers only Tools and Connection tabs', () => {
        render(<IntegrationEditor record={RECORD} catalogEntry={ENTRY} />);

        expect(screen.getAllByRole('tab')).toHaveLength(2);
        expect(screen.getByTestId('integration-editor-tab-tools')).toHaveAttribute('aria-selected', 'true');
        expect(screen.queryByRole('tab', { name: /overview/i })).not.toBeInTheDocument();
        expect(screen.getByTestId('integration-tool-email.messages.get')).toBeChecked();
        expect(screen.queryByRole('textbox', { name: 'Connection name' })).not.toBeInTheDocument();
    });

    it('preserves exact grants when only the label changes', () => {
        const onSave = vi.fn();
        render(
            <IntegrationEditor
                record={RECORD}
                catalogEntry={ENTRY}
                saving={false}
                onSave={onSave}
                onRemove={vi.fn()}
                onReconnect={vi.fn()}
            />,
        );

        fireEvent.click(screen.getByTestId('integration-editor-tab-connection'));
        fireEvent.change(screen.getByRole('textbox', { name: 'Connection name' }), {
            target: { value: 'Renamed mail' },
        });
        fireEvent.click(screen.getByTestId('integrations-save-gmail_work'));

        expect(onSave).toHaveBeenCalledWith({ label: 'Renamed mail' });
    });

    it('keeps drafts across tabs and reverts both name and tool edits', () => {
        const onReconnect = vi.fn();
        render(<IntegrationEditor record={RECORD} catalogEntry={ENTRY} onReconnect={onReconnect} />);
        fireEvent.click(screen.getByTestId('integration-tool-email.messages.send'));
        fireEvent.click(screen.getByTestId('integration-editor-tab-connection'));
        fireEvent.change(screen.getByRole('textbox', { name: 'Connection name' }), {
            target: { value: 'Draft name' },
        });
        fireEvent.click(screen.getByTestId('integrations-reconnect-gmail_work'));
        expect(onReconnect).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByTestId('integration-editor-tab-tools'));
        expect(screen.getByTestId('integration-tool-email.messages.send')).toBeChecked();
        fireEvent.click(screen.getByTestId('integration-editor-tab-connection'));
        expect(screen.getByRole('textbox', { name: 'Connection name' })).toHaveValue('Draft name');
        fireEvent.click(screen.getByTestId('integrations-cancel-gmail_work'));
        expect(screen.getByRole('textbox', { name: 'Connection name' })).toHaveValue(RECORD.label);
        fireEvent.click(screen.getByTestId('integration-editor-tab-tools'));
        expect(screen.getByTestId('integration-tool-email.messages.send')).not.toBeChecked();
        expect(screen.getByTestId('integrations-save-gmail_work')).toBeDisabled();
    });

    it('edits individual operation grants with the shared picker', () => {
        const onSave = vi.fn();
        render(
            <IntegrationEditor
                record={RECORD}
                catalogEntry={ENTRY}
                saving={false}
                onSave={onSave}
                onRemove={vi.fn()}
                onReconnect={vi.fn()}
            />,
        );
        fireEvent.click(screen.getByTestId('integration-editor-tab-tools'));
        fireEvent.click(screen.getByTestId('integration-tool-email.messages.send'));
        fireEvent.click(screen.getByTestId('integrations-save-gmail_work'));

        expect(onSave).toHaveBeenCalledWith({
            operation_grants: ['email.messages.get', 'email.messages.send'],
        });
    });

    it('synchronizes drafts when reconnect narrows the authoritative grants', async () => {
        const props = {
            catalogEntry: ENTRY,
            saving: false,
            onSave: vi.fn(),
            onRemove: vi.fn(),
            onReconnect: vi.fn(),
        };
        const { rerender } = render(<IntegrationEditor record={RECORD} {...props} />);
        fireEvent.click(screen.getByTestId('integration-editor-tab-tools'));
        expect(screen.getByTestId('integration-tool-email.messages.get')).toBeChecked();

        rerender(
            <IntegrationEditor
                record={{ ...RECORD, operation_grants: [] }}
                {...props}
            />,
        );

        await waitFor(() => {
            expect(screen.getByTestId('integration-tool-email.messages.get')).not.toBeChecked();
        });
        expect(screen.getByTestId('integrations-save-gmail_work')).toBeDisabled();
    });
});
