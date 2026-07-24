import { describe, expect, it } from 'vitest';
import { APP_EFFECT_TYPES } from '../../../app/appEffectTypes.js';
import { getConversationEventEffects } from '../conversationEventEffects.js';

function event(type, fields = {}) {
    return { id: `event-${type}`, type, ...fields };
}

describe('getConversationEventEffects', () => {
    it('maps tool creation to catalog invalidation', () => {
        expect(getConversationEventEffects(event('tool_created'))).toEqual([
            { type: APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS },
        ]);
    });

    it('builds a playable data URL for audio events', () => {
        expect(getConversationEventEffects(event('audio_playback', {
            content_type: 'audio/wav', content: 'base64-audio',
        }))).toEqual([{
            type: APP_EFFECT_TYPES.PLAY_AUDIO,
            audio: {
                key: 'event-audio_playback',
                src: 'data:audio/wav;base64,base64-audio',
            },
        }]);
    });

    it('requests background Browser and Terminal surfaces for root events', () => {
        expect(getConversationEventEffects(event('browser_screenshot', {
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
            agent_name: 'Omnideck',
            depth: 0,
            screenshot: 'base64-image',
        }))).toEqual([{
            type: APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
            conversationId: 'conversation-1',
            agentId: 'root-1',
            agentName: 'Omnideck',
            resourceId: 'browser',
        }]);
        expect(getConversationEventEffects(event('terminal_output', {
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
            agent_name: 'Omnideck',
            depth: 0,
        }))).toEqual([{
            type: APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
            conversationId: 'conversation-1',
            agentId: 'root-1',
            agentName: 'Omnideck',
            resourceId: 'terminal',
        }]);
    });

    it('does not request surfaces for sub-agent execution events', () => {
        expect(getConversationEventEffects(event('browser_screenshot', {
            conversation_id: 'conversation-1',
            agent_id: 'child-1',
            agent_name: 'Researcher',
            depth: 1,
            screenshot: 'base64-image',
        }))).toEqual([]);
        expect(getConversationEventEffects(event('terminal_output', {
            conversation_id: 'conversation-1',
            agent_id: 'child-1',
            depth: 1,
        }))).toEqual([]);
    });

    it('ignores state and missing events', () => {
        expect(getConversationEventEffects(event('agent_started'))).toEqual([]);
        expect(getConversationEventEffects(null)).toEqual([]);
    });
});
