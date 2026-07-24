import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
    AppEffectsProvider,
    useAppEffectDispatch,
    useAppEffectSubscription,
} from '../AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../appEffectTypes.js';

describe('AppEffectsProvider', () => {
    it('delivers one typed effect to every current subscriber', () => {
        const first = vi.fn();
        const second = vi.fn();
        let dispatch;

        function Harness() {
            dispatch = useAppEffectDispatch();
            useAppEffectSubscription(APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS, first);
            useAppEffectSubscription(APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS, second);
            return null;
        }

        render(
            <AppEffectsProvider>
                <Harness />
            </AppEffectsProvider>,
        );

        const effect = { type: APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS };
        act(() => dispatch(effect));

        expect(first).toHaveBeenCalledWith(effect);
        expect(second).toHaveBeenCalledWith(effect);
    });

    it('isolates effect types', () => {
        const playAudio = vi.fn();
        let dispatch;

        function Harness() {
            dispatch = useAppEffectDispatch();
            useAppEffectSubscription(APP_EFFECT_TYPES.PLAY_AUDIO, playAudio);
            return null;
        }

        render(
            <AppEffectsProvider>
                <Harness />
            </AppEffectsProvider>,
        );

        act(() => dispatch({ type: APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS }));

        expect(playAudio).not.toHaveBeenCalled();
    });
});
