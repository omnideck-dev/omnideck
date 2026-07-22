import { useEffect, useState } from 'react';
import { useAgentState } from '../features/agent/AgentState.jsx';
import useAutoScroll from '../hooks/useAutoScroll.js';
import BackButton from './BackButton.jsx';
import { formatElapsed, formatAgentName } from '../utils/agentUtils.js';
import ContextMeter from './ContextMeter.jsx';
import ActivityRail from './ActivityRail.jsx';
import MarkdownContent from './MarkdownContent.jsx';
import StatusDot from './StatusDot.jsx';
import styles from './AgentActivityView.module.css';

/**
 * Build a breadcrumb trail from root to this agent.
 */
function _buildBreadcrumb(agents, agentId) {
    const trail = [];
    let current = agentId;
    while (current && agents[current]) {
        trail.unshift(agents[current]);
        current = agents[current].parentId;
    }
    return trail;
}

/**
 * Full-screen view of a single agent's work. Stacked bars at the top
 * carry the crumb nav, the agent's name + meta, and the instruction;
 * below them, the activity stream renders via ActivityRail. Preview
 * panels (browser, terminal, files) live in the shared panel.
 *
 * The nudge bar at the bottom sends to the currently viewed agent.
 */
export default function AgentActivityView({
    agentId,
    onBack,
    onSelectAgent,
    onNudge,
    onPreview,
    nudgeDisabled = false,
}) {
    const { agents } = useAgentState();
    const agent = agentId ? agents[agentId] : null;
    const [instructionOpen, setInstructionOpen] = useState(false);

    const { ref: scrollRef, onScroll: handleScroll, resetScroll } = useAutoScroll(
        [agent?.activityLog?.length, agent?.status],
        agent?.status === 'running',
    );

    // Reset scroll lock when switching agents
    useEffect(() => {
        resetScroll();
    }, [agentId, resetScroll]);

    if (!agent) return null;

    const breadcrumb = _buildBreadcrumb(agents, agentId);
    const spawnedAgents = agent.childIds.map((id) => agents[id]).filter(Boolean);

    return (
        <div className={styles.container} data-testid="agent-activity-view">
            {/* Crumb bar — back + breadcrumb, full width */}
            <div className={styles.crumbBar}>
                <BackButton label="Agents" onClick={onBack} />
                <span className={styles.breadcrumb}>
                    {breadcrumb.map((a, i) => (
                        <span key={a.id}>
                            {i > 0 && ' › '}
                            <span className={i === breadcrumb.length - 1 ? styles.breadcrumbCurrent : ''}>
                                {formatAgentName(a.name)}
                            </span>
                        </span>
                    ))}
                </span>
            </div>

            {/* Agent name + meta */}
            <div className={styles.agentBar}>
                <div className={styles.titleRow}>
                    <StatusDot status={agent.status} />
                    <span className={styles.title} data-testid="agent-activity-title">{formatAgentName(agent.name)}</span>
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

            {/* Activity stream — previews live in the shared panel */}
            <div className={styles.body}>
                <div className={`${styles.activity} ${styles.activityFull}`} ref={scrollRef} onScroll={handleScroll}>
                    <ActivityRail
                        entries={agent.activityLog}
                        spawnedAgents={spawnedAgents}
                        onSelectAgent={onSelectAgent}
                        onPreview={onPreview}
                    />
                </div>
            </div>

            {/* Nudge bar */}
            <div className={styles.nudgeBar}>
                <span className={styles.nudgeLabel}>Nudge</span>
                <input
                    className={styles.nudgeInput}
                    type="text"
                    placeholder={nudgeDisabled ? 'Stopping...' : `Send a nudge to ${formatAgentName(agent.name)}...`}
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
    );
}
