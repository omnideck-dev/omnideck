import { useState, useRef, useCallback, useMemo } from 'react';
import useStreamStall from './useStreamStall.js';

function _uuid() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
        (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16),
    );
}

/**
 * Build the request body for /api/chat.
 */
function _buildRequestBody(message, fileData, profileId, conversationId) {
    const body = { message: message || '(uploaded file)' };
    if (conversationId) body.conversation_id = conversationId;
    if (fileData) {
        body.data = [fileData];
    }
    if (profileId) body.profile_id = profileId;
    return body;
}

/**
 * Handle non-text events that arrive on the stream (screenshots,
 * terminal output, agent lifecycle, tool calls, etc.).
 *
 * Each event type maps to a callback that DesktopApp provided.
 * Text tokens are handled separately in the main loop — this
 * function only deals with "something happened" events.
 */
function _handleStreamEvent(data, callbacks) {
    const payload = data.payload;
    if (!payload) return;

    const { type } = payload;
    const agentId = data.agent_id || null;

    // Content and turn_end are handled in the main loop, not here.
    if (type === 'content' || type === 'turn_end') return;

    // Agent started/finished → adds or updates a node in the agent tree
    if (type === 'agent_started' || type === 'agent_completed') {
        if (callbacks.onAgentEvent) callbacks.onAgentEvent(payload);
    }

    // Browser screenshot → shows in preview panel and as card thumbnail
    if (type === 'browser_screenshot') {
        callbacks.onBrowserSnapshot({
            url: payload.url,
            title: payload.title,
            screenshot: payload.screenshot,
            tabId: payload.tab_id ?? null,
            openTabIds: payload.open_tab_ids ?? null,
            agentId,
        });
    }

    // Terminal output → shows in terminal panel
    if (type === 'terminal_output') {
        callbacks.onTerminalOutput({ ...payload, agentId });
    }

    // New custom tool was created → refresh the tools panel
    if (type === 'tool_created') {
        callbacks.onToolCreated();
    }

    // Tool side-effects (memory refresh, etc.) fire from the iteration
    // event below — every tool call the model planned is on
    // iteration.tool_calls, which is the single source of truth.

    if (type === 'audio_playback') {
        callbacks.onAudioPlayback({
            key: Date.now(),
            src: `data:${payload.content_type};base64,${payload.content}`,
        });
    }

    if (type === 'desktop_active') {
        callbacks.onDesktopActive(agentId);
    }

    if (type === 'generation_preview') {
        callbacks.onGenerationPreview({ ...payload, agentId });
    }

    if (type === 'file_output') {
        if (callbacks.onAgentFileOutput) {
            callbacks.onAgentFileOutput({ ...payload, agentId });
        }
    }

    // Context usage → agent card badges (iteration count, context fill)
    if (type === 'context_usage') {
        if (callbacks.onAgentContextUsage && agentId) {
            callbacks.onAgentContextUsage({
                agentId,
                iteration: payload.iteration || null,
                maxIterations: payload.max_iterations || null,
                contextUsage: {
                    context_used: payload.context_used,
                    context_limit: payload.context_limit,
                    fill_ratio: payload.fill_ratio,
                    compaction_threshold: payload.compaction_threshold,
                },
            });
        }
    }
}

// Resume-path equivalent of the backend's _summarize_arguments cap.
const _MAX_ARG_LEN = 64;

// Event types that get appended to ``events`` (matches backend's
// _PERSISTED_TYPES in conversations/_events_log.py). Content deltas and
// transient bookkeeping types are excluded — they update other state
// (inflightIteration) instead.
const _PERSISTED_EVENT_TYPES = new Set([
    'agent_started',
    'agent_completed',
    'user_message',
    'iteration',
    'tool_result',
    'compaction',
    'file_output',
    'spawn_requested',
    'error',
]);

/**
 * Reducer for inflightIteration on a content delta. The inflight holds
 * the thinking + content the model has streamed for the current
 * iteration; it's cleared as soon as the iteration event arrives.
 *
 * Sub-agent (depth>0) deltas are dropped entirely: this state drives the
 * main chat bubble, and sub-agent output belongs in the agent activity
 * view's per-agent activityLog instead.
 */
export function _reduceInflightOnContent(prev, agentId, depth, content, thinking) {
    if ((depth ?? 0) > 0) return prev;
    const c = content || '';
    const th = thinking || '';
    if (!c && !th) return prev;
    if (!prev || prev.agentId !== agentId) {
        return { agentId, content: c, thinking: th };
    }
    return {
        agentId: prev.agentId,
        content: prev.content + c,
        thinking: prev.thinking + th,
    };
}

/**
 * Flatten an SSE message ({payload, agent_id, agent_name, timestamp, depth})
 * into the events.jsonl shape that ``_buildTurns`` expects.
 */
export function _flattenSseToEvent(data) {
    const payload = data?.payload;
    if (!payload || typeof payload !== 'object') return null;
    const { type, ...rest } = payload;
    return {
        id: data.id || `live_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        type,
        timestamp: data.timestamp || new Date().toISOString(),
        conversation_id: data.conversation_id || null,
        agent_id: data.agent_id || null,
        agent_name: data.agent_name || null,
        depth: data.depth ?? 0,
        ...rest,
    };
}

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
 * Build a list of Turn objects from the raw events.jsonl-shaped event log.
 *
 * One Turn per root `agent_started` event. Each Turn has an ordered
 * `children[]` of UI items (kind ∈ {'user_prompt', 'iteration',
 * 'tool_result', 'file_output', 'compaction', 'error'}).
 * Compaction children are repositioned so each
 * sits right before the iteration referenced by its `keptFromId` —
 * matching what the strategy actually drew as the
 * summarized/preserved boundary.
 *
 * Sub-agent events (agent_started with parent_agent_id) are skipped at
 * the top level — they're for the network view, not the chat.
 */
export function _buildTurns(events) {
    if (!Array.isArray(events)) return [];
    const turns = [];
    let currentTurn = null;

    for (const ev of events) {
        if (!ev) continue;
        const t = ev.type;

        if (t === 'agent_started' && !ev.parent_agent_id) {
            currentTurn = {
                id: `turn_${turns.length}`,
                agentId: ev.agent_id,
                children: [],
            };
            turns.push(currentTurn);
            continue;
        }
        // sub-agent lifecycle + non-chat metadata: ignore
        if (t === 'agent_started') continue;
        if (t === 'agent_completed') continue;
        if (t === 'context_usage') continue;

        if (!currentTurn) {
            // A root error with no turn yet means the turn failed before
            // the agent ever started (setup failure) — synthesize a turn
            // so the error still shows in the chat instead of being
            // dropped with the rest of the orphan events.
            if (t === 'error' && (ev.depth ?? 0) === 0) {
                currentTurn = {
                    id: `turn_${turns.length}`,
                    agentId: ev.agent_id || null,
                    children: [],
                };
                turns.push(currentTurn);
            } else {
                continue;
            }
        }

        // Everything from a sub-agent (depth>0) lives in the agent
        // activity view, not the main chat. Without this filter the
        // sub-agent's instruction user_message would render as a user
        // bubble in the conversation.
        if ((ev.depth ?? 0) > 0) continue;

        if (t === 'user_message') {
            currentTurn.children.push({
                kind: 'user_prompt',
                id: ev.id,
                content: ev.content || '',
                attachments: ev.attachments || [],
                isNudge: !!ev.is_nudge,
            });
        } else if (t === 'iteration') {
            currentTurn.children.push({
                kind: 'iteration',
                id: ev.id,
                iterationIndex: ev.iteration_index,
                content: ev.content || '',
                thinking: ev.thinking || '',
                toolCalls: (ev.tool_calls || []).map((tc) => ({
                    id: tc.id,
                    name: tc.name,
                    arguments: tc.arguments,
                })),
            });
        } else if (t === 'tool_result') {
            currentTurn.children.push({
                kind: 'tool_result',
                id: ev.id,
                toolCallId: ev.tool_call_id,
                toolName: ev.tool_name,
                content: ev.content || '',
            });
        } else if (t === 'file_output') {
            currentTurn.children.push({
                kind: 'file_output',
                id: ev.id,
                filename: ev.filename,
                contentType: ev.content_type,
                path: ev.path || null,
                timestamp: ev.timestamp,
            });
        } else if (t === 'compaction') {
            currentTurn.children.push({
                kind: 'compaction',
                id: ev.id,
                summaryText: ev.summary_text || '',
                userIntentSummary: ev.user_intent_summary || '',
                stats: ev.stats || null,
                agentId: ev.agent_id || null,
                timestamp: ev.timestamp || null,
                keptFromId: ev.kept_from_id || null,
            });
        } else if (t === 'spawn_requested') {
            currentTurn.children.push({
                kind: 'spawn_requested',
                id: ev.id,
                correlationId: ev.correlation_id || null,
            });
        } else if (t === 'error') {
            currentTurn.children.push({
                kind: 'error',
                id: ev.id,
                message: ev.message || 'An error occurred.',
            });
        }
    }

    // Reposition compactions: each chip belongs right before the
    // iteration whose id matches its keptFromId. The strategy emits the
    // compaction event AFTER the kept iteration in the log; the chip's
    // semantic place is BEFORE that iteration.
    for (const turn of turns) {
        const children = turn.children;
        const compactions = children.filter((c) => c.kind === 'compaction');
        for (const comp of compactions) {
            if (!comp.keptFromId) continue;
            const targetIdx = children.findIndex(
                (c) => c.kind === 'iteration' && c.id === comp.keptFromId,
            );
            if (targetIdx < 0) continue;
            const currentIdx = children.indexOf(comp);
            if (currentIdx < 0 || currentIdx === targetIdx - 1) continue;
            children.splice(currentIdx, 1);
            const newTargetIdx = currentIdx < targetIdx
                ? targetIdx - 1
                : targetIdx;
            children.splice(newTargetIdx, 0, comp);
        }
    }

    return turns;
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
        if (ev?.type === 'agent_started' && !ev.parent_agent_id) {
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
        if (ev?.type === 'agent_started' && !ev.parent_agent_id) {
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
 * POSTs to /api/chat and reads the response as a stream of JSON lines.
 * Each line is either a text token or an event (screenshot, tool call, etc.).
 *
 * Root agent tokens are buffered and flushed into an ordered entries[]
 * array on the assistant message (~60fps via requestAnimationFrame).
 * Sub-agent tokens go to the agent reducer for the network/detail views.
 */
export default function useStreamingChat(callbacks) {
    // ── Unified state for chat rendering ───────────────────────────────
    // ``events`` is the source of truth: persisted-shape event records
    // (matching events.jsonl). Both resume and live append to this same
    // array. ChatMessages renders by calling _buildTurns(events).
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

    const sendMessage = useCallback(async (message, fileData, profileId) => {
        if (!message && !fileData) return;

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

        // Build user message with optional attachment preview
        const userMsg = {
            id: `u_${Date.now()}_${Math.random().toString(36).slice(2)}`,
            role: 'user',
            content: message || '',
        };
        if (fileData && fileData.content_type && fileData.content_type.startsWith('image/')) {
            userMsg.images = [`data:${fileData.content_type};base64,${fileData.base64}`];
        } else if (fileData && fileData.filename) {
            userMsg.files = [{ filename: fileData.filename, content_type: fileData.content_type }];
        }

        // Add user message + a placeholder "Thinking..." bubble to the
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
            attachments: [
                ...(userMsg.images || []).map((src) => ({ kind: 'image', src })),
                ...(userMsg.files || []),
            ],
        });

        const body = _buildRequestBody(message, fileData, profileId, conversationIdRef.current);

        // IDs for pending animation frame flushes. Declared here so the
        // finally block can cancel them if the stream errors or aborts.
        let agentRafId = null;
        try {
            const controller = new AbortController();
            abortControllerRef.current = controller;
            setIsStreaming(true);
            setStopRequested(false);

            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: controller.signal,
            });
            if (!resp.body) return;

            // ── Read the JSONL stream ────────────────────────────────
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            // ── Single message per turn ─────────────────────────────
            // One assistant message with an ordered entries[] array,
            // rendered identically to the agent activity view.
            const assistantId = placeholderId;

            // ── Activity log buffering ────────────────────────────────
            // Events arrive faster than React can render. We queue
            // everything in arrival order and flush once per animation
            // frame (~60fps). React 18 batches the dispatches into one
            // render, and the reducer merges consecutive same-type entries.
            const pending = [];

            const flush = () => {
                agentRafId = null;
                for (const op of pending) {
                    op.callback(op.args);
                }
                pending.length = 0;
            };

            const scheduleFlush = () => {
                if (agentRafId === null) {
                    agentRafId = requestAnimationFrame(flush);
                }
            };

            // ── Process JSONL lines ────────────────────────────────
            // The backend streams one JSON object per line (JSONL).
            // reader.read() gives us arbitrary byte chunks, so we
            // accumulate into a buffer and extract complete lines
            // (up to each \n) one at a time.
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = buffer.indexOf('\n')) !== -1) {
                    const line = buffer.slice(0, idx).trim();
                    buffer = buffer.slice(idx + 1);
                    if (!line) continue;
                    try {
                        const data = JSON.parse(line);

                        const payload = data.payload;
                        const eventType = payload?.type;

                        _handleStreamEvent(data, callbacks);

                        // ── Update the unified events / inflight state ──
                        // Persisted events (matches backend's
                        // _PERSISTED_TYPES) get pushed to the events
                        // array so _buildTurns sees them.
                        if (eventType && _PERSISTED_EVENT_TYPES.has(eventType)) {
                            const flat = _flattenSseToEvent(data);
                            if (flat) {
                                setEvents((prev) => [...prev, flat]);
                                if (eventType === 'user_message') {
                                    // Backend confirmed our user input;
                                    // clear the optimistic synthetic turn.
                                    setPendingUserPrompt(null);
                                }
                                if (eventType === 'iteration') {
                                    // Final iteration arrived; clear the
                                    // streaming placeholder and replay the
                                    // model-planned tool calls into the
                                    // per-agent activity log. The dispatch
                                    // goes through the RAF queue so it
                                    // interleaves correctly with the
                                    // streaming content / thinking deltas
                                    // already in flight for this iteration.
                                    setInflightIteration(null);
                                    if (data.agent_id && callbacks.onActivityEntry) {
                                        for (const tc of (payload.tool_calls || [])) {
                                            if (tc?.name === 'remember' || tc?.name === 'forget') {
                                                callbacks.onMemoryChanged?.();
                                            }
                                            pending.push({
                                                callback: callbacks.onActivityEntry,
                                                args: {
                                                    agentId: data.agent_id,
                                                    entry: {
                                                        type: 'tool_call',
                                                        name: tc.name,
                                                        arguments: tc.arguments || null,
                                                        timestamp: Date.now(),
                                                    },
                                                },
                                            });
                                        }
                                        scheduleFlush();
                                    }
                                }
                            }
                        }
                        if (eventType === 'content' && data.agent_id) {
                            setInflightIteration((prev) => _reduceInflightOnContent(
                                prev, data.agent_id, data.depth,
                                payload.content, payload.thinking,
                            ));
                        }

                        // Set agentId on the assistant message so the chat
                        // view can look up this agent's activityLog.
                        if (payload?.type === 'agent_started' && !payload.parent_agent_id) {
                            rootAgentIdRef.current = payload.agent_id;
                            setMessages((prev) => {
                                const i = prev.length - 1;
                                if (i < 0 || prev[i].id !== assistantId) return prev;
                                const updated = [...prev];
                                updated[i] = { ...updated[i], agentId: payload.agent_id, streaming: true };
                                return updated;
                            });
                        }

                        if (payload?.type === 'content' && data.agent_id && callbacks.onAgentContent) {
                            const contentField = payload.content || '';
                            const hasResponse = contentField.length > 0;
                            const hasThinking = typeof payload.thinking === 'string' && payload.thinking.length > 0;
                            if (hasResponse || hasThinking) {
                                pending.push({
                                    callback: callbacks.onAgentContent,
                                    args: {
                                        agentId: data.agent_id,
                                        content: hasResponse ? contentField : null,
                                        thinking: hasThinking ? payload.thinking : null,
                                    },
                                });
                                scheduleFlush();
                            }
                        }

                        if (payload?.type === 'spawn_requested' && data.agent_id && callbacks.onActivityEntry) {
                            pending.push({
                                callback: callbacks.onActivityEntry,
                                args: {
                                    agentId: data.agent_id,
                                    entry: {
                                        type: 'spawn_requested',
                                        correlationId: payload.correlation_id,
                                        timestamp: Date.now(),
                                    },
                                },
                            });
                            scheduleFlush();
                        }

                        if (payload?.type === 'file_output' && data.agent_id && callbacks.onActivityEntry) {
                            pending.push({
                                callback: callbacks.onActivityEntry,
                                args: {
                                    agentId: data.agent_id,
                                    entry: { type: 'file_output', ...payload, timestamp: Date.now() },
                                },
                            });
                            scheduleFlush();
                        }

                        // Compaction → activity-rail marker. Main chat shows
                        // depth-0 compactions as chips; this surfaces a
                        // sub-agent's own compaction in its activity view.
                        if (payload?.type === 'compaction' && data.agent_id && callbacks.onActivityEntry) {
                            pending.push({
                                callback: callbacks.onActivityEntry,
                                args: {
                                    agentId: data.agent_id,
                                    entry: {
                                        type: 'compaction',
                                        stats: payload.stats || null,
                                        summaryText: payload.summary_text || null,
                                        userIntentSummary: payload.user_intent_summary || null,
                                        timestamp: Date.now(),
                                    },
                                },
                            });
                            scheduleFlush();
                        }

                        // Error → for a sub-agent (depth>0) it surfaces in
                        // that agent's activity view; a root error (depth 0)
                        // renders in the main chat via the events log above.
                        if (payload?.type === 'error' && (data.depth ?? 0) > 0
                            && data.agent_id && callbacks.onActivityEntry) {
                            pending.push({
                                callback: callbacks.onActivityEntry,
                                args: {
                                    agentId: data.agent_id,
                                    entry: {
                                        type: 'error',
                                        message: payload.message || 'An error occurred.',
                                        timestamp: Date.now(),
                                    },
                                },
                            });
                            scheduleFlush();
                        }

                        // Turn end — flush and mark done
                        if (payload?.type === 'turn_end') {
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
                            // Defensive: at end of turn, any unfinalized
                            // in-flight iteration is stale.
                            setInflightIteration(null);
                            setPendingUserPrompt(null);
                        }
                    } catch (e) {
                        // ignore parse errors for partial/incomplete lines
                    }
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
            // accepted, so yanking the bubble would be misleading.
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
        fetch(`/api/chat/stop?conversation_id=${conversationIdRef.current}`, { method: 'POST' }).catch(() => {});
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
        fetch(`/api/chat/stop?conversation_id=${oldConversationId}`, { method: 'POST' }).catch(() => {});
        setIsStreaming(false);
        setStopRequested(false);
        setMessages([]);
        setEvents([]);
        setInflightIteration(null);
        setPendingUserPrompt(null);
        // Seed the composer in the same batch as the new id, so the fresh
        // conversation's input gets the text (e.g. composing a goal).
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
        const baseTurns = _buildTurns(augmented);
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
