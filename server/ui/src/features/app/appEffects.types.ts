import { APP_EFFECT_TYPES } from './appEffectTypes.js';

/** Application-wide effects currently understood by feature owners. */
export type AppEffect =
    | {
        type: typeof APP_EFFECT_TYPES.PLAY_AUDIO;
        audio: {
            key: string;
            src: string;
        };
    }
    | { type: typeof APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS }
    | {
        type: typeof APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE;
        conversationId: string | null;
        agentId: string;
        agentName: string | null;
        resourceId: 'browser' | 'terminal';
    }
    | {
        type: typeof APP_EFFECT_TYPES.CLOSE_CONVERSATION_EXECUTION_VIEWS;
        conversationId: string;
    };

export type AppEffectType = AppEffect['type'];
export type AppEffectOfType<Type extends AppEffectType> = Extract<AppEffect, { type: Type }>;
