import {
    useState,
    useRef,
    useCallback,
    useMemo,
    useReducer,
    useEffect,
} from 'react';
import { createLiveEventDelivery } from '../events/liveEventDelivery.js';
import { normalizeLiveEvent } from '../events/normalizeEvent.js';
import { projectTurns } from '../events/projectTurns.js';
import { accumulateLiveIteration } from '../events/liveIteration.js';
import { mapConversationEventToActions } from '../events/mapConversationEventToActions.js';
import { getConversationRestorePlan } from '../events/conversationRestore.js';
import {
    ChatStreamHttpError,
    streamAgentRun,
    streamChatTurn,
} from '../transport/chatClient.js';
import useStreamStall from '../../../hooks/useStreamStall.js';

/**
 * @typedef {object} ConversationLoadData
 * @property {string} conversationId
 * @property {Array<object>} events
 * @property {Array<object>} browserTabs
 * @property {Object<string, Array<object>>} terminal
 * @property {string|null} profileId
 * @property {{run_id: string, status: string, last_seq: number, resume_after_seq: number}|null} activeRun
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

const MAX_RECONNECT_DELAY_MS = 2000;

function abortError() {
    return new DOMException('The operation was aborted.', 'AbortError');
}

function browserIsOffline() {
    return typeof navigator !== 'undefined' && navigator.onLine === false;
}

function waitUntilOnline(signal) {
    if (!browserIsOffline()) return Promise.resolve();
    return new Promise((resolve, reject) => {
        const cleanup = () => {
            window.removeEventListener('online', onOnline);
            signal.removeEventListener('abort', onAbort);
        };
        const onOnline = () => {
            cleanup();
            resolve();
        };
        const onAbort = () => {
            cleanup();
            reject(abortError());
        };
        window.addEventListener('online', onOnline, { once: true });
        signal.addEventListener('abort', onAbort, { once: true });
    });
}

function createRequestController(parentSignal) {
    const controller = new AbortController();
    const abortFromParent = () => controller.abort();
    parentSignal.addEventListener('abort', abortFromParent, { once: true });
    return {
        controller,
        dispose: () => parentSignal.removeEventListener('abort', abortFromParent),
    };
}

function waitBeforeReconnect(attempt, signal) {
    if (signal.aborted) return Promise.reject(abortError());
    const delay = Math.min(250 * (2 ** attempt), MAX_RECONNECT_DELAY_MS);
    return new Promise((resolve, reject) => {
        const timeoutId = setTimeout(() => {
            signal.removeEventListener('abort', onAbort);
            resolve();
        }, delay);
        const onAbort = () => {
            clearTimeout(timeoutId);
            reject(abortError());
        };
        signal.addEventListener('abort', onAbort, { once: true });
    });
}

async function fetchConversationSnapshot(conversationId, signal) {
    const response = await fetch(`/api/conversations/sessions/${conversationId}/resume`, {
        method: 'POST',
        signal,
    });
    if (!response.ok) {
        let message = null;
        try {
            const body = await response.json();
            message = body?.error;
        } catch {
            // Use the status fallback when the response body is not JSON.
        }
        throw new ChatStreamHttpError(response.status, message);
    }
    return response.json();
}

function normalizeConversationLoadData(conversationId, data) {
    return {
        conversationId,
        events: Array.isArray(data.events) ? data.events : [],
        browserTabs: data.browser_tabs || [],
        terminal: data.terminal || {},
        profileId: data.profile_id || null,
        activeRun: data.active_run || null,
    };
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
    const eventsRef = useRef(events);
    // Unlike eventsRef, this includes canonical records owned only by the
    // agent/workspace views. It lets ambiguous-start recovery distinguish new
    // persisted work from old events that are not part of the transcript.
    const canonicalEventIdsRef = useRef(new Set());
    useEffect(() => {
        eventsRef.current = events;
    }, [events]);
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
    const requestControllerRef = useRef(null);
    const [connectionStatus, setConnectionStatus] = useState(
        browserIsOffline() ? 'offline' : null,
    );
    useEffect(() => {
        const onOffline = () => {
            setConnectionStatus('offline');
            // End only the current HTTP subscription. The outer controller and
            // manager-owned agent run remain alive so runConnection can attach
            // again when the browser comes online.
            requestControllerRef.current?.abort();
        };
        const onOnline = () => {
            setConnectionStatus(isStreamingRef.current ? 'reconnecting' : null);
        };
        window.addEventListener('offline', onOffline);
        window.addEventListener('online', onOnline);
        return () => {
            window.removeEventListener('offline', onOffline);
            window.removeEventListener('online', onOnline);
        };
    }, []);
    useEffect(() => () => {
        const controller = abortControllerRef.current;
        abortControllerRef.current = null;
        requestControllerRef.current?.abort();
        requestControllerRef.current = null;
        controller?.abort();
    }, []);
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

    const createEventDelivery = useCallback(() => createLiveEventDelivery({
        dispatch: {
            session: (action) => {
                if (action.type === 'SET_ROOT_AGENT') {
                    rootAgentIdRef.current = action.agentId;
                } else if (action.type === 'RETAIN_EVENT') {
                    const eventId = action.event?.id;
                    if (!eventId || !eventsRef.current.some((event) => event.id === eventId)) {
                        eventsRef.current = [...eventsRef.current, action.event];
                    }
                }
                dispatchConversation(action);
            },
            agent: agentDispatch,
            workspace: workspaceDispatch,
            appEffect: appEffectDispatch,
        },
    }), [agentDispatch, appEffectDispatch, workspaceDispatch]);

    const applySnapshotGap = useCallback((snapshot, knownEventIds, delivery) => {
        let addedEventCount = 0;
        for (const event of (snapshot.events || [])) {
            if (event?.id && knownEventIds.has(event.id)) continue;
            delivery.deliver(event);
            if (event?.id) {
                knownEventIds.add(event.id);
                canonicalEventIdsRef.current.add(event.id);
            }
            addedEventCount += 1;
        }

        // Browser and terminal records live in bounded sidecars instead of the
        // event log. Treat browser tabs as a full snapshot so tabs closed while
        // disconnected do not linger, then re-apply the latest sidecar values.
        const browserAgentIds = new Set(
            (snapshot.events || [])
                .filter((event) => event?.type === 'agent_started' && event.agent_id)
                .map((event) => event.agent_id),
        );
        for (const tab of (snapshot.browserTabs || [])) {
            if (tab?.agent_id) browserAgentIds.add(tab.agent_id);
        }
        for (const agentId of browserAgentIds) {
            try {
                workspaceDispatch?.({ type: 'CLEAR_BROWSER_TABS', agentId });
            } catch {
                // Continue restoring the other workspace records.
            }
        }
        const sidecarRestore = getConversationRestorePlan({
            events: [],
            browserTabs: snapshot.browserTabs,
            terminal: snapshot.terminal,
        });
        for (const action of sidecarRestore.workspaceActions) {
            try {
                workspaceDispatch?.(action);
            } catch {
                // A broken workspace view must not prevent transcript recovery.
            }
        }
        return addedEventCount;
    }, [workspaceDispatch]);
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

    const runConnection = useCallback(async ({
        conversationId,
        controller,
        initialRequest = null,
        activeRun = null,
        persistedEvents = [],
    }) => {
        const delivery = createEventDelivery();
        const knownEventIds = new Set(
            [
                ...canonicalEventIdsRef.current,
                ...persistedEvents.map((event) => event?.id).filter(Boolean),
            ],
        );
        let startRequest = initialRequest;
        let runId = activeRun?.run_id || null;
        let lastRunId = runId;
        let lastSeq = Number(activeRun?.resume_after_seq) || 0;
        let reconnectAttempt = 0;
        let startFailure = null;
        let sawRunEvidence = Boolean(activeRun);
        let reachedTurnEnd = false;

        setIsStreaming(true);
        setStopRequested(false);

        try {
            while (!reachedTurnEnd) {
                if (controller.signal.aborted) throw abortError();
                if (browserIsOffline()) {
                    setConnectionStatus('offline');
                    await waitUntilOnline(controller.signal);
                    setConnectionStatus('reconnecting');
                    reconnectAttempt = 0;
                    continue;
                }

                if (!startRequest && !runId) {
                    let snapshot;
                    const requestAttempt = createRequestController(controller.signal);
                    requestControllerRef.current = requestAttempt.controller;
                    try {
                        const rawSnapshot = await fetchConversationSnapshot(
                            conversationId,
                            requestAttempt.controller.signal,
                        );
                        snapshot = normalizeConversationLoadData(
                            conversationId,
                            rawSnapshot,
                        );
                    } catch (error) {
                        if (controller.signal.aborted) throw abortError();
                        if (error instanceof ChatStreamHttpError && error.status < 500) {
                            if (startFailure && !sawRunEvidence) throw startFailure;
                            throw error;
                        }
                        setConnectionStatus(
                            browserIsOffline() ? 'offline' : 'reconnecting',
                        );
                        if (browserIsOffline()) continue;
                        await waitBeforeReconnect(reconnectAttempt, controller.signal);
                        reconnectAttempt += 1;
                        continue;
                    } finally {
                        if (requestControllerRef.current === requestAttempt.controller) {
                            requestControllerRef.current = null;
                        }
                        requestAttempt.dispose();
                    }

                    const addedEvents = applySnapshotGap(
                        snapshot,
                        knownEventIds,
                        delivery,
                    );
                    const discoveredRun = snapshot.activeRun;
                    if (!discoveredRun) {
                        if (startFailure && !sawRunEvidence && addedEvents === 0) {
                            throw startFailure;
                        }
                        setConnectionStatus(null);
                        break;
                    }

                    sawRunEvidence = true;
                    const discoveredCursor = Number(discoveredRun.resume_after_seq) || 0;
                    if (lastRunId === discoveredRun.run_id) {
                        lastSeq = Math.max(lastSeq, discoveredCursor);
                    } else {
                        lastSeq = discoveredCursor;
                    }
                    runId = discoveredRun.run_id;
                    lastRunId = runId;
                    reconnectAttempt = 0;
                    continue;
                }

                const source = startRequest ? 'start' : 'run';
                const request = startRequest;
                startRequest = null;
                const requestAttempt = createRequestController(controller.signal);
                requestControllerRef.current = requestAttempt.controller;

                try {
                    const records = source === 'start'
                        ? streamChatTurn({
                            ...request,
                            conversationId,
                            signal: requestAttempt.controller.signal,
                        })
                        : streamAgentRun({
                            runId,
                            afterSeq: lastSeq,
                            signal: requestAttempt.controller.signal,
                        });
                    for await (const data of records) {
                        if (controller.signal.aborted) throw abortError();
                        const recordRunId = typeof data?.run_id === 'string'
                            ? data.run_id
                            : null;
                        const recordSeq = Number.isInteger(data?.seq) ? data.seq : null;

                        if (recordRunId) {
                            if (runId && recordRunId !== runId) {
                                throw new Error('Conversation stream changed run identity.');
                            }
                            runId = recordRunId;
                            lastRunId = recordRunId;
                        }
                        if (recordSeq !== null) {
                            if (recordSeq <= lastSeq) continue;
                            if (recordSeq !== lastSeq + 1) {
                                throw new Error(
                                    `Conversation stream skipped sequence ${lastSeq + 1}.`,
                                );
                            }
                        }

                        // A sequenced but malformed event has still been
                        // consumed. Advance past it so reconnect does not
                        // replay the same bad record forever.
                        if (recordSeq !== null) lastSeq = recordSeq;
                        const event = normalizeLiveEvent(data);
                        if (!event) continue;
                        setConnectionStatus(null);
                        if (!event.id || !knownEventIds.has(event.id)) {
                            delivery.deliver(event);
                            if (event.id) {
                                knownEventIds.add(event.id);
                                canonicalEventIdsRef.current.add(event.id);
                            }
                        }
                        sawRunEvidence = true;
                        reconnectAttempt = 0;
                        if (event.type === 'turn_end') {
                            reachedTurnEnd = true;
                            break;
                        }
                    }

                    if (!reachedTurnEnd) {
                        if (source === 'start' && !sawRunEvidence) {
                            startFailure = new Error(
                                'The conversation stream closed before the run started.',
                            );
                        }
                        // EOF without turn_end means only this connection ended.
                        // Discover the current run again so completion/pruning and
                        // a proxy-closing-a-live-response use the same path.
                        runId = null;
                    }
                } catch (error) {
                    if (controller.signal.aborted) throw abortError();
                    setConnectionStatus(
                        browserIsOffline() ? 'offline' : 'reconnecting',
                    );
                    if (source === 'start') {
                        if (
                            error instanceof ChatStreamHttpError
                            && error.status < 500
                        ) {
                            throw error;
                        }
                        if (!sawRunEvidence) {
                            startFailure = error.name === 'AbortError'
                                ? new Error(
                                    'The connection was lost before the run could be confirmed.',
                                )
                                : error;
                            runId = null;
                        }
                        if (!browserIsOffline() && sawRunEvidence) {
                            await waitBeforeReconnect(
                                reconnectAttempt,
                                controller.signal,
                            );
                            reconnectAttempt += 1;
                        }
                        continue;
                    }
                    if (error instanceof ChatStreamHttpError && error.status === 404) {
                        runId = null;
                        continue;
                    }
                    if (error instanceof ChatStreamHttpError && error.status < 500) {
                        throw error;
                    }
                    if (browserIsOffline()) continue;
                    await waitBeforeReconnect(reconnectAttempt, controller.signal);
                    reconnectAttempt += 1;
                } finally {
                    if (requestControllerRef.current === requestAttempt.controller) {
                        requestControllerRef.current = null;
                    }
                    requestAttempt.dispose();
                }
            }
            delivery.flush();
        } catch (error) {
            if (error.name !== 'AbortError' && abortControllerRef.current === controller) {
                const streamError = {
                    id: `stream_error_${Date.now()}`,
                    type: 'error',
                    timestamp: new Date().toISOString(),
                    conversation_id: conversationId,
                    agent_id: rootAgentIdRef.current,
                    agent_name: null,
                    depth: 0,
                    message: error.message || 'The conversation stream failed.',
                    retryable: true,
                };
                eventsRef.current = [...eventsRef.current, streamError];
                dispatchConversation({ type: 'RETAIN_EVENT', event: streamError });
            }
        } finally {
            delivery.cancel();
            if (abortControllerRef.current === controller) {
                abortControllerRef.current = null;
                setIsStreaming(false);
                setStopRequested(false);
                setConnectionStatus(browserIsOffline() ? 'offline' : null);
                dispatchConversation({ type: 'FINALIZE_ITERATION' });
            }
        }
    }, [
        applySnapshotGap,
        createEventDelivery,
        setIsStreaming,
        setStopRequested,
    ]);

    const sendMessage = useCallback(async (message, attachments, profileId) => {
        if ((!message && !attachments?.length) || isStreamingRef.current) return;

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

        dispatchConversation({
            type: 'START_PENDING_USER_PROMPT',
            prompt: {
                id: pendingUserId,
                content: message || '',
                attachments: pendingAttachments,
            },
        });

        const controller = new AbortController();
        abortControllerRef.current = controller;
        await runConnection({
            conversationId: conversationIdRef.current,
            controller,
            initialRequest: { message, attachments, profileId },
            persistedEvents: eventsRef.current,
        });
    }, [runConnection]);

    /** Ask the backend to stop generation, leaving the stream open until
     * turn_end so the backend can flush whatever it streamed so far. */
    const stopGeneration = useCallback(() => {
        if (!isStreamingRef.current || stopRequestedRef.current) return;
        setStopRequested(true);
        fetch(`/api/chat/stop?conversation_id=${conversationIdRef.current}`, { method: 'POST' }).catch(() => { });
    }, [setStopRequested]);

    /** Resume a previous conversation by loading its history from the backend. */
    const loadConversation = useCallback(async (conversationId) => {
        const previousConversationId = conversationIdRef.current;
        const previousWasStreaming = isStreamingRef.current;
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
        if (previousWasStreaming && previousConversationId !== conversationId) {
            fetch(
                `/api/chat/stop?conversation_id=${encodeURIComponent(previousConversationId)}`,
                { method: 'POST' },
            ).catch(() => { });
        }
        setIsStreaming(false);
        setStopRequested(false);
        setDraft('');

        const controller = new AbortController();
        abortControllerRef.current = controller;
        try {
            const rawData = await fetchConversationSnapshot(
                conversationId,
                controller.signal,
            );
            if (abortControllerRef.current !== controller) return null;
            const data = normalizeConversationLoadData(conversationId, rawData);
            canonicalEventIdsRef.current = new Set(
                data.events.map((event) => event?.id).filter(Boolean),
            );
            setConversationId(conversationId);
            const retainedEvents = [];
            rootAgentIdRef.current = null;
            for (const event of data.events) {
                const actions = mapConversationEventToActions(event);
                for (const action of actions.session) {
                    if (action.type === 'RETAIN_EVENT') retainedEvents.push(action.event);
                    if (action.type === 'SET_ROOT_AGENT') rootAgentIdRef.current = action.agentId;
                }
            }

            // Seed the open transcript before the provider restores the other
            // feature owners from the returned canonical data.
            eventsRef.current = retainedEvents;
            dispatchConversation({ type: 'RESTORE_CONVERSATION', events: retainedEvents });

            return data;
        } catch (_) {
            return null;
        } finally {
            if (abortControllerRef.current === controller) {
                abortControllerRef.current = null;
            }
        }
    }, [setConversationId]);

    /** Attach after the provider has restored agent and workspace state. */
    const reattachActiveRun = useCallback((loaded) => {
        if (!loaded?.activeRun || loaded.conversationId !== conversationIdRef.current) {
            return null;
        }
        if (abortControllerRef.current) abortControllerRef.current.abort();
        const controller = new AbortController();
        abortControllerRef.current = controller;
        return runConnection({
            conversationId: loaded.conversationId,
            controller,
            activeRun: loaded.activeRun,
            persistedEvents: loaded.events,
        });
    }, [runConnection]);

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
        eventsRef.current = [];
        canonicalEventIdsRef.current = new Set();
        rootAgentIdRef.current = null;
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
        connectionStatus,
        stopRequested,
        activeConversationId,
        draft,
        setDraft,
        sendMessage,
        sendNudge,
        stopGeneration,
        loadConversation,
        reattachActiveRun,
        newConversation,
    };
}
