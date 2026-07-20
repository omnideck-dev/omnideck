import { useState, useRef, useCallback, useMemo } from 'react';
import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isRootAgentEvent,
} from '../features/conversation/events/eventTypes.js';
import { getAgentEventActions } from '../features/conversation/events/agentEventHandler.js';
import { applyConversationEvent } from '../features/conversation/events/applyConversationEvent.js';
import { normalizeLiveEvent } from '../features/conversation/events/normalizeEvent.js';
import { runOneTimeEventActions } from '../features/conversation/events/oneTimeEventActions.js';
import { projectTurns } from '../features/conversation/events/projectTurns.js';
import { handleSessionEvent } from '../features/conversation/events/sessionEventHandler.js';
import { getWorkspaceEventActions } from '../features/conversation/events/workspaceEventHandler.js';
import { accumulateLiveIteration } from '../features/conversation/events/liveIteration.js';
import { streamChatTurn } from '../features/conversation/transport/chatClient.js';
import useStreamStall from './useStreamStall.js';

function _uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
    );
}

// Resume-path equivalent of the backend's _summarize_arguments cap.
const _MAX_ARG_LEN = 64;

/**
 * Normalize a stored tool-call's arguments into a display string map.
 * History stores them as a JSON string (or object); live events arrive
 * pre-summarized by the backend, so this only runs on the resume path.
 * Values are stringified, whitespace-collapsed, and length-capped to
 * match what the backend emits for live calls.
 */
function _summarizeToolArgs(raw) {
    if (!raw) return null;
    let obj = raw;
    if (typeof raw === 'string') {
        try {
            obj = JSON.parse(raw);
        } catch {
            return null;
        }
    }
    if (!obj || typeof obj !== 'object') return null;
    const out = {};
    for (const [key, value] of Object.entries(obj)) {
        const text = (typeof value === 'string' ? value : JSON.stringify(value))
            .replace(/\s+/g, ' ').trim();
        out[key] = text.length > _MAX_ARG_LEN ? `${text.slice(0, _MAX_ARG_LEN - 1)}…` : text;
    }
    return Object.keys(out).length > 0 ? out : null;
}

/**
 * Convert raw LLM messages into UI-friendly message objects for display.
 *
 * A turn spans several assistant messages in history — one per tool-call
 * round-trip. They are merged into a single assistant message with one
 * ordered `entries[]` (thinking, content, tool calls), matching how a
 * live turn renders as one message. A user message closes the run.
 * Tool result messages are skipped: the chat doesn't display them.
 */
export function _historyToMessages(rawMessages) {
    const uiMessages = [];
    let openAssistant = null;

    for (const msg of rawMessages) {
        if (msg.role === 'system' || msg.role === 'tool') continue;
        if (msg.role === 'user') {
            openAssistant = null;
            uiMessages.push({
                id: `hist_u_${uiMessages.length}`,
                role: 'user',
                content: msg.content || '',
            });
            continue;
        }
        if (msg.role === 'assistant') {
            const entries = [];
            if (msg.thinking) entries.push({ type: 'thinking', thinking: msg.thinking });
            if (msg.content) entries.push({ type: 'content', content: msg.content });
            for (const tc of (msg.tool_calls || [])) {
                entries.push({
                    type: 'tool_call',
                    name: tc?.function?.name || '',
                    arguments: _summarizeToolArgs(tc?.function?.arguments),
                });
            }
            if (entries.length === 0) continue;
            if (openAssistant) {
                openAssistant.entries.push(...entries);
            } else {
                openAssistant = {
                    id: `hist_a_${uiMessages.length}`,
                    role: 'assistant',
                    entries,
                    streaming: false,
                };
                uiMessages.push(openAssistant);
            }
        }
    }
    return uiMessages;
}

/**
 * Build a compaction message item from a compaction event the resume
 * API returned. Keeps the heavy strings + stats on the item itself so
 * the panel can render without extra fetches.
 */
function _compactionMessage(ev) {
    return {
        id: `compaction-${ev.id}`,
        role: 'compaction',
        summaryText: ev.summary_text || '',
        userIntentSummary: ev.user_intent_summary || '',
        stats: ev.stats || null,
        agentId: ev.agent_id || null,
        timestamp: ev.timestamp || null,
    };
}

/**
 * Interleave compaction chips into the per-turn message list.
 *
 * Placement rule (matches what the strategy actually drew): the chip
 * sits at the boundary between what got summarized and what was kept
 * verbatim — i.e. right BEFORE the assistant message for the turn
 * whose iteration is referenced by ``compaction.kept_from_id``. The
 * chip's owning turn is the root turn that contains that iteration in
 * the event log.
 *
 * Returns a new uiMessages list with chips inserted.
 */
export function _mergeCompactions(uiMessages, events) {
    if (!Array.isArray(events) || events.length === 0) return uiMessages;

    // For each compaction event, find which root turn its kept_from_id
    // iteration belongs to. The chip belongs immediately before that
    // turn's assistant message.
    const eventsById = new Map();
    for (const ev of events) {
        if (ev?.id) eventsById.set(ev.id, ev);
    }
    // Pre-compute root turn index for every event id by walking events once.
    const turnIdxByEventId = new Map();
    let curTurnIdx = -1;
    for (const ev of events) {
        if (ev?.type === EVENT.AGENT_STARTED && isRootAgentEvent(ev)) {
            curTurnIdx += 1;
        }
        if (ev?.id) turnIdxByEventId.set(ev.id, curTurnIdx);
    }

    // For each compaction, decide which assistant idx to insert before.
    // Fallback when kept_from_id isn't present: use the turn index at the
    // compaction event's own position (best-effort).
    const insertionsByAssistantIdx = new Map();
    for (const ev of events) {
        if (ev?.type !== 'compaction') continue;
        let turnIdx = turnIdxByEventId.get(ev.kept_from_id);
        if (turnIdx == null) turnIdx = turnIdxByEventId.get(ev.id) ?? 0;
        const arr = insertionsByAssistantIdx.get(turnIdx) ?? [];
        arr.push(ev);
        insertionsByAssistantIdx.set(turnIdx, arr);
    }
    if (insertionsByAssistantIdx.size === 0) return uiMessages;

    // Walk uiMessages; before each assistant (turn) that has compactions,
    // emit chips in their original order.
    const result = [];
    let assistantIdx = -1;
    for (const msg of uiMessages) {
        if (msg.role === 'assistant') {
            assistantIdx += 1;
            const pending = insertionsByAssistantIdx.get(assistantIdx);
            if (pending) {
                for (const compEv of pending) {
                    result.push(_compactionMessage(compEv));
                }
            }
        }
        result.push(msg);
    }
    // Trailing compactions whose target turn never rendered — append at end.
    const seen = new Set();
    let trailingIdx = assistantIdx + 1;
    for (const [idx, comps] of insertionsByAssistantIdx) {
        if (idx > assistantIdx) {
            for (const compEv of comps) {
                result.push(_compactionMessage(compEv));
                seen.add(compEv);
            }
        }
    }
    return result;
}

/**
 * Inject file_output events from events.json into the assistant message
 * for the turn they belong to.
 *
 * Mapping: every root-level `agent_started` in events.json marks a new
 * turn. The Nth root agent_started corresponds to the Nth assistant ui
 * message (assistant messages and turns are 1:1 after `_historyToMessages`
 * merges multi-round tool calls).
 *
 * Mutates and returns `uiMessages` for convenience.
 */
export function _mergeFileOutputs(uiMessages, events) {
    if (!Array.isArray(events) || events.length === 0) return uiMessages;
    const assistants = uiMessages.filter((m) => m.role === 'assistant');
    let turnIdx = -1;
    for (const ev of events) {
        if (ev?.type === EVENT.AGENT_STARTED && isRootAgentEvent(ev)) {
            turnIdx += 1;
            continue;
        }
        if (ev?.type === 'file_output' && turnIdx >= 0 && turnIdx < assistants.length) {
            assistants[turnIdx].entries.push({
                type: 'file_output',
                filename: ev.filename,
                content_type: ev.content_type,
                path: ev.path || null,
                timestamp: ev.timestamp,
            });
        }
    }
    return uiMessages;
}

/**
 * Manages the streaming chat connection with the backend.
 *
 * Coordinates the active conversation session around the raw envelopes yielded
 * by the chat transport client.
 *
 * Root agent tokens are buffered and flushed into an ordered entries[]
 * array on the assistant message (~60fps via requestAnimationFrame).
 * Sub-agent tokens go to the agent reducer for the network/detail views.
 */
export default function useStreamingChat(callbacks = {}) {
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
    // ``user_message`` SSE event.
    const [messages, setMessages] = useState([]);
    const [events, setEvents] = useState([]);
    const [inflightIteration, setInflightIteration] = useState(null);
    const [pendingUserPrompt, setPendingUserPrompt] = useState(null);
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
    // makes (send, nudge, stop, resume, preview-state) is keyed by it. The ref
    // is the source of truth so callbacks can read it synchronously mid-flight,
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
    // True until the current conversation has had a turn started. Set when a
    // fresh conversation is opened (mount / New chat), cleared once its first
    // message is sent or when an existing conversation is resumed. Lets
    // sendMessage tell consumers a brand-new conversation just began without
    // them having to infer it from list membership.
    const isFreshConversationRef = useRef(true);

    const sendNudge = useCallback(async (message, agentId) => {
        if (!message) return;
        if (stopRequestedRef.current) return;
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
                if (callbacks.onNudgeSent) callbacks.onNudgeSent({ ok: true, message });
            } else {
                const data = await res.json().catch(() => ({}));
                if (callbacks.onNudgeSent) callbacks.onNudgeSent({ ok: false, status: res.status, error: data.error });
            }
        } catch {
            if (callbacks.onNudgeSent) callbacks.onNudgeSent({ ok: false, status: 0, error: 'Could not reach the server' });
        }
    }, [callbacks]);

    const sendMessage = useCallback(async (message, attachments, profileId) => {
        if (!message && !attachments?.length) return;

        // First message of a brand-new conversation: the events-first backend
        // persists it as soon as the turn starts, so tell consumers now (the
        // sidebar inserts the row + kicks off title generation). Cleared so a
        // second message in the same conversation isn't treated as new.
        if (isFreshConversationRef.current) {
            isFreshConversationRef.current = false;
            callbacks.onConversationStarted?.({
                conversationId: conversationIdRef.current,
                firstMessage: message || '',
            });
        }

        // Build user message. The pending attachment list keeps upload order
        // and carries filename + content_type for every entry (images too), so
        // the optimistic turn renders the same chips the composer showed.
        const userMsg = {
            id: `u_${Date.now()}_${Math.random().toString(36).slice(2)}`,
            role: 'user',
            content: message || '',
        };
        const pendingAttachments = (attachments || []).map((a) => {
            const isImage = a.content_type?.startsWith('image/');
            return {
                kind: isImage ? 'image' : 'file',
                filename: a.filename,
                content_type: a.content_type,
                src: isImage ? (a.preview || `data:${a.content_type};base64,${a.base64}`) : undefined,
            };
        });

        // Add user message + a placeholder "Thinking..." assistant entry to the
        // legacy messages list (still used by ChatPanel's turnCount and
        // by the agent activity rail).
        const placeholderId = Math.random().toString(36).slice(2);
        setMessages((prev) => [
            ...prev,
            userMsg,
            { id: placeholderId, role: 'assistant', placeholder: true },
        ]);
        // Show the user's input immediately as a synthetic "pending" turn.
        // The backend's real user_message SSE event will clear this and
        // append the persisted event to `events`.
        setPendingUserPrompt({
            id: userMsg.id,
            content: userMsg.content,
            attachments: pendingAttachments,
        });

        // IDs for pending animation frame flushes. Declared here so the
        // finally block can cancel them if the stream errors or aborts.
        let agentRafId = null;
        try {
            const controller = new AbortController();
            abortControllerRef.current = controller;
            setIsStreaming(true);
            setStopRequested(false);

            // ── Single message per turn ─────────────────────────────
            // One assistant message with an ordered entries[] array,
            // rendered identically to the agent activity view.
            const assistantId = placeholderId;

            // ── Activity log buffering ────────────────────────────────
            // Events arrive faster than React can render. We queue
            // everything in arrival order and flush once per animation
            // frame (~60fps). React 18 batches the dispatches into one
            // render, and the reducer merges consecutive same-type entries.
            const pendingAgentActions = [];

            const flush = () => {
                agentRafId = null;
                for (const action of pendingAgentActions.splice(0)) {
                    try {
                        callbacks.onAgentAction?.(action);
                    } catch {
                        // One failed reducer dispatch must not drop later
                        // activity that was already queued.
                    }
                }
            };

            const scheduleFlush = () => {
                if (agentRafId === null) {
                    agentRafId = requestAnimationFrame(flush);
                }
            };

            const sessionActions = {
                retainEvent: (event) => setEvents((prev) => [...prev, event]),
                confirmUserMessage: () => setPendingUserPrompt(null),
                finalizeIteration: () => setInflightIteration(null),
                updateInProgressIteration: (event) => {
                    setInflightIteration((prev) => accumulateLiveIteration(
                        prev,
                        event.agent_id,
                        event.depth,
                        event.content,
                        event.thinking,
                    ));
                },
                setRootAgent: (event) => {
                    rootAgentIdRef.current = event.agent_id;
                    setMessages((prev) => {
                        const i = prev.length - 1;
                        if (i < 0 || prev[i].id !== assistantId) return prev;
                        const updated = [...prev];
                        updated[i] = { ...updated[i], agentId: event.agent_id, streaming: true };
                        return updated;
                    });
                },
                finishTurn: () => {
                    if (agentRafId !== null) {
                        cancelAnimationFrame(agentRafId);
                        agentRafId = null;
                    }
                    flush();
                    setMessages((prev) => {
                        const i = prev.length - 1;
                        if (i < 0 || prev[i].id !== assistantId) return prev;
                        const updated = [...prev];
                        updated[i] = { ...updated[i], streaming: false, placeholder: false };
                        return updated;
                    });
                    setInflightIteration(null);
                    setPendingUserPrompt(null);
                },
            };

            const stateHandlers = {
                session: (event) => handleSessionEvent(event, sessionActions),
                agent: (event) => {
                    const { immediate, ordered } = getAgentEventActions(event);
                    for (const action of immediate) {
                        try {
                            callbacks.onAgentAction?.(action);
                        } catch {
                            // Keep later actions and state owners independent.
                        }
                    }
                    if (ordered.length === 0 || !callbacks.onAgentAction) return;
                    pendingAgentActions.push(...ordered);
                    scheduleFlush();
                },
                workspace: (event) => {
                    for (const action of getWorkspaceEventActions(event)) {
                        try {
                            callbacks.onWorkspaceAction?.(action);
                        } catch {
                            // Workspace failures do not affect session or agent state.
                        }
                    }
                },
            };

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
                    applyConversationEvent(event, stateHandlers);
                    try {
                        runOneTimeEventActions(event, callbacks);
                    } catch {
                        // A one-time UI action cannot interrupt event delivery.
                    }
                } catch {
                    // Malformed records must not stop later stream records.
                }
            }
            // Stream ended — flush any remaining buffered entries
            flush();
        } catch (err) {
            if (err.name === 'AbortError') return;
            // Replace the placeholder (or append) with an error message
            setMessages((prev) => {
                const updated = [...prev];
                const pIndex = updated.findIndex(
                    (m) => m.role === 'assistant' && (m.id === placeholderId || m.placeholder)
                );
                const errorMsg = {
                    id: placeholderId, role: 'assistant',
                    entries: [{ type: 'content', content: `[Error: ${err.message}]` }],
                    placeholder: false, streaming: false,
                };
                if (pIndex !== -1) {
                    updated[pIndex] = errorMsg;
                    return updated;
                }
                return [...prev, errorMsg];
            });
        } finally {
            if (agentRafId !== null) cancelAnimationFrame(agentRafId);
            abortControllerRef.current = null;
            setIsStreaming(false);
            setStopRequested(false);
            // If the stream ended without a turn_end (abort, network
            // drop), any half-streamed iteration is no longer
            // meaningful. The pending user prompt stays visible:
            // the user's input was sent and may even have been
            // accepted, so removing the pending message would be misleading.
            // The SSE user_message handler clears it on confirmation,
            // and the next sendMessage replaces it.
            setInflightIteration(null);
        }
    }, [callbacks, setStopRequested]);

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
            if (!resp.ok) return false;
            const data = await resp.json();
            setConversationId(conversationId);
            // A resumed conversation already exists; its next message is not new.
            isFreshConversationRef.current = false;

            const events = Array.isArray(data.events) ? data.events : [];
            // Seed the chat-side state first so a buggy callback can't
            // leave the events array out of sync with the agent tree.
            setMessages([]);
            setEvents(events);
            setInflightIteration(null);
            setPendingUserPrompt(null);

            if (callbacks.onConversationLoaded) {
                callbacks.onConversationLoaded({
                    conversationId,
                    events,
                    browserTabs: data.browser_tabs || [],
                    terminal: data.terminal || {},
                    previewState: data.preview_state || {},
                    profileId: data.profile_id || null,
                });
            }
            return true;
        } catch (_) {
            return false;
        }
    }, [callbacks, setConversationId]);

    /** Persist the user's preview-panel tab state for the current conversation. */
    const savePreviewState = useCallback(async (state) => {
        const id = conversationIdRef.current;
        if (!id) return;
        try {
            await fetch(`/api/conversations/sessions/${id}/preview-state`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(state),
            });
        } catch {
            // best-effort; preview state is non-critical UI affordance
        }
    }, []);

    /** Clear messages and switch to a fresh conversation ID.
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
        setMessages([]);
        setEvents([]);
        setInflightIteration(null);
        setPendingUserPrompt(null);
        // Seed the composer in the same batch as the new id, so the fresh
        // conversation's input gets the text.
        setDraft(seedDraft);
        setConversationId(_uuid());
        // A fresh conversation: its first message starts it anew.
        isFreshConversationRef.current = true;
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

    // Stall detection. While a turn streams, the SSE feed can go silent for
    // many seconds — some providers stream a large tool call's arguments as
    // tokens that carry no content, so nothing arrives to render. Key off the
    // hook's own event-derived state: the persisted event count plus the
    // in-flight iteration's content/thinking length. Any advance means output
    // arrived and resets the stall clock; a plateau while streaming is a stall.
    const streamActivityKey = `${events.length}:${inflightIteration?.content?.length || 0}:${inflightIteration?.thinking?.length || 0}`;
    const stalled = useStreamStall(streamActivityKey, isStreaming);

    return {
        messages,
        events,
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
        savePreviewState,
    };
}
