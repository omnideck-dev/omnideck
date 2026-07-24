import { CONVERSATION_EVENT_TYPES as EVENT } from './eventTypes.js';
import { isRootAgentEvent } from './eventTypes.js';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';

/**
 * Map a conversation event to application-wide one-time effects. Delivery is
 * performed elsewhere so feature owners can subscribe independently of where
 * the event originated.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {Array<import('../../app/appEffects.types').AppEffect>}
 */
export function getConversationEventEffects(event) {
    switch (event?.type) {
        case EVENT.BROWSER_SCREENSHOT:
            if (!isRootAgentEvent(event) || !event.agent_id || !event.screenshot) return [];
            return [{
                type: APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
                conversationId: event.conversation_id || null,
                agentId: event.agent_id,
                agentName: event.agent_name || null,
                resourceId: 'browser',
            }];
        case EVENT.TERMINAL_OUTPUT:
            if (!isRootAgentEvent(event) || !event.agent_id) return [];
            return [{
                type: APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
                conversationId: event.conversation_id || null,
                agentId: event.agent_id,
                agentName: event.agent_name || null,
                resourceId: 'terminal',
            }];
        case EVENT.TOOL_CREATED:
            return [{ type: APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS }];
        case EVENT.AUDIO_PLAYBACK:
            return [{
                type: APP_EFFECT_TYPES.PLAY_AUDIO,
                audio: {
                    key: event.id,
                    src: `data:${event.content_type};base64,${event.content}`,
                },
            }];
        default:
            return [];
    }
}
