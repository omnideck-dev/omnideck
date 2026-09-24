import type {
    AgentCompletedPayload,
    CompactionStats,
    ConversationEvent,
    FileOutputPayload,
    GenerationPreviewPayload,
} from './conversationEvents.generated';

export type AgentActivityEntry =
    | { type: 'thinking'; thinking: string; timestamp: number }
    | { type: 'content'; content: string; timestamp: number }
    | { type: 'tool_call'; name: string; arguments: Record<string, unknown> | null; timestamp: number }
    | { type: 'spawn_requested'; correlationId: string; timestamp: number }
    | ({ type: 'file_output'; timestamp: number } & Omit<FileOutputPayload, 'type'>)
    | {
        type: 'compaction';
        stats: CompactionStats | null;
        summaryText: string | null;
        userIntentSummary: string | null;
        timestamp: number;
    }
    | { type: 'error'; message: string; timestamp: number };

export type AgentAction =
    | {
        type: 'AGENT_STARTED';
        agentId: string;
        agentName: string;
        parentAgentId: string | null;
        instruction: string | null;
        correlationId: string | null;
        timestamp: number;
    }
    | {
        type: 'AGENT_COMPLETED';
        agentId: string;
        status: AgentCompletedPayload['status'];
        timestamp: number;
    }
    | {
        type: 'UPDATE_ITERATION';
        agentId: string;
        iteration: number | null;
        maxIterations: number | null;
        contextUsage: {
            context_used: number;
            context_limit: number;
            fill_ratio: number;
            compaction_threshold: number;
        };
    }
    | {
        type: 'APPEND_STREAM_CHUNK';
        agentId: string;
        content: string | null;
        thinking: string | null;
    }
    | {
        type: 'FINALIZE_AGENT_ITERATION';
        agentId: string;
        content: string | null;
        thinking: string | null;
        toolCalls: Array<{
            name: string;
            arguments: Record<string, unknown> | null;
        }>;
        timestamp: number;
    }
    | { type: 'APPEND_ACTIVITY'; agentId: string; entry: AgentActivityEntry };

export type WorkspaceAction =
    | { type: 'WORKSPACE_AGENT_STARTED'; agentId: string; parentAgentId: string | null }
    | {
        type: 'UPDATE_BROWSER_SNAPSHOT';
        agentId: string | null;
        snapshot: {
            url: string;
            title: string;
            screenshot: string | null;
            tabId: number | null;
            openTabIds: Array<number> | null;
            agentId: string | null;
        };
    }
    | {
        type: 'UPDATE_TERMINAL';
        agentId: string | null;
        event: Record<string, unknown> & { agentId: string | null };
    }
    | { type: 'UPDATE_DESKTOP_ACTIVE'; agentId: string | null }
    | {
        type: 'UPDATE_GENERATION_PREVIEW';
        agentId: string | null;
        preview: GenerationPreviewPayload & { agentId: string | null };
    }
    | {
        type: 'OPEN_FILE';
        agentId: string;
        item: {
            type: 'file_output';
            filename: string;
            path: string;
        };
    }
    | { type: 'CLEAR_BROWSER_TABS'; agentId: string }
    | { type: 'CLEAR_TERMINAL'; agentId: string }
    | { type: 'CLEAR_DESKTOP'; agentId: string }
    | { type: 'CLEAR_GENERATION_PREVIEW'; agentId: string }
    | { type: 'CLOSE_FILE'; agentId: string; fileKey: string }
    | { type: 'RESET' };

export type ConversationRestoreData = {
    events?: Array<ConversationEvent>;
    activeRun?: {
        run_id: string;
        status: string;
        last_seq: number;
        resume_after_seq: number;
    } | null;
    browserTabs?: Array<{
        agent_id: string | null;
        url: string;
        title: string;
        screenshot: string | null;
        tab_id: string | null;
    }>;
    terminal?: Record<string, Array<Record<string, unknown>>>;
};

export type ConversationRestorePlan = {
    agentActions: Array<AgentAction>;
    workspaceActions: Array<WorkspaceAction>;
};

export type SessionAction =
    | { type: 'RETAIN_EVENT'; event: ConversationEvent }
    | { type: 'CONFIRM_USER_MESSAGE' }
    | { type: 'FINALIZE_ITERATION' }
    | { type: 'UPDATE_IN_PROGRESS_ITERATION'; event: ConversationEvent }
    | { type: 'SET_ROOT_AGENT'; agentId: string }
    | { type: 'FINISH_TURN' };

export type ConversationEventActions = {
    session: Array<SessionAction>;
    agent: {
        immediate: Array<AgentAction>;
        batched: Array<AgentAction>;
    };
    workspace: Array<WorkspaceAction>;
    effects: Array<import('../../app/appEffects.types').AppEffect>;
};

export type LiveIteration = {
    agentId: string;
    content: string;
    thinking: string;
};

export type TranscriptItem =
    | {
        kind: 'user_prompt';
        id: string;
        content: string;
        attachments: Array<unknown>;
        isNudge: boolean;
    }
    | {
        kind: 'iteration';
        id: string;
        iterationIndex: number;
        content: string;
        thinking: string;
        toolCalls: Array<{
            id: string | null;
            name: string;
            arguments: Record<string, unknown> | null;
        }>;
    }
    | {
        kind: 'tool_result';
        id: string;
        toolCallId: string | null;
        toolName: string;
        content: string;
    }
    | {
        kind: 'file_output';
        id: string;
        filename: string;
        contentType: string;
        path: string | null;
        timestamp: string;
    }
    | {
        kind: 'compaction';
        id: string;
        summaryText: string;
        userIntentSummary: string;
        stats: CompactionStats | null;
        agentId: string | null;
        timestamp: string | null;
        keptFromId: string | null;
    }
    | { kind: 'spawn_requested'; id: string; correlationId: string | null }
    | { kind: 'error'; id: string; message: string };

export type ConversationTurn = {
    id: string;
    agentId: string | null;
    children: Array<TranscriptItem>;
};

export type LiveEventDeliveryOptions = {
    dispatch?: {
        session?: (action: SessionAction) => void;
        agent?: (action: AgentAction) => void;
        workspace?: (action: WorkspaceAction) => void;
        appEffect?: (effect: import('../../app/appEffects.types').AppEffect) => void;
    };
    requestFrame?: (callback: FrameRequestCallback) => number;
    cancelFrame?: (handle: number) => void;
};

export type LiveEventDelivery = {
    deliver: (event: ConversationEvent) => void;
    flush: () => void;
    cancel: () => void;
};
