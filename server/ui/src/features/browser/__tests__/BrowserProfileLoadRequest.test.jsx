import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { AppEffectsProvider, useAppEffectDispatch } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import {
    BrowserProfileLoadRequestProvider,
    useBrowserProfileLoadRequest,
} from '../BrowserProfileLoadRequest.jsx';

function Harness() {
    const dispatch = useAppEffectDispatch();
    const { request, clearRequest } = useBrowserProfileLoadRequest();
    return (
        <>
            <button
                type="button"
                onClick={() => dispatch({
                    type: APP_EFFECT_TYPES.OPEN_BROWSER_PROFILE_REQUESTED,
                    payload: { profileId: 'work', profileName: 'Work' },
                })}
            >
                Request profile
            </button>
            <button type="button" onClick={clearRequest}>Clear request</button>
            <span>{request?.profileName || 'No request'}</span>
        </>
    );
}

describe('BrowserProfileLoadRequestProvider', () => {
    it('holds a one-time Browser profile request only until its owner consumes it', async () => {
        const user = userEvent.setup();
        render(
            <AppEffectsProvider>
                <BrowserProfileLoadRequestProvider>
                    <Harness />
                </BrowserProfileLoadRequestProvider>
            </AppEffectsProvider>,
        );

        await act(async () => {
            await user.click(screen.getByRole('button', { name: 'Request profile' }));
        });
        expect(screen.getByText('Work')).toBeInTheDocument();

        await act(async () => {
            await user.click(screen.getByRole('button', { name: 'Clear request' }));
        });
        expect(screen.getByText('No request')).toBeInTheDocument();
    });
});
