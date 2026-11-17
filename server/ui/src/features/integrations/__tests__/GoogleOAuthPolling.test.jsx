import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import GoogleOAuthConnection from '../setup/connection-adapters/GoogleOAuthConnection.jsx';

const response = body => Promise.resolve({ ok: true, json: async () => body });

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it.each(['pending', 'committing'])('shows and clears a failed poll while Google authorization is %s', async status => {
    vi.useFakeTimers();
    vi.spyOn(window, 'open').mockReturnValue(null);
    const connected = vi.fn();
    const poll = vi.fn()
        .mockRejectedValueOnce(new Error('Network unavailable'))
        .mockImplementationOnce(() => response({ status }))
        .mockImplementationOnce(() => response({ status: 'success', integration_id: 'google_saved' }));
    globalThis.fetch = vi.fn(url => url.endsWith('/start')
        ? response({ state: 'google_attempt', status, authorize_url: 'https://accounts.example/authorize' })
        : poll());
    render(<GoogleOAuthConnection entry={{ id: 'google_workspace', title: 'Google' }}
        onBack={vi.fn()} onConnectedId={connected} />);
    fireEvent.change(screen.getByTestId('wizard-email'), { target: { value: 'demo@example.test' } });
    fireEvent.change(screen.getByTestId('oauth-client-id'), { target: { value: 'client' } });
    fireEvent.change(screen.getByTestId('oauth-client-secret'), { target: { value: 'secret' } });
    await act(async () => { fireEvent.click(screen.getByTestId('oauth-authorize')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByText('Checking sign-in')).toBeInTheDocument();
    expect(screen.getByText('Network unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reopen sign-in' }).disabled).toBe(status === 'committing');
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.queryByText('Network unavailable')).not.toBeInTheDocument();
    expect(connected).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(connected).toHaveBeenCalledWith('google_saved');
    expect(globalThis.fetch.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(1);
});
