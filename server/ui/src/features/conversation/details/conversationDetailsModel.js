import { formatAgentName } from '../../../utils/agentUtils.js';
import { workspaceResourceViewId } from '../../workspace/workspaceResourceDesktopViews.js';

function tokenTotal(agents) {
    const calls = agents.flatMap((agent) => Object.values(agent.usageByIteration || {}));
    // Never present a partial history or current context size as total usage.
    if (!calls.length || calls.some((value) => value === null)) return null;
    return calls.reduce((sum, value) => sum + value, 0);
}

/** Derived display data only. Resource availability stays in Workspace state. */
export function buildConversationDetails({ conversationId, turns = [], agents = {}, rootId, workspace = {}, openViewsById = {} }) {
    const nodes = Object.values(agents);
    const children = nodes.filter((agent) => agent.parentId != null);
    const roots = nodes.filter((agent) => agent.parentId == null);
    const artifacts = new Set();
    for (const turn of turns) {
        for (const item of turn.children || []) {
            if (item.kind === 'file_output') artifacts.add(item.path || item.filename || item.id);
        }
    }
    for (const agent of children) {
        for (const item of agent.activityLog || []) {
            if (item.type === 'file_output') artifacts.add(item.path || item.filename);
        }
    }
    const rows = [{
        id: 'artifacts', label: 'Artifacts', icon: 'collection',
        description: artifacts.size ? `${artifacts.size} created in this conversation` : 'None created yet',
        updateIds: [...artifacts].map((id) => `artifact:${id}`),
    }];
    if (children.length) {
        const working = children.filter((agent) => agent.status === 'running').length;
        const failed = children.filter((agent) => agent.status === 'error').length;
        const stopped = children.filter((agent) => agent.status === 'stopped').length;
        const finished = children.length - working - failed - stopped;
        rows.push({
            id: 'agents', label: 'Agents', icon: 'people', count: children.length,
            description: [working && `${working} working`, finished && `${finished} finished`, failed && `${failed} failed`, stopped && `${stopped} stopped`].filter(Boolean).join(' · '),
            updateIds: children.map((agent) => `agent:${agent.id}`),
        });
    }
    // Root workspaces carry forward between turns. Offer only the latest root
    // plus individual sub-agents, avoiding one duplicate resource per turn.
    for (const agent of [agents[rootId], ...children].filter(Boolean)) {
        const data = workspace[agent.id];
        if (!data || !conversationId) continue;
        for (const resourceId of ['browser', 'terminal']) {
            const available = resourceId === 'browser'
                ? Object.keys(data.browserTabs || {}).length > 0
                : (data.terminalLines || []).length > 0;
            if (!available) continue;
            const isRoot = agent.parentId == null;
            const id = workspaceResourceViewId(conversationId, agent.id, resourceId, isRoot);
            const label = resourceId === 'browser' ? 'Browser' : 'Terminal';
            rows.push({
                id, agentId: agent.id, resourceId, isRoot,
                ownerLabel: isRoot ? 'Primary agent' : formatAgentName(agent.name),
                label: isRoot ? label : `${formatAgentName(agent.name)} · ${label}`,
                icon: resourceId === 'browser' ? 'globe' : 'terminal',
                description: openViewsById[id] ? 'Open in workspace' : 'View closed',
                updateIds: [id],
            });
        }
    }
    return {
        rows,
        updateIds: rows.flatMap((row) => row.updateIds),
        turnCount: turns.length,
        agentCount: children.length,
        totalTokens: tokenTotal(nodes),
        contextUsage: agents[rootId]?.contextUsage || null,
        agentUsage: [
            { id: 'primary', label: 'Primary agent', tokens: tokenTotal(roots) },
            ...children.map((agent) => ({ id: agent.id, label: formatAgentName(agent.name), tokens: tokenTotal([agent]) })),
        ],
    };
}
