import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import IntegrationsTab from '../IntegrationsTab.jsx';

vi.mock('../hooks/useIntegrations.js', () => ({ default: () => ({
    connections: [{ id: 'personal', slug: 'gmail', label: 'Personal', operation_grants: [] }, { id: 'work', slug: 'gmail', label: 'Work', operation_grants: [] }],
    catalog: [], loading: false, refresh: vi.fn(),
}) }));
vi.mock('../editor/IntegrationEditor.jsx', () => ({ default: ({ record }) => <div data-testid="editor">{record.id}</div> }));

describe('Integration selection links', () => {
    it('selects the requested account and responds to a new target', () => {
        const { rerender } = render(<IntegrationsTab initialConnectionId="work" />);
        expect(screen.getByTestId('editor')).toHaveTextContent('work');
        rerender(<IntegrationsTab initialConnectionId="personal" />);
        expect(screen.getByTestId('editor')).toHaveTextContent('personal');
    });
    it('does not substitute another account when a linked connection is gone', async () => {
        const user = userEvent.setup();
        render(<IntegrationsTab initialConnectionId="deleted" />);
        expect(screen.queryByTestId('editor')).not.toBeInTheDocument();
        expect(screen.getByRole('alert')).toHaveTextContent('Integration no longer available');
        await user.click(screen.getByTestId('integrations-row-work'));
        expect(screen.getByTestId('editor')).toHaveTextContent('work');
    });
    it('reopens the requested account after locally selecting a different one', async () => {
        const user = userEvent.setup();
        const { rerender } = render(<IntegrationsTab initialConnectionId="work" selectionRequest={{}} />);
        await user.click(screen.getByTestId('integrations-row-personal'));
        expect(screen.getByTestId('editor')).toHaveTextContent('personal');
        rerender(<IntegrationsTab initialConnectionId="work" selectionRequest={{}} />);
        expect(screen.getByTestId('editor')).toHaveTextContent('work');
    });
});
