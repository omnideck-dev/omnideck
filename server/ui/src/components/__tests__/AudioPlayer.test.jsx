import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AudioPlayer from '../AudioPlayer.jsx';
import {
    AppEffectsProvider,
    useAppEffectDispatch,
} from '../../features/app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../features/app/appEffectTypes.js';

describe('AudioPlayer', () => {
    it('plays incoming audio effects and clears itself when playback ends', () => {
        let dispatchAppEffect;

        function EffectControl() {
            dispatchAppEffect = useAppEffectDispatch();
            return null;
        }

        render(
            <AppEffectsProvider>
                <EffectControl />
                <AudioPlayer />
            </AppEffectsProvider>,
        );
        expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument();

        act(() => dispatchAppEffect({
            type: APP_EFFECT_TYPES.PLAY_AUDIO,
            audio: {
                key: 'audio-1',
                src: 'data:audio/wav;base64,content',
            },
        }));

        expect(screen.getByTestId('audio-player-media')).toHaveAttribute(
            'src',
            'data:audio/wav;base64,content',
        );
        expect(screen.getByTestId('audio-player')).toHaveAttribute('title', 'Pause');

        fireEvent.ended(screen.getByTestId('audio-player-media'));
        expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument();
    });
});
