import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import OperationPicker from '../components/OperationPicker.jsx';

const OPERATIONS = [
    { id: 'mail.list', title: 'List messages', description: 'List recent messages.' },
    { id: 'mail.send', title: 'Send message', description: 'Send a new message.' },
    { id: 'calendar.list', title: 'List events', description: 'List calendar events.' },
];
const GROUPS = [
    { id: 'mail', title: 'Email', operation_ids: ['mail.list', 'mail.send'] },
    { id: 'calendar', title: 'Calendar', operation_ids: ['calendar.list'] },
];

describe('OperationPicker', () => {
    it('allows collapsing search results and restores the unfiltered expansion state', () => {
        render(<OperationPicker operations={OPERATIONS} groups={GROUPS} selectedIds={[]} collapsible />);
        const toggle = () => screen.getByRole('button', { name: 'Email 0 of 2' });
        fireEvent.click(toggle());
        expect(screen.getByTestId('integration-tool-mail.list')).not.toBeVisible();

        const search = screen.getByRole('searchbox', { name: 'Search tools' });
        fireEvent.change(search, { target: { value: 'message' } });
        expect(toggle()).toHaveAttribute('aria-expanded', 'true');
        fireEvent.click(toggle());
        expect(toggle()).toHaveAttribute('aria-expanded', 'false');
        expect(screen.getByTestId('integration-tool-mail.list')).not.toBeVisible();
        fireEvent.click(toggle());
        expect(screen.getByTestId('integration-tool-mail.list')).toBeVisible();

        fireEvent.change(search, { target: { value: '' } });
        expect(toggle()).toHaveAttribute('aria-expanded', 'false');
        expect(screen.getByTestId('integration-tool-mail.list')).not.toBeVisible();
    });

    it.each([false, true])('uses the same selection language when collapsible=%s', collapsible => {
        render(<OperationPicker operations={OPERATIONS} selectedIds={[]} collapsible={collapsible} />);
        expect(screen.getByRole('button', { name: 'Select all', exact: true })).toBeVisible();
        expect(screen.getByRole('button', { name: 'Deselect all', exact: true })).toBeVisible();
        expect(screen.getByText('0 of 3 selected')).toBeVisible();
    });

    it('labels ungrouped selection without repeating tools', () => {
        render(<OperationPicker operations={OPERATIONS} selectedIds={[]} collapsible />);

        expect(screen.getByRole('checkbox', { name: 'Select all in Tools' })).toBeInTheDocument();
    });

    it('starts new operations off and emits explicit operation IDs', () => {
        const onChange = vi.fn();
        render(
            <OperationPicker
                operations={OPERATIONS}
                groups={GROUPS}
                selectedIds={['mail.list']}
                onChange={onChange}
            />,
        );

        expect(screen.getByTestId('integration-tool-mail.list')).toBeChecked();
        expect(screen.getByTestId('integration-tool-mail.send')).not.toBeChecked();
        expect(screen.getByTestId('integration-tool-calendar.list')).not.toBeChecked();

        fireEvent.click(screen.getByTestId('integration-tool-mail.send'));
        expect(onChange).toHaveBeenLastCalledWith(['mail.list', 'mail.send']);
    });

    it('supports catalog groups, all, clear, and search without changing the contract', () => {
        const onChange = vi.fn();
        const { rerender } = render(
            <OperationPicker
                operations={OPERATIONS}
                groups={GROUPS}
                selectedIds={[]}
                onChange={onChange}
            />,
        );

        fireEvent.click(screen.getByTestId('integration-tool-group-mail'));
        expect(onChange).toHaveBeenLastCalledWith(['mail.list', 'mail.send']);

        rerender(
            <OperationPicker
                operations={OPERATIONS}
                groups={GROUPS}
                selectedIds={['mail.list', 'mail.send']}
                onChange={onChange}
            />,
        );
        fireEvent.click(screen.getByTestId('integration-tools-enable-all'));
        expect(onChange).toHaveBeenLastCalledWith(['calendar.list', 'mail.list', 'mail.send']);
        fireEvent.click(screen.getByTestId('integration-tools-clear'));
        expect(onChange).toHaveBeenLastCalledWith([]);

        fireEvent.change(screen.getByTestId('integration-tools-search'), {
            target: { value: 'calendar' },
        });
        expect(screen.getByText('List events')).toBeInTheDocument();
        expect(screen.queryByText('Send message')).not.toBeInTheDocument();
    });

    it('deduplicates overlapping groups and tolerates optional descriptions', () => {
        render(
            <OperationPicker
                operations={[
                    { id: 'mail.list', title: 'List messages' },
                    { id: 'mail.send', title: 'Send message', description: 'Send.' },
                    null,
                    { title: 'Missing ID' },
                ]}
                groups={[
                    { id: 'first', title: 'First', operation_ids: ['mail.list'] },
                    { id: 'second', title: 'Second', operation_ids: ['mail.list', 'mail.send'] },
                ]}
                selectedIds={['removed.operation']}
                onChange={vi.fn()}
            />,
        );

        expect(screen.getAllByText('List messages')).toHaveLength(1);
        expect(screen.getByText('0 of 2 selected')).toBeInTheDocument();
        expect(screen.getByRole('checkbox', { name: 'First 0 of 1' })).toHaveAttribute(
            'aria-checked',
            'false',
        );
    });
});
