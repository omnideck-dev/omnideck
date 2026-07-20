import { describe, expect, it, vi } from 'vitest';
import { runOneTimeEventActions } from '../oneTimeEventActions.js';

function event(type, fields = {}) {
    return { id: `event-${type}`, type, ...fields };
}

describe('runOneTimeEventActions', () => {
    it('refreshes tools when a tool is created', () => {
        const onToolCreated = vi.fn();

        runOneTimeEventActions(event('tool_created'), { onToolCreated });

        expect(onToolCreated).toHaveBeenCalledTimes(1);
    });

    it('builds a playable data URL for audio events', () => {
        const onAudioPlayback = vi.fn();

        runOneTimeEventActions(event('audio_playback', {
            content_type: 'audio/wav', content: 'base64-audio',
        }), { onAudioPlayback });

        expect(onAudioPlayback).toHaveBeenCalledWith({
            key: expect.any(Number),
            src: 'data:audio/wav;base64,base64-audio',
        });
    });

    it('ignores state events, missing events, and absent actions', () => {
        const actions = {
            onToolCreated: vi.fn(),
            onAudioPlayback: vi.fn(),
        };

        runOneTimeEventActions(event('agent_started'), actions);
        runOneTimeEventActions(null, actions);

        expect(actions.onToolCreated).not.toHaveBeenCalled();
        expect(actions.onAudioPlayback).not.toHaveBeenCalled();
        expect(() => runOneTimeEventActions(event('tool_created'))).not.toThrow();
    });
});
