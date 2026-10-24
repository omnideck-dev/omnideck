import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import IntegrationRowSummary from '../components/IntegrationRowSummary.jsx';

describe('IntegrationRowSummary', () => {
    it.each([
        [[], 'No tools selected'],
        [['read'], '1 tool selected'],
        [['read', 'write'], '2 tools selected'],
    ])('keeps running connections quiet with grants %j', (grants, label) => {
        render(<IntegrationRowSummary record={{ state: 'running', slug: 'mcp', operation_grants: grants }} />);
        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.queryByText('Connected')).not.toBeInTheDocument();
        expect(screen.queryByTestId('integration-issue')).not.toBeInTheDocument();
    });

    it.each([
        ['auth_failed', 'mcp', 'Sign in again'],
        ['auth_failed', 'slack', 'Sign in again'],
        ['auth_failed', 'google_workspace', 'Sign in again'],
        ['auth_failed', 'icloud', 'Update app password'],
        ['auth_failed', 'http', 'Update token'],
        ['broken', 'mcp', 'Connection unavailable'],
        ['unknown', 'mcp', 'Couldn’t check connection'],
        [undefined, 'mcp', 'Couldn’t check connection'],
    ])('replaces the count with recovery text for %s / %s', (state, slug, label) => {
        render(<IntegrationRowSummary record={{ state, slug, operation_grants: ['read'] }} />);
        const issue = screen.getByTestId('integration-issue');
        expect(issue).toHaveTextContent(label);
        expect(issue.querySelector('.bi-exclamation-triangle')).toHaveAttribute('aria-hidden', 'true');
        expect(screen.queryByText('1 tool selected')).not.toBeInTheDocument();
    });
});
