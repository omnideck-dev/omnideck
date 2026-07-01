import Turn from './Turn.jsx';
import StarterPrompts from './StarterPrompts.jsx';
import useAutoScroll from '../hooks/useAutoScroll.js';
import { useAgentState } from '../hooks/useAgentState.jsx';
import styles from './ChatMessages.module.css';

/**
 * Scrollable chat view. Renders a list of ``<Turn>`` components — one
 * per turn — driven by ``turns`` computed inside ``useStreamingChat``
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
    const { agents, rootId } = useAgentState();

    // Scroll triggers: turns array length + the root agent's
    // activityLog growth (so tokens streaming in scroll the view).
    const rootLog = rootId ? agents[rootId]?.activityLog : null;
    const lastEntry = rootLog?.length ? rootLog[rootLog.length - 1] : null;
    const scrollKey = lastEntry
        ? (lastEntry.content?.length || lastEntry.thinking?.length || 0)
        : 0;
    const { ref, onScroll } = useAutoScroll(
        [turns, rootLog?.length, scrollKey],
    );

    const turnList = Array.isArray(turns) ? turns : [];
    const isEmpty = turnList.length === 0;

    return (
        <div className={styles.chatMessages} id="chatMessages" ref={ref} onScroll={onScroll}>
            <div className={`${styles.inner}${isEmpty ? ` ${styles.empty}` : ''}`}>
                {isEmpty ? (
                    <StarterPrompts onSelect={onStarterSelect} />
                ) : (
                    <>
                        {turnList.map((turn) => {
                            const agent = turn.agentId ? agents[turn.agentId] : null;
                            const spawnedAgents = (agent?.childIds || [])
                                .map((id) => agents[id])
                                .filter(Boolean);
                            const streaming = agent?.status === 'running';
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
