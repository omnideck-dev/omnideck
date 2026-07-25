import { useMemo } from 'react';
import AgentActivityView from '../../components/AgentActivityView.jsx';
import AgentNetwork from '../../components/AgentNetwork.jsx';
import BackButton from '../../components/BackButton.jsx';
import { formatAgentName } from '../../utils/agentUtils.js';
import { useAgentState } from './AgentState.jsx';
import { projectAgentActivity } from '../conversation/events/projectAgentActivity.js';
import { useWorkspaceState } from '../workspace/WorkspaceState.jsx';
import styles from './AgentNetworkView.module.css';

function buildBreadcrumb(agents, agentId) {
    const trail = [];
    let current = agentId;
    while (current && agents[current]) {
        trail.unshift(agents[current]);
        current = agents[current].parentId;
    }
    return trail;
}

/** Owns the Agent Network header and graph-to-activity drill-down. */
export default function AgentNetworkView({
    selectedAgentId,
    turns,
    agentCounts,
    onClose,
    onOpenOverview,
    onSelectAgent,
    onNudge,
    onPreview,
    onOpenWorkspaceResource,
    nudgeDisabled = false,
}) {
    const { agents } = useAgentState();
    const { byAgentId: workspaceByAgentId } = useWorkspaceState();
    const selectedAgent = selectedAgentId ? agents[selectedAgentId] : null;
    const selectedActivity = useMemo(() => {
        if (!selectedAgent || selectedAgent.parentId !== null) {
            return selectedAgent?.activityLog;
        }
        return projectAgentActivity(turns, selectedAgent.id);
    }, [selectedAgent, turns]);
    const selectedWorkspace = selectedAgent
        ? workspaceByAgentId[selectedAgent.id]
        : null;
    const availableViews = [];
    if (Object.keys(selectedWorkspace?.browserTabs || {}).length > 0) {
        availableViews.push('browser');
    }
    if ((selectedWorkspace?.terminalLines || []).length > 0) {
        availableViews.push('terminal');
    }
    const breadcrumb = selectedAgent ? buildBreadcrumb(agents, selectedAgent.id) : [];
    const counts = agentCounts || { total: 0, running: 0, complete: 0, error: 0 };

    return (
        <section className={styles.container} data-testid="agent-network-view">
            <header className={styles.header}>
                <BackButton label="Chat" onClick={onClose} />
                <h2 className={styles.title}>Agent Network</h2>
                <span className={styles.count}>
                    {counts.total} agent{counts.total !== 1 ? 's' : ''}
                </span>
                <div className={styles.legend}>
                    {counts.running > 0 && (
                        <span className={styles.legendItem}>
                            <span className={`${styles.legendDot} ${styles.running}`} />
                            running
                        </span>
                    )}
                    {counts.complete > 0 && (
                        <span className={styles.legendItem}>
                            <span className={`${styles.legendDot} ${styles.complete}`} />
                            complete
                        </span>
                    )}
                    {counts.error > 0 && (
                        <span className={styles.legendItem}>
                            <span className={`${styles.legendDot} ${styles.error}`} />
                            error
                        </span>
                    )}
                </div>
            </header>

            {selectedAgent && (
                <nav className={styles.subnavigation} aria-label="Agent Network">
                    <BackButton label="Agents" onClick={onOpenOverview} />
                    <span className={styles.breadcrumb}>
                        {breadcrumb.map((agent, index) => (
                            <span key={agent.id}>
                                {index > 0 && <span aria-hidden="true"> › </span>}
                                {index === breadcrumb.length - 1 ? (
                                    <span className={styles.breadcrumbCurrent}>
                                        {formatAgentName(agent.name)}
                                    </span>
                                ) : (
                                    <button
                                        type="button"
                                        className={styles.breadcrumbLink}
                                        onClick={() => onSelectAgent(agent.id)}
                                    >
                                        {formatAgentName(agent.name)}
                                    </button>
                                )}
                            </span>
                        ))}
                    </span>
                </nav>
            )}

            <div className={styles.content}>
                {selectedAgent ? (
                    <AgentActivityView
                        agentId={selectedAgent.id}
                        activityEntries={selectedActivity}
                        onSelectAgent={onSelectAgent}
                        onNudge={onNudge}
                        onPreview={onPreview}
                        availableViews={availableViews}
                        onOpenView={(resourceId) => (
                            onOpenWorkspaceResource?.(selectedAgent.id, resourceId)
                        )}
                        nudgeDisabled={nudgeDisabled}
                    />
                ) : (
                    <AgentNetwork
                        onSelectAgent={onSelectAgent}
                        runningCount={counts.running}
                    />
                )}
            </div>
        </section>
    );
}
