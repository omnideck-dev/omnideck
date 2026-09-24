import { useEffect, useState } from 'react';
import { useAgentState } from '../features/agent/AgentState.jsx';
import useAutoScroll from '../hooks/useAutoScroll.js';
import { formatElapsed, formatAgentName } from '../utils/agentUtils.js';
import ContextMeter from './ContextMeter.jsx';
import ActivityRail from './ActivityRail.jsx';
import BrowserIcon from './icons/BrowserIcon.jsx';
import MarkdownContent from './MarkdownContent.jsx';
import OfflineNotice from './OfflineNotice.jsx';
import StatusDot from './StatusDot.jsx';
import TerminalIcon from './icons/TerminalIcon.jsx';
import styles from './AgentActivityView.module.css';

/**
 * Detail view of a single agent's work. Stacked bars at the top
 * carry the agent's name + meta and the instruction;
 * below them, the activity stream renders via ActivityRail. Available
 * Browser and Terminal output can be opened as agent-bound desktop tabs.
 *
 * The nudge bar at the bottom sends to the currently viewed agent.
 */
export default function AgentActivityView({
    agentId,
    activityEntries,
    onSelectAgent,
    onNudge,
    onPreview,
    availableViews = [],
    onOpenView,
    isOffline = false,
    stopRequested = false,
}) {
    const { agents } = useAgentState();
    const agent = agentId ? agents[agentId] : null;
    const [instructionOpen, setInstructionOpen] = useState(false);
    const activityLog = activityEntries || agent?.activityLog;
    const lastActivity = activityLog?.length
        ? activityLog[activityLog.length - 1]
        : null;

    const { ref: scrollRef, onScroll: handleScroll, resetScroll } = useAutoScroll(
        [
            activityLog?.length,
            lastActivity?.content?.length,
            lastActivity?.thinking?.length,
            agent?.status,
        ],
        agent?.status === 'running',
    );

    // Reset scroll lock when switching agents
    useEffect(() => {
        resetScroll();
    }, [agentId, resetScroll]);

    if (!agent) return null;

    const spawnedAgents = agent.childIds.map((id) => agents[id]).filter(Boolean);
    const nudgeDisabled = isOffline || stopRequested;
    const nudgePlaceholder = stopRequested
        ? 'Stopping...'
        : `Send a nudge to ${formatAgentName(agent.name)}...`;

    return (
        <div className={styles.container} data-testid="agent-activity-view">
            {/* Agent name + meta */}
            <div className={styles.agentBar}>
                <div className={styles.titleRow}>
                    <StatusDot status={agent.status} />
                    <span className={styles.title} data-testid="agent-activity-title">{formatAgentName(agent.name)}</span>
                    {availableViews.length > 0 && (
                        <div className={styles.viewActions} aria-label="Agent views">
                            {availableViews.includes('browser') && (
                                <button
                                    type="button"
                                    className={styles.viewAction}
                                    onClick={() => onOpenView?.('browser')}
                                    data-testid="open-agent-browser"
                                >
                                    <BrowserIcon size={13} />
                                    Browser
                                </button>
                            )}
                            {availableViews.includes('terminal') && (
                                <button
                                    type="button"
                                    className={styles.viewAction}
                                    onClick={() => onOpenView?.('terminal')}
                                    data-testid="open-agent-terminal"
                                >
                                    <TerminalIcon size={13} />
                                    Terminal
                                </button>
                            )}
                        </div>
                    )}
                    <div className={styles.meta}>
                        {agent.startedAt && <span>{formatElapsed(agent.startedAt, agent.completedAt)}</span>}
                        {agent.iteration !== null && (
                            <span>
                                iter {agent.iteration}{agent.maxIterations ? `/${agent.maxIterations}` : ''}
                            </span>
                        )}
                        <ContextMeter contextUsage={agent.contextUsage} />
                        {agent.childIds.length > 0 && (
                            <span>{agent.childIds.length} sub-agent{agent.childIds.length !== 1 ? 's' : ''}</span>
                        )}
                    </div>
                </div>
            </div>

            {/* Instruction bar — collapsed by default so long task descriptions
              * don't dominate the view. Click to expand. */}
            {agent.instruction && (
                <div className={`${styles.instruction}${instructionOpen ? ` ${styles.instructionOpen}` : ''}`}>
                    <button
                        type="button"
                        className={styles.instructionToggle}
                        onClick={() => setInstructionOpen((v) => !v)}
                        data-testid="instruction-toggle"
                        aria-expanded={instructionOpen}
                    >
                        <span className={styles.instructionToggleChev} aria-hidden="true">▶</span>
                        Instruction
                        {!instructionOpen && (
                            <span className={styles.instructionPreview}>
                                {agent.instruction.split('\n')[0]}
                            </span>
                        )}
                    </button>
                    {instructionOpen && (
                        <div className={styles.instructionBody} data-testid="instruction-body">
                            <MarkdownContent>{agent.instruction}</MarkdownContent>
                        </div>
                    )}
                </div>
            )}

            {/* Activity stream */}
            <div className={styles.body}>
                <div
                    className={styles.activity}
                    ref={scrollRef}
                    onScroll={handleScroll}
                    data-testid="agent-activity-scroll"
                >
                    <ActivityRail
                        entries={activityLog}
                        spawnedAgents={spawnedAgents}
                        onSelectAgent={onSelectAgent}
                        onPreview={onPreview}
                    />
                </div>
            </div>

            <div className={styles.nudgeArea}>
                {isOffline && (
                    <OfflineNotice description="Nudges are unavailable." />
                )}
                <div className={styles.nudgeBar}>
                    <span className={styles.nudgeLabel}>Nudge</span>
                    <input
                        className={styles.nudgeInput}
                        type="text"
                        placeholder={nudgePlaceholder}
                        disabled={nudgeDisabled}
                        onKeyDown={(e) => {
                            if (nudgeDisabled) return;
                            if (e.key === 'Enter' && e.target.value.trim()) {
                                if (onNudge) onNudge(e.target.value.trim(), agentId);
                                e.target.value = '';
                            }
                        }}
                    />
                    <span className={styles.nudgeHint}>queues for {formatAgentName(agent.name)}</span>
                </div>
            </div>
        </div>
    );
}
