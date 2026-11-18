import { describe, expect, it } from 'vitest';
import { APP_EFFECT_TYPES } from '../../../app/appEffectTypes.js';
import { getConversationEventEffects } from '../conversationEventEffects.js';

function event(type, fields = {}) {
    return { id: `event-${type}`, type, ...fields };
}

describe('getConversationEventEffects', () => {
    it('maps tool creation to catalog invalidation', () => {
        expect(getConversationEventEffects(event('tool_created'))).toEqual([
            {
                type: APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS_REQUESTED,
                payload: null,
            },
        ]);
    });

    it('maps a finished set_theme call to a theme refresh', () => {
        expect(getConversationEventEffects(event('tool_result', {
            tool_name: 'set_theme',
            tool_call_id: 'call-1',
            content: '{"status": "ok"}',
        }))).toEqual([
            {
                type: APP_EFFECT_TYPES.REFRESH_THEME_REQUESTED,
                payload: null,
            },
        ]);
    });

    it('also refreshes the theme when set_theme reports an error, since the check is cheap', () => {
        expect(getConversationEventEffects(event('tool_result', {
            tool_name: 'set_theme',
            content: '{"status": "error"}',
        }))).toHaveLength(1);
    });

    it('leaves the results of other tools alone, including a read of the theme', () => {
        for (const tool_name of ['get_theme', 'remember', 'run_bash_cmd']) {
            expect(getConversationEventEffects(event('tool_result', { tool_name }))).toEqual([]);
        }
    });

    it('builds a playable data URL for audio events', () => {
        expect(getConversationEventEffects(event('audio_playback', {
            content_type: 'audio/wav', content: 'base64-audio',
        }))).toEqual([{
            type: APP_EFFECT_TYPES.PLAY_AUDIO_REQUESTED,
            payload: {
                audio: {
                    key: 'event-audio_playback',
                    src: 'data:audio/wav;base64,base64-audio',
                },
            },
        }]);
    });

    it('requests background Browser and Terminal Views for root events', () => {
        expect(getConversationEventEffects(event('browser_screenshot', {
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
            agent_name: 'Omnideck',
            depth: 0,
            screenshot: 'base64-image',
        }))).toEqual([{
            type: APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE,
            payload: {
                conversationId: 'conversation-1',
                agentId: 'root-1',
                agentName: 'Omnideck',
                resourceId: 'browser',
            },
        }]);
        expect(getConversationEventEffects(event('terminal_output', {
            conversation_id: 'conversation-1',
            agent_id: 'root-1',
            agent_name: 'Omnideck',
            depth: 0,
        }))).toEqual([{
            type: APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE,
            payload: {
                conversationId: 'conversation-1',
                agentId: 'root-1',
                agentName: 'Omnideck',
                resourceId: 'terminal',
            },
        }]);
    });

    it('does not request Views for sub-agent Workspace events', () => {
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
