import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import BrowserChrome from '../BrowserChrome.jsx';

describe('BrowserChrome', () => {
    it('omits takeover entirely when the Browser does not own a session', () => {
        render(
            <BrowserChrome
                url="https://example.com"
                title="Example"
                control={undefined}
            />,
        );

        expect(screen.queryByTestId('browser-take-control')).toBeNull();
    });

    it('shows the server reason and disables takeover after rejection', () => {
        render(
            <BrowserChrome
                url="https://example.com"
                title="Example"
                control={{
                    canControl: false,
                    error: 'no_active_browser',
                    toggleEngage: vi.fn(),
                }}
            />,
        );

        expect(screen.getByTestId('browser-control-error')).toHaveTextContent(
            'no_active_browser',
        );
        expect(screen.getByTestId('browser-take-control')).toBeDisabled();
    });
});
