import { useCallback, useRef, useState } from 'react';
import {
    useAppEffectSubscription,
} from '../features/app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../features/app/appEffectTypes.js';
import styles from './AudioPlayer.module.css';

/** Plays audio requested through the application effect channel. */
function AudioPlayer() {
    const audioRef = useRef(null);
    const [audio, setAudio] = useState(null);
    const [paused, setPaused] = useState(false);

    const receiveAudio = useCallback((effect) => {
        setAudio(effect.audio);
        setPaused(false);
    }, []);
    useAppEffectSubscription(APP_EFFECT_TYPES.PLAY_AUDIO, receiveAudio);

    if (!audio) return null;

    const handleToggle = () => {
        const el = audioRef.current;
        if (!el) return;
        if (el.paused) {
            el.play();
            setPaused(false);
        } else {
            el.pause();
            setPaused(true);
        }
    };

    return (
        <>
            <audio
                ref={audioRef}
                key={audio.key}
                src={audio.src}
                autoPlay
                onEnded={() => setAudio(null)}
                data-testid="audio-player-media"
            />
            <button
                className={`${styles.button} ${paused ? styles.paused : ''}`}
                onClick={handleToggle}
                title={paused ? 'Resume' : 'Pause'}
                aria-label={paused ? 'Resume audio' : 'Pause audio'}
                data-testid="audio-player"
            >
                <span className={styles.bar} />
                <span className={styles.bar} />
                <span className={styles.bar} />
                <span className={styles.bar} />
            </button>
        </>
    );
}

export default AudioPlayer;
