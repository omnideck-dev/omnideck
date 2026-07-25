import { APP_EFFECT_TYPES } from './appEffectTypes.js';

/**
 * Payload registry for application-wide, one-time effects.
 *
 * Keeping payloads in a type map gives dispatchers and subscribers one source
 * of truth while the runtime envelope stays uniform.
 */
export type AppEffectPayloads = {
    [APP_EFFECT_TYPES.PLAY_AUDIO_REQUESTED]: {
        audio: {
            key: string;
            src: string;
        };
    };
    [APP_EFFECT_TYPES.REFRESH_CUSTOM_TOOLS_REQUESTED]: null;
    [APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE]: {
        conversationId: string | null;
        agentId: string;
        agentName: string | null;
        resourceId: 'browser' | 'terminal';
    };
    [APP_EFFECT_TYPES.CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED]: {
        conversationId: string;
    };
    [APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE_REQUESTED]: {
        agentId: string;
        resourceId: 'browser' | 'terminal';
    };
    [APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED]: {
        appSlug: string;
    };
    [APP_EFFECT_TYPES.OPEN_ARTIFACT_REQUESTED]: {
        artifactId: string;
        conversationId: string | null;
    };
    [APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING]: {
        views: Array<Record<string, unknown> & {
            id: string;
            type: string;
        }>;
    };
    [APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED]: {
        actionId: string;
        view: Record<string, unknown> & {
            id: string;
            type: string;
        };
    };
};

export type AppEffectType = keyof AppEffectPayloads;

/** Bus metadata is transport context, never domain-owned payload data. */
export type AppEffectMeta = Readonly<{
    source?: string;
    correlationId?: string;
}>;

/** Canonical envelope; the mapped type preserves payload discrimination. */
export type AppEffect<Type extends AppEffectType = AppEffectType> = {
    [CurrentType in Type]: Readonly<{
        type: CurrentType;
        payload: AppEffectPayloads[CurrentType];
        meta?: AppEffectMeta;
    }>
}[Type];

export type AppEffectOfType<Type extends AppEffectType> = AppEffect<Type>;
