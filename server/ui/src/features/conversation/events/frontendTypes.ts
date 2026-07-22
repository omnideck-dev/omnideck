import type {
    AgentCompletedPayload,
    CompactionStats,
    ConversationEvent,
    FileOutputPayload,
    GenerationPreviewPayload,
} from './conversationEvents.generated';

export type AgentActivityEntry =
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
    | { type: 'APPEND_ACTIVITY'; agentId: string; entry: AgentActivityEntry };

export type WorkspaceAction =
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
    };

export type SessionEventCommands = {
    retainEvent?: (event: ConversationEvent) => void;
    confirmUserMessage?: () => void;
    finalizeIteration?: () => void;
    updateInProgressIteration?: (event: ConversationEvent) => void;
    setRootAgent?: (event: ConversationEvent) => void;
    finishTurn?: () => void;
};

export type EventHandlers = {
    session?: (event: ConversationEvent) => void;
    agent?: (event: ConversationEvent) => void;
    workspace?: (event: ConversationEvent) => void;
};

export type OneTimeEventActions = {
    onToolCreated?: () => void;
    onAudioPlayback?: (audio: { key: number; src: string }) => void;
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
    sessionActions?: SessionEventCommands;
    onAgentAction?: (action: AgentAction) => void;
    onWorkspaceAction?: (action: WorkspaceAction) => void;
    oneTimeActions?: OneTimeEventActions;
    requestFrame?: (callback: FrameRequestCallback) => number;
    cancelFrame?: (handle: number) => void;
};

export type LiveEventDelivery = {
    deliver: (event: ConversationEvent) => void;
    flush: () => void;
    cancel: () => void;
};
