import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import IntegrationEditor from '../editor/IntegrationEditor.jsx';

const RECORD = {
    id: 'gmail_work', slug: 'gmail', label: 'Work mail', state: 'running',
    operation_grants: ['email.messages.get'],
    operations: [
        { id: 'email.messages.get', title: 'Read email message', description: 'Read one message.' },
        { id: 'email.messages.send', title: 'Send email', description: 'Send one message.' },
    ],
};
const ENTRY = {
    id: 'gmail', title: 'Gmail',
    operation_groups: [{ id: 'email', title: 'Email', operation_ids: ['email.messages.get', 'email.messages.send'] }],
};
function props(extra = {}) {
    return { record: RECORD, catalogEntry: ENTRY, onSave: vi.fn().mockResolvedValue(true),
        onRemove: vi.fn(), onReconnect: vi.fn(), onClearSaveError: vi.fn(), ...extra };
}
const openTools = () => fireEvent.click(screen.getByRole('button', { name: 'Change tools' }));
const openSettings = () => fireEvent.click(screen.getByText('Connection settings', { exact: true }));
const openRename = () => {
    openSettings();
    fireEvent.click(screen.getByRole('button', { name: 'Rename', exact: true }));
};

describe('IntegrationEditor', () => {
    afterEach(() => vi.useRealTimers());

    it('excludes unavailable saved tools from the overview and disables them in the picker', () => {
        render(<IntegrationEditor {...props({ record: { ...RECORD,
            operation_grants: ['email.messages.get', 'email.messages.send'],
            operations: [RECORD.operations[0], { ...RECORD.operations[1], unavailable_reason: 'Invalid schema' }],
        } })} />);
        expect(screen.getByText('1 tool selected for this integration.')).toBeInTheDocument();
        expect(screen.queryByText('Send email')).not.toBeInTheDocument();
        openTools();
        expect(screen.getByTestId('integration-tool-email.messages.send')).toBeDisabled();
        expect(screen.getByText('1 of 1 selected')).toBeInTheDocument();
    });

    it('warns about assignment removal and allows cancellation before deleting', async () => {
        const p = props();
        render(<IntegrationEditor {...p} />);
        openSettings();
        fireEvent.click(screen.getByRole('button', { name: 'Remove integration…' }));
        const dialog = screen.getByRole('dialog', { name: 'Delete Work mail?' });
        expect(dialog).toHaveTextContent('This removes the connection and its tool assignments from all agents and skills. Reconnecting later won’t restore those assignments.');
        expect(p.onRemove).not.toHaveBeenCalled();
        fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(p.onRemove).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Remove integration…' }));
        await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Delete integration' })));
        expect(p.onRemove).toHaveBeenCalledOnce();
    });

    it('prevents duplicate deletion and shows errors in the confirmation', async () => {
        let finish;
        const p = props({ onRemove: vi.fn(() => new Promise(resolve => { finish = resolve; })) });
        const { rerender } = render(<IntegrationEditor {...p} />);
        openSettings();
        fireEvent.click(screen.getByRole('button', { name: 'Remove integration…' }));
        fireEvent.click(screen.getByRole('button', { name: 'Delete integration' }));
        expect(screen.getByRole('button', { name: 'Deleting…' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        rerender(<IntegrationEditor {...p} removeError="Connection service unavailable" />);
        await act(async () => finish());
        expect(within(screen.getByRole('dialog')).getByText('Connection service unavailable')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Delete integration' })).toBeEnabled();
        expect(p.onRemove).toHaveBeenCalledOnce();
    });

    it('starts connection settings collapsed and lets the user expand and collapse them', () => {
        render(<IntegrationEditor {...props()} />);
        const settings = screen.getByText('Connection settings', { exact: true }).closest('details');
        const rename = screen.getByTestId(`integrations-rename-${RECORD.id}`);
        expect(settings).not.toHaveAttribute('open');
        expect(rename).not.toBeVisible();
        openSettings();
        expect(settings).toHaveAttribute('open');
        expect(rename).toBeVisible();
        openSettings();
        expect(rename).not.toBeVisible();
    });

    it('shows a read-only grouped overview without tabs, inputs or operation IDs', () => {
        render(<IntegrationEditor {...props()} />);
        expect(screen.queryByText('Connected')).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'What omnideck can do' })).toBeInTheDocument();
        const group = screen.getByRole('region', { name: 'Email' });
        expect(group).toHaveTextContent('Read email message');
        expect(group).not.toHaveTextContent('Send email');
        expect(screen.getAllByText(/1 tool selected/)).toHaveLength(1);
        expect(screen.queryByRole('heading', { name: 'Email' })).not.toBeInTheDocument();
        expect(screen.queryAllByRole('tab')).toHaveLength(0);
        expect(screen.queryAllByRole('textbox')).toHaveLength(0);
        expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
        expect(screen.queryByText('email.messages.get')).not.toBeInTheDocument();
    });

    it('shows ungrouped tools and empty selections without hiding available groups', () => {
        render(<IntegrationEditor {...props({ record: { ...RECORD, operation_grants: [] }, catalogEntry: null })} />);
        expect(screen.getByRole('region', { name: 'Tools' })).toHaveTextContent('No tools selected');
        expect(screen.getByText('0 tools selected for this integration.')).toBeInTheDocument();
    });

    it('labels multiple tool groups without repeating their counts', () => {
        render(<IntegrationEditor {...props({ catalogEntry: { ...ENTRY, operation_groups: [
            { id: 'read', title: 'Reading', operation_ids: ['email.messages.get'] },
            { id: 'write', title: 'Writing', operation_ids: ['email.messages.send'] },
        ] } })} />);
        expect(screen.getByRole('heading', { name: 'Reading' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Writing' })).toBeInTheDocument();
        expect(screen.getAllByText(/1 tool selected/)).toHaveLength(1);
        expect(screen.queryByText('0 tools selected')).not.toBeInTheDocument();
    });

    it('opens the shared picker, searches, collapses groups and saves only grants', async () => {
        const p = props();
        render(<IntegrationEditor {...p} />);
        openTools();
        expect(p.onClearSaveError).toHaveBeenCalledOnce();
        const toggle = screen.getByRole('button', { name: 'Email 1 of 2' });
        fireEvent.click(toggle);
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        fireEvent.change(screen.getByRole('searchbox', { name: 'Search tools' }), { target: { value: 'Send' } });
        expect(screen.getByTestId('integration-tool-email.messages.send')).toBeVisible();
        fireEvent.click(screen.getByTestId('integration-tool-email.messages.send'));
        expect(screen.getByText('1 unsaved change')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(p.onSave).toHaveBeenCalledWith({ operation_grants: ['email.messages.get', 'email.messages.send'] });
    });

    it('cancels tool drafts and starts the next edit from saved selections', () => {
        const p = props();
        render(<IntegrationEditor {...p} />);
        openTools();
        fireEvent.click(screen.getByTestId('integration-tool-email.messages.send'));
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
        openTools();
        expect(screen.getByTestId('integration-tool-email.messages.send')).not.toBeChecked();
        expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
        expect(p.onSave).not.toHaveBeenCalled();
    });

    it('renames with a trimmed label-only payload and rejects blank or unchanged names', async () => {
        const p = props();
        render(<IntegrationEditor {...p} />);
        openRename();
        const input = screen.getByRole('textbox', { name: 'Name' });
        expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
        fireEvent.change(input, { target: { value: '  ' } });
        expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled();
        fireEvent.change(input, { target: { value: '  Renamed mail  ' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
        expect(p.onSave).toHaveBeenCalledWith({ label: 'Renamed mail' });
    });

    it('retains the draft on failed saves and allows retry', async () => {
        const p = props({ onSave: vi.fn().mockResolvedValue(false) });
        const { rerender } = render(<IntegrationEditor {...p} />);
        openRename();
        fireEvent.change(screen.getByRole('textbox', { name: 'Name' }), { target: { value: 'Retry me' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
        await waitFor(() => expect(p.onSave).toHaveBeenCalledOnce());
        rerender(<IntegrationEditor {...p} saveError="Temporary outage" />);
        expect(within(screen.getByRole('dialog')).getByRole('alert')).toHaveTextContent('Temporary outage');
        expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Retry me');
        p.onSave.mockResolvedValue(true);
        fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
        await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    });

    it('blocks all mutation and dismissal while saving', () => {
        const p = props();
        const { rerender } = render(<IntegrationEditor {...p} />);
        openSettings();
        openTools();
        fireEvent.click(screen.getByTestId('integration-tool-email.messages.send'));
        rerender(<IntegrationEditor {...p} saving />);
        for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).toBeDisabled();
        for (const name of ['Select all', 'Deselect all', 'Cancel', 'Close', 'Rename', 'Update app password', 'Remove integration…']) {
            expect(screen.getByRole('button', { name, exact: true })).toBeDisabled();
        }
        expect(screen.getByRole('button', { name: 'Saving…' })).toHaveAttribute('aria-busy', 'true');
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(p.onSave).not.toHaveBeenCalled();
    });

    it('shows slow-save feedback only during the current save and clears the timer', () => {
        vi.useFakeTimers();
        const p = props();
        const { rerender, unmount } = render(<IntegrationEditor {...p} />);
        openTools();
        rerender(<IntegrationEditor {...p} saving />);
        act(() => vi.advanceTimersByTime(3000));
        expect(screen.getByRole('alert')).toHaveTextContent('Still saving');
        rerender(<IntegrationEditor {...p} saving={false} />);
        expect(screen.queryByText(/Still saving/)).not.toBeInTheDocument();
        rerender(<IntegrationEditor {...p} saving />);
        unmount();
        expect(vi.getTimerCount()).toBe(0);
    });

    it('resynchronizes selections when authoritative grants change', () => {
        const p = props();
        const { rerender } = render(<IntegrationEditor {...p} />);
        openTools();
        rerender(<IntegrationEditor {...p} record={{ ...RECORD, operation_grants: [] }} />);
        expect(screen.getByTestId('integration-tool-email.messages.get')).not.toBeChecked();
        expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    });

    it.each([
        ['google_workspace', 'Sign in again'], ['icloud', 'Update app password'],
        ['gmail', 'Update app password'], ['http', 'Update token'], ['test', 'Update test credential'],
    ])('uses a service-specific credential action for %s', (slug, action) => {
        const p = props({ record: { ...RECORD, slug } });
        render(<IntegrationEditor {...p} />);
        openSettings();
        fireEvent.click(screen.getByRole('button', { name: action }));
        expect(p.onReconnect).toHaveBeenCalledOnce();
    });

    it.each(['broken', 'auth_failed', 'unknown'])('shows recovery without a duplicate status for %s connections', (state) => {
        const p = props({ record: { ...RECORD, state } });
        render(<IntegrationEditor {...p} />);
        const alert = screen.getByRole('alert');
        const repair = within(alert).getByRole('button', { name: 'Update app password' });
        expect(repair).toBeVisible();
        expect(screen.getByText('Connection settings', { exact: true }).closest('details')).not.toHaveAttribute('open');
        fireEvent.click(repair);
        expect(p.onReconnect).toHaveBeenCalledOnce();
        openSettings();
        expect(screen.getByRole('button', { name: 'Change tools' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Rename' })).toBeEnabled();
        expect(screen.getByTestId(`integrations-reconnect-${RECORD.id}`)).toBeEnabled();
        expect(screen.getByRole('alert')).toHaveTextContent('This integration needs attention');
        expect(screen.queryByTestId('integration-status')).not.toBeInTheDocument();
    });

    it.each([
        ['mcp', 'Sign in again'], ['slack', 'Sign in again'],
        ['google_workspace', 'Sign in again'], ['http', 'Update token'],
    ])('uses the existing %s recovery action without opening connection settings', (slug, action) => {
        const p = props({ record: { ...RECORD, slug, state: 'broken' } });
        render(<IntegrationEditor {...p} />);
        const alert = screen.getByRole('alert');
        expect(alert).toHaveTextContent(`${action} to restore access.`);
        fireEvent.click(within(alert).getByRole('button', { name: action }));
        expect(p.onReconnect).toHaveBeenCalledOnce();
        expect(p.onSave).not.toHaveBeenCalled();
        expect(p.onRemove).not.toHaveBeenCalled();
    });

    it('blocks repair while saving and clears the warning after recovery without changing selected tools', () => {
        const p = props({ record: { ...RECORD, slug: 'mcp', state: 'broken' }, saving: true });
        const { rerender } = render(<IntegrationEditor {...p} />);
        const repair = within(screen.getByRole('alert')).getByRole('button', { name: 'Sign in again' });
        expect(repair).toBeDisabled();
        fireEvent.click(repair);
        expect(p.onReconnect).not.toHaveBeenCalled();
        rerender(<IntegrationEditor {...p} saving={false} record={{ ...p.record, state: 'running' }} />);
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.queryByTestId(`integrations-repair-${RECORD.id}`)).not.toBeInTheDocument();
        expect(screen.getByRole('region', { name: 'Email' })).toHaveTextContent('Read email message');
        expect(screen.getByRole('button', { name: 'Change tools' })).toBeEnabled();
    });
});
