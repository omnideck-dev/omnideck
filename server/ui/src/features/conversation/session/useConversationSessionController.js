import { useState, useRef, useCallback, useMemo, useReducer } from 'react';
import { createLiveEventDelivery } from '../events/liveEventDelivery.js';
import { normalizeLiveEvent } from '../events/normalizeEvent.js';
import { projectTurns } from '../events/projectTurns.js';
import { accumulateLiveIteration } from '../events/liveIteration.js';
import { mapConversationEventToActions } from '../events/mapConversationEventToActions.js';
import { streamChatTurn } from '../transport/chatClient.js';
import useStreamStall from '../../../hooks/useStreamStall.js';

/**
 * @typedef {object} ConversationLoadData
 * @property {string} conversationId
 * @property {Array<object>} events
 * @property {Array<object>} browserTabs
 * @property {Object<string, Array<object>>} terminal
 * @property {string|null} profileId
 */

/**
 * @typedef {object} ConversationSessionDispatchers
 * @property {(action: import('../events/frontendTypes').AgentAction) => void} [agentDispatch]
 * @property {(action: import('../events/frontendTypes').WorkspaceAction) => void} [workspaceDispatch]
 * @property {(effect: import('../../app/appEffects.types').AppEffect) => void} [appEffectDispatch]
 */

function _uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
    );
}

const INITIAL_CONVERSATION_STATE = {
    events: [],
    inflightIteration: null,
    pendingUserPrompt: null,
};

function conversationReducer(state, action) {
    switch (action.type) {
        case 'RETAIN_EVENT':
            return { ...state, events: [...state.events, action.event] };
        case 'CONFIRM_USER_MESSAGE':
            return { ...state, pendingUserPrompt: null };
        case 'FINALIZE_ITERATION':
            return { ...state, inflightIteration: null };
        case 'UPDATE_IN_PROGRESS_ITERATION':
            return {
                ...state,
                inflightIteration: accumulateLiveIteration(
                    state.inflightIteration,
                    action.event.agent_id,
                    action.event.depth,
                    action.event.content,
                    action.event.thinking,
                ),
            };
        case 'FINISH_TURN':
            return { ...state, inflightIteration: null, pendingUserPrompt: null };
        case 'START_PENDING_USER_PROMPT':
            return { ...state, pendingUserPrompt: action.prompt };
        case 'RESTORE_CONVERSATION':
            return {
                events: action.events,
                inflightIteration: null,
                pendingUserPrompt: null,
            };
        case 'RESET_CONVERSATION':
            return INITIAL_CONVERSATION_STATE;
        default:
            return state;
    }
}

/**
 * Owns the active conversation and its streaming connection to the backend.
 *
 * Coordinates the active conversation session around the raw envelopes yielded
 * by the chat transport client.
 *
 * Root agent output updates the open transcript. Sub-agent activity is
 * delivered to the agent model in animation-frame batches for the network and
 * detail views; root detail is projected from the transcript.
 *
 * @param {ConversationSessionDispatchers} dispatchers
 */
export default function useConversationSessionController({
    agentDispatch,
    workspaceDispatch,
    appEffectDispatch,
} = {}) {
    // ── Unified state for chat rendering ───────────────────────────────
    // ``events`` is the source of truth for the open conversation's
    // transcript: resume seeds saved canonical records and live handling
    // retains the canonical records needed by projectTurns.
    //
    // ``inflightIteration`` holds the iteration currently being streamed
    // — content deltas update its content/thinking in real-time; once
    // the backend publishes the final ``iteration`` event we push it
    // into ``events`` and clear this.
    //
    // ``pendingUserPrompt`` shows the user's just-typed input
    // optimistically, before the backend confirms with a real
    // ``user_message`` stream event.
    const [conversationState, dispatchConversation] = useReducer(
        conversationReducer,
        INITIAL_CONVERSATION_STATE,
    );
    const { events, inflightIteration, pendingUserPrompt } = conversationState;
    // The composer draft for the open conversation. Lives here (not in the
    // chat component) so opening/seeding a conversation and its draft are one
    // concern — newConversation can seed it, switching conversations clears it.
    const [draft, setDraft] = useState('');
    const [isStreaming, _setIsStreaming] = useState(false);
    // Ref mirror of isStreaming so sendMessage can read it synchronously
    const isStreamingRef = useRef(false);
    const setIsStreaming = useCallback((val) => {
        isStreamingRef.current = val;
        _setIsStreaming(val);
    }, []);
    // A stop was requested but the turn is still finishing — the stream
    // stays open until turn_end so the backend can flush its partial output.
    const [stopRequested, _setStopRequested] = useState(false);
    const stopRequestedRef = useRef(false);
    const setStopRequested = useCallback((val) => {
        stopRequestedRef.current = val;
        _setStopRequested(val);
    }, []);
    const abortControllerRef = useRef(null);
    // The open conversation id is this hook's primary key — every request it
    // makes (send, nudge, stop, resume) is keyed by it. The ref
    // is the source of truth so commands can read it synchronously mid-flight,
    // before any re-render lands. The state below mirrors it purely so rendered
    // consumers (the sidebar's active-row highlight) update when it changes;
    // always flip both together via setConversationId, never the ref alone.
    const conversationIdRef = useRef(_uuid());
    const [activeConversationId, _setActiveConversationId] = useState(conversationIdRef.current);
    const setConversationId = useCallback((id) => {
        conversationIdRef.current = id;
        _setActiveConversationId(id);
    }, []);
    const rootAgentIdRef = useRef(null);
    const sendNudge = useCallback(async (message, agentId) => {
        if (!message || stopRequestedRef.current) return null;
        const nudgeBody = {
            message,
            conversation_id: conversationIdRef.current,
            agent_id: agentId || rootAgentIdRef.current,
        };
        try {
            const res = await fetch('/api/nudge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(nudgeBody),
            });
            if (res.ok) {
                return { ok: true, message };
            }
            const data = await res.json().catch(() => ({}));
            return {
                ok: false,
                status: res.status,
                error: data.error,
            };
        } catch {
            return {
                ok: false,
                status: 0,
                error: 'Could not reach the server',
            };
        }
    }, []);

    const sendMessage = useCallback(async (message, attachments, profileId) => {
        if (!message && !attachments?.length) return;

        // The pending attachment list keeps upload order
        // and carries filename + content_type for every entry (images too), so
        // the optimistic turn renders the same chips the composer showed.
        const pendingUserId = `u_${Date.now()}_${Math.random().toString(36).slice(2)}`;
        const pendingAttachments = (attachments || []).map((a) => {
            const isImage = a.content_type?.startsWith('image/');
            return {
                kind: isImage ? 'image' : 'file',
                filename: a.filename,
                content_type: a.content_type,
                src: isImage ? (a.preview || `data:${a.content_type};base64,${a.base64}`) : undefined,
            };
        });

        // Show the user's input immediately as a synthetic "pending" turn.
        // The backend's real user_message event will clear this and
        // append the persisted event to `events`.
        dispatchConversation({
            type: 'START_PENDING_USER_PROMPT',
            prompt: {
                id: pendingUserId,
                content: message || '',
                attachments: pendingAttachments,
            },
        });

        // The finally block cancels delivery if the stream errors or aborts.
        let liveEventDelivery = null;
        try {
            const controller = new AbortController();
            abortControllerRef.current = controller;
            setIsStreaming(true);
            setStopRequested(false);

            liveEventDelivery = createLiveEventDelivery({
                dispatch: {
                    session: (action) => {
                        if (action.type === 'SET_ROOT_AGENT') {
                            rootAgentIdRef.current = action.agentId;
                        }
                        dispatchConversation(action);
                    },
                    agent: agentDispatch,
                    workspace: workspaceDispatch,
                    appEffect: appEffectDispatch,
                },
            });

            for await (const data of streamChatTurn({
                message,
                attachments,
                profileId,
                conversationId: conversationIdRef.current,
                signal: controller.signal,
            })) {
                try {
                    const event = normalizeLiveEvent(data);
                    if (!event) continue;
                    liveEventDelivery.deliver(event);
                } catch {
                    // Malformed records must not stop later stream records.
                }
            }
            // The transport can close without a turn_end record. Preserve any
            // agent activity that was still waiting for the next frame.
            liveEventDelivery.flush();
        } catch (err) {
            if (err.name === 'AbortError') return;
            dispatchConversation({
                type: 'RETAIN_EVENT',
                event: {
                    id: `stream_error_${Date.now()}`,
                    type: 'error',
                    timestamp: new Date().toISOString(),
                    conversation_id: conversationIdRef.current,
                    agent_id: rootAgentIdRef.current,
                    agent_name: null,
                    depth: 0,
                    message: err.message || 'The conversation stream failed.',
                    retryable: true,
                },
            });
        } finally {
            liveEventDelivery?.cancel();
            abortControllerRef.current = null;
            setIsStreaming(false);
            setStopRequested(false);
            // If the stream ended without a turn_end (abort, network
            // drop), any half-streamed iteration is no longer
            // meaningful. The pending user prompt stays visible:
            // the user's input was sent and may even have been
            // accepted, so removing the pending message would be misleading.
            // The user_message action clears it on confirmation,
            // and the next sendMessage replaces it.
            dispatchConversation({ type: 'FINALIZE_ITERATION' });
        }
    }, [agentDispatch, appEffectDispatch, setStopRequested, workspaceDispatch]);

    /** Ask the backend to stop generation, leaving the stream open until
     * turn_end so the backend can flush whatever it streamed so far. */
    const stopGeneration = useCallback(() => {
        if (!isStreamingRef.current || stopRequestedRef.current) return;
        setStopRequested(true);
        fetch(`/api/chat/stop?conversation_id=${conversationIdRef.current}`, { method: 'POST' }).catch(() => { });
    }, [setStopRequested]);

    /** Resume a previous conversation by loading its history from the backend. */
    const loadConversation = useCallback(async (conversationId) => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        setIsStreaming(false);
        setStopRequested(false);
        setDraft('');

        try {
            const resp = await fetch(`/api/conversations/sessions/${conversationId}/resume`, {
                method: 'POST',
            });
            if (!resp.ok) return null;
            const data = await resp.json();
            setConversationId(conversationId);
            const events = Array.isArray(data.events) ? data.events : [];
            const retainedEvents = [];
            rootAgentIdRef.current = null;
            for (const event of events) {
                const actions = mapConversationEventToActions(event);
                for (const action of actions.session) {
                    if (action.type === 'RETAIN_EVENT') retainedEvents.push(action.event);
                    if (action.type === 'SET_ROOT_AGENT') rootAgentIdRef.current = action.agentId;
                }
            }

            // Seed the open transcript before the provider restores the other
            // feature owners from the returned canonical data.
            dispatchConversation({ type: 'RESTORE_CONVERSATION', events: retainedEvents });

            return {
                conversationId,
                events,
                browserTabs: data.browser_tabs || [],
                terminal: data.terminal || {},
                profileId: data.profile_id || null,
            };
        } catch (_) {
            return null;
        }
    }, [setConversationId]);

    /** Clear session state and switch to a fresh conversation ID.
     *
     * Sends a best-effort stop for the previous conversation. The server
     * keeps an LRU cache of recent conversations and rehydrates from disk
     * on demand, so no explicit cache-eviction call is needed.
     */
    const newConversation = useCallback(({ draft: seedDraft = '' } = {}) => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        const oldConversationId = conversationIdRef.current;
        fetch(`/api/chat/stop?conversation_id=${oldConversationId}`, { method: 'POST' }).catch(() => { });
        setIsStreaming(false);
        setStopRequested(false);
        dispatchConversation({ type: 'RESET_CONVERSATION' });
        // Seed the composer in the same batch as the new id, so the fresh
        // conversation's input gets the text.
        setDraft(seedDraft);
        const nextConversationId = _uuid();
        setConversationId(nextConversationId);
        return nextConversationId;
    }, [setConversationId, setStopRequested]);

    // Derive the chat-view turn list from events + the in-flight
    // streaming state. Both resume and live feed `events`; the live
    // path additionally maintains `inflightIteration` (for tokens
    // arriving via content delta events) and `pendingUserPrompt` (the
    // user's input shown optimistically before the backend confirms).
    const turns = useMemo(() => {
        let augmented = events;
        if (inflightIteration?.agentId) {
            augmented = [...events, {
                id: `_inflight_${inflightIteration.agentId}`,
                type: 'iteration',
                agent_id: inflightIteration.agentId,
                content: inflightIteration.content,
                thinking: inflightIteration.thinking,
                tool_calls: [],
            }];
        }
        const baseTurns = projectTurns(augmented);
        if (pendingUserPrompt) {
            return [...baseTurns, {
                id: `_pending_${pendingUserPrompt.id || 'turn'}`,
                agentId: '_pending',
                children: [{
                    kind: 'user_prompt',
                    id: pendingUserPrompt.id || '_pending_user',
                    content: pendingUserPrompt.content || '',
                    attachments: pendingUserPrompt.attachments || [],
                    isNudge: false,
                }],
            }];
        }
        return baseTurns;
    }, [events, inflightIteration, pendingUserPrompt]);

    // Stall detection. While a turn streams, the event feed can go silent for
    // many seconds — some providers stream a large tool call's arguments as
    // tokens that carry no content, so nothing arrives to render. Key off the
    // hook's own event-derived state: the persisted event count plus the
    // in-flight iteration's content/thinking length. Any advance means output
    // arrived and resets the stall clock; a plateau while streaming is a stall.
    const streamActivityKey = `${events.length}:${inflightIteration?.content?.length || 0}:${inflightIteration?.thinking?.length || 0}`;
    const stalled = useStreamStall(streamActivityKey, isStreaming);

    return {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        activeConversationId,
        draft,
        setDraft,
        sendMessage,
        sendNudge,
        stopGeneration,
        loadConversation,
        newConversation,
    };
}
