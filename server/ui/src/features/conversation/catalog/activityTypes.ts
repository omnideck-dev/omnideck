export type RunIdentity = { conversation_id: string; run_id: string };
export type RunActivityMessage = {
    type: 'snapshot' | 'started' | 'finished';
    runs: RunIdentity[];
};
export type ConversationActivityAction = RunActivityMessage | {
    type: 'visibility';
    conversationId: string | null;
};
export type ConversationActivityState = {
    running: Map<string, string>;
    finished: Set<string>;
    visibleConversationId: string | null;
};
