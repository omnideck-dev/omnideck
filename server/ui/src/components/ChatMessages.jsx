import Turn from './Turn.jsx';
import StarterPrompts from './StarterPrompts.jsx';
import useAutoScroll from '../hooks/useAutoScroll.js';
import { useAgentState } from '../features/agent/AgentState.jsx';
import styles from './ChatMessages.module.css';

/**
 * Scrollable chat view. Renders a list of ``<Turn>`` components — one
 * per turn — driven by ``turns`` from the conversation session
 * from a unified events array (resume + live SSE) plus the in-flight
 * iteration buffer and the optimistic user prompt.
 */
export default function ChatMessages({
    turns,
    stalled = false,
    onPreview,
    onStarterSelect,
    onSelectAgent,
}) {
    const { agents } = useAgentState();

    // The conversation session rebuilds turns whenever persisted events or
    // the in-flight iteration changes, so transcript growth is the chat's
    // complete and feature-owned scroll signal.
    const { ref, onScroll } = useAutoScroll([turns]);

    const turnList = Array.isArray(turns) ? turns : [];
    const isEmpty = turnList.length === 0;

    return (
        <div className={styles.chatMessages} id="chatMessages" ref={ref} onScroll={onScroll}>
            <div className={`${styles.inner}${isEmpty ? ` ${styles.empty}` : ''}`}>
                {isEmpty ? (
                    <StarterPrompts onSelect={onStarterSelect} />
                ) : (
                    <>
                        {turnList.map((turn, index) => {
                            const agent = turn.agentId ? agents[turn.agentId] : null;
                            const spawnedAgents = (agent?.childIds || [])
                                .map((id) => agents[id])
                                .filter(Boolean);
                            // Root agent identity can be reused across turns.
                            // Its global running status describes only the
                            // current turn; applying it to historical turns
                            // resurrects stale "Working…" rows above the
                            // latest user message.
                            const streaming = index === turnList.length - 1
                                && agent?.status === 'running';
                            return (
                                <Turn
                                    key={turn.id}
                                    turn={turn}
                                    onPreview={onPreview}
                                    spawnedAgents={spawnedAgents}
                                    onSelectAgent={onSelectAgent}
                                    streaming={streaming}
                                    stalled={stalled}
                                />
                            );
                        })}
                        <div />
                    </>
                )}
            </div>
        </div>
    );
}
