import { createContext, useContext, useReducer } from 'react';

/**
 * State for the agent tree. This powers the network graph and agent
 * detail views. Each agent gets its own node and ordered activity log.
 *
 * Data arrives here via:
 *   backend stream → canonical event action plan → reducer actions → dispatch
 *
 * The tree builds up as agent_started events arrive and updates as
 * lifecycle, content, tool, and context events flow in.
 */
const _INITIAL_STATE = {
    agents: {},             // all agent nodes, keyed by ID
    rootId: null,           // the top-level agent
};

/**
 * Create a fresh agent node with all the data an agent card or
 * detail view might need.
 */
function _makeAgent(id, name, parentId, instruction, startedAt, correlationId = null) {
    return {
        id,
        name,
        parentId,
        // Set on sub-agents only: the same id the parent's spawn_requested
        // activity entry carries. AgentOutput uses it to drop each child
        // into the right SpawnCard. None on root agents.
        correlationId,
        status: 'running',       // running | success | error | stopped
        childIds: [],            // sub-agents spawned by this agent
        startedAt,               // for elapsed time display
        instruction: instruction || '',
        activityLog: [],         // everything the agent did: thinking, content, tool calls
        inflightActivityStart: null, // first temporary text entry for the current iteration
        completedAt: null,       // when the agent finished (for frozen elapsed time)
        iteration: null,         // current loop iteration
        maxIterations: null,     // budget limit
        contextUsage: null,      // how full the context window is
    };
}

/**
 * All agent state changes go through this reducer. The action names
 * map pretty directly to what happened:
 *
 *   AGENT_STARTED/COMPLETED → agent appeared or finished
 *   APPEND_STREAM_CHUNK     → new text from a sub-agent
 *   APPEND_ACTIVITY         → tool call or file output happened
 *   UPDATE_ITERATION        → loop and context-window metadata changed
 *   RESET                   → new conversation
 */
function _agentReducer(state, action) {
    switch (action.type) {
        // New agent appeared — create its node and wire it to its parent.
        case 'AGENT_STARTED': {
            const { agentId, agentName, parentAgentId, instruction, timestamp, correlationId } = action;
            const agent = _makeAgent(agentId, agentName, parentAgentId, instruction, timestamp, correlationId || null);

            // Keep the last turn's context usage visible until this turn's
            // first context_usage event replaces it. Workspace carryover is
            // owned separately by WorkspaceProvider.
            if (!parentAgentId && state.rootId && state.agents[state.rootId]) {
                const prev = state.agents[state.rootId];
                agent.contextUsage = prev.contextUsage;
            }

            const agents = { ...state.agents, [agentId]: agent };

            // Link parent → child
            if (parentAgentId && agents[parentAgentId]) {
                agents[parentAgentId] = {
                    ...agents[parentAgentId],
                    childIds: [...agents[parentAgentId].childIds, agentId],
                };
            }

            return {
                ...state,
                agents,
                // Always update rootId when a new root agent starts (no parent).
                // Each turn creates a fresh root span with a new ID, so the
                // simple chat view needs to follow the latest one.
                rootId: parentAgentId ? state.rootId : agentId,
            };
        }

        case 'AGENT_COMPLETED': {
            const { agentId, status, timestamp } = action;
            const agent = state.agents[agentId];
            if (!agent) return state;
            return {
                ...state,
                agents: {
                    ...state.agents,
                    [agentId]: { ...agent, status, completedAt: timestamp || Date.now() },
                },
            };
        }

        // Append streamed text to an agent's activity log. Thinking and
        // content are merged in one update to keep them from getting
        // interleaved. If the last log entry is the same type, we just
        // extend it instead of creating a new one.
        case 'APPEND_STREAM_CHUNK': {
            const { agentId, content, thinking } = action;
            const agent = state.agents[agentId];
            if (!agent) return state;
            let log = [...agent.activityLog];
            const inflightActivityStart = agent.inflightActivityStart ?? log.length;

            const mergeOrAppend = (type, key, text) => {
                if (!text) return;
                const lastIdx = log.length - 1;
                if (lastIdx >= 0 && log[lastIdx].type === type) {
                    log[lastIdx] = { ...log[lastIdx], [key]: (log[lastIdx][key] || '') + text };
                } else {
                    log.push({ type, [key]: text, timestamp: Date.now() });
                }
            };

            // Thinking first, then content — matches the model's output order
            mergeOrAppend('thinking', 'thinking', thinking);
            mergeOrAppend('content', 'content', content);

            return {
                ...state,
                agents: {
                    ...state.agents,
                    [agentId]: { ...agent, activityLog: log, inflightActivityStart },
                },
            };
        }

        // Replace the temporary streamed text for this iteration with the
        // backend's finalized record. On restore there is no temporary text,
        // so the same action simply appends the finalized entries.
        case 'FINALIZE_AGENT_ITERATION': {
            const { agentId, content, thinking, toolCalls, timestamp } = action;
            const agent = state.agents[agentId];
            if (!agent) return state;
            const log = agent.inflightActivityStart === null
                ? [...agent.activityLog]
                : agent.activityLog.slice(0, agent.inflightActivityStart);
            if (thinking) log.push({ type: 'thinking', thinking, timestamp });
            if (content) log.push({ type: 'content', content, timestamp });
            for (const toolCall of (toolCalls || [])) {
                log.push({
                    type: 'tool_call',
                    name: toolCall.name,
                    arguments: toolCall.arguments || null,
                    timestamp,
                });
            }
            return {
                ...state,
                agents: {
                    ...state.agents,
                    [agentId]: {
                        ...agent,
                        activityLog: log,
                        inflightActivityStart: null,
                    },
                },
            };
        }

        // Add a one-off entry (tool call, file output) to the activity log.
        // Consecutive content/thinking entries get merged together.
        case 'APPEND_ACTIVITY': {
            const { agentId, entry } = action;
            const agent = state.agents[agentId];
            if (!agent) return state;
            const log = agent.activityLog;
            const last = log.length > 0 ? log[log.length - 1] : null;
            if (last && last.type === entry.type && (entry.type === 'content' || entry.type === 'thinking')) {
                const key = entry.type === 'content' ? 'content' : 'thinking';
                const merged = { ...last, [key]: (last[key] || '') + (entry[key] || '') };
                const newLog = [...log.slice(0, -1), merged];
                return {
                    ...state,
                    agents: {
                        ...state.agents,
                        [agentId]: { ...agent, activityLog: newLog },
                    },
                };
            }

            return {
                ...state,
                agents: {
                    ...state.agents,
                    [agentId]: {
                        ...agent,
                        activityLog: [...log, entry],
                    },
                },
            };
        }

        case 'UPDATE_ITERATION': {
            const { agentId, iteration, maxIterations, contextUsage } = action;
            const agent = state.agents[agentId];
            if (!agent) return state;
            return {
                ...state,
                agents: {
                    ...state.agents,
                    [agentId]: { ...agent, iteration, maxIterations, contextUsage },
                },
            };
        }

        case 'RESET': {
            return _INITIAL_STATE;
        }

        default:
            return state;
    }
}

const AgentStateContext = createContext(null);
const AgentDispatchContext = createContext(null);

/**
 * Provider component that wraps the app to make agent state available.
 */
export function AgentProvider({ children }) {
    const [state, dispatch] = useReducer(_agentReducer, _INITIAL_STATE);

    return (
        <AgentStateContext.Provider value={state}>
            <AgentDispatchContext.Provider value={dispatch}>
                {children}
            </AgentDispatchContext.Provider>
        </AgentStateContext.Provider>
    );
}

/**
 * Hook to read agent state.
 */
export function useAgentState() {
    const state = useContext(AgentStateContext);
    if (state === null) {
        throw new Error('useAgentState must be used within AgentProvider');
    }
    return state;
}

/**
 * Hook to get the dispatch function for agent state actions.
 */
export function useAgentDispatch() {
    const dispatch = useContext(AgentDispatchContext);
    if (dispatch === null) {
        throw new Error('useAgentDispatch must be used within AgentProvider');
    }
    return dispatch;
}
