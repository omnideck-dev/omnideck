import { CONVERSATION_EVENT_TYPES as EVENT } from './eventTypes.js';

/**
 * Run work that should happen once when a canonical event arrives live.
 *
 * Restoring saved state never calls this function.
 */
export function runOneTimeEventActions(event, actions = {}) {
    if (!event?.type) return;

    if (event.type === EVENT.TOOL_CREATED) {
        actions.onToolCreated?.();
    }

    if (event.type === EVENT.AUDIO_PLAYBACK) {
        actions.onAudioPlayback?.({
            key: Date.now(),
            src: `data:${event.content_type};base64,${event.content}`,
        });
    }
}
