import { useEffect } from 'react';
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
    const {
        ref,
        contentRef,
        onScroll,
        isAtBottom,
        scrollToBottom,
    } = useAutoScroll([turns]);

    const turnList = Array.isArray(turns) ? turns : [];
    const isEmpty = turnList.length === 0;

    useEffect(() => {
        const handleShortcut = (event) => {
            if (
                event.defaultPrevented
                || event.repeat
                || !event.altKey
                || event.ctrlKey
                || event.metaKey
                || event.shiftKey
                || event.key !== 'End'
                || isAtBottom
            ) {
                return;
            }

            event.preventDefault();
            scrollToBottom();
        };

        document.addEventListener('keydown', handleShortcut);
        return () => document.removeEventListener('keydown', handleShortcut);
    }, [isAtBottom, scrollToBottom]);

    return (
        <div className={styles.scrollArea}>
            <div
                className={styles.chatMessages}
                id="chatMessages"
                ref={ref}
                onScroll={onScroll}
            >
                <div
                    ref={contentRef}
                    className={`${styles.inner}${isEmpty ? ` ${styles.empty}` : ''}`}
                >
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
            {!isAtBottom && (
                <button
                    type="button"
                    className={styles.jumpToLatest}
                    onClick={scrollToBottom}
                    aria-label="Jump to latest message"
                    aria-keyshortcuts="Alt+End"
                    title="Jump to latest message (Alt+End)"
                    data-testid="jump-to-latest"
                >
                    <i className="bi bi-arrow-down" aria-hidden="true" />
                </button>
            )}
        </div>
    );
}
