/**
 * Event names from the conversation stream and persisted event log.
 *
 * JavaScript has no native string enum, so this frozen object gives event
 * producers and consumers one vocabulary without changing the wire format.
 */
export const CONVERSATION_EVENT_TYPES = Object.freeze(/** @type {const} */ ({
    CONTENT: 'content',
    TURN_END: 'turn_end',
    TOOL_CALL: 'tool_call',
    SPAWN_REQUESTED: 'spawn_requested',
    BROWSER_SCREENSHOT: 'browser_screenshot',
    FILE_OUTPUT: 'file_output',
    TOOL_CREATED: 'tool_created',
    AUDIO_PLAYBACK: 'audio_playback',
    TERMINAL_OUTPUT: 'terminal_output',
    DESKTOP_ACTIVE: 'desktop_active',
    CONTEXT_USAGE: 'context_usage',
    GENERATION_PREVIEW: 'generation_preview',
    AGENT_STARTED: 'agent_started',
    AGENT_COMPLETED: 'agent_completed',
    ERROR: 'error',
    USER_MESSAGE: 'user_message',
    ITERATION: 'iteration',
    TOOL_RESULT: 'tool_result',
    COMPACTION: 'compaction',
}));

/** Item names understood by the chat transcript's Turn renderer. */
export const TRANSCRIPT_ITEM_KINDS = Object.freeze(/** @type {const} */ ({
    USER_PROMPT: 'user_prompt',
    ITERATION: 'iteration',
    TOOL_RESULT: 'tool_result',
    FILE_OUTPUT: 'file_output',
    COMPACTION: 'compaction',
    SPAWN_REQUESTED: 'spawn_requested',
    ERROR: 'error',
}));

/**
 * Agent lifecycle events identify a sub-agent with `parent_agent_id`; other
 * events identify it with `depth > 0`. Keep that protocol detail here so
 * transcript code does not alternate between the two tests.
 */
/** @param {{parent_agent_id?: string|null, depth?: number|null}|null|undefined} event */
export function isSubAgentEvent(event) {
    if (!event) return false;
    return Boolean(event.parent_agent_id) || (event.depth ?? 0) > 0;
}

/** @param {{parent_agent_id?: string|null, depth?: number|null}|null|undefined} event */
export function isRootAgentEvent(event) {
    return Boolean(event) && !isSubAgentEvent(event);
}
