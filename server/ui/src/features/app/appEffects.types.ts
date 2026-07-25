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
        type: typeof APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE;
        conversationId: string | null;
        agentId: string;
        agentName: string | null;
        resourceId: 'browser' | 'terminal';
    }
    | {
        type: typeof APP_EFFECT_TYPES.CLOSE_CONVERSATION_WORKSPACE_VIEWS;
        conversationId: string;
    }
    | {
        type: typeof APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE;
        agentId: string;
        resourceId: 'browser' | 'terminal';
    }
    | {
        type: typeof APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING;
        views: Array<Record<string, unknown> & {
            id: string;
            type: string;
        }>;
    }
    | {
        type: typeof APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED;
        actionId: string;
        view: Record<string, unknown> & {
            id: string;
            type: string;
        };
    };

export type AppEffectType = AppEffect['type'];
export type AppEffectOfType<Type extends AppEffectType> = Extract<AppEffect, { type: Type }>;
