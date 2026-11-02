import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import IntegrationStatus from '../components/IntegrationStatus.jsx';

describe('IntegrationStatus', () => {
    it('shows Connected with a decorative checkmark', () => {
        render(<IntegrationStatus state="running" />);
        const status = screen.getByTestId('integration-status');
        expect(status).toHaveTextContent('Connected');
        expect(status.querySelector('.bi-check-lg')).toHaveAttribute('aria-hidden', 'true');
    });

    it.each([
        ['auth_failed', 'auth failed'],
        ['broken', 'not running'],
        ['unknown', 'not running'],
    ])('does not present %s as connected', (state, label) => {
        render(<IntegrationStatus state={state} />);
        expect(screen.getByTestId('integration-status')).toHaveTextContent(label);
        expect(screen.queryByText('Connected')).not.toBeInTheDocument();
    });
});
