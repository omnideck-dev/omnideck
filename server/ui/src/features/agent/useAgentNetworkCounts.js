import { useMemo } from 'react';

import { useAgentState } from './AgentState.jsx';

/** Counts agents in trees that contain sub-agents, matching the network view. */
export default function useAgentNetworkCounts() {
    const { agents } = useAgentState();
    return useMemo(() => {
        let total = 0;
        let running = 0;
        let complete = 0;
        let error = 0;
        for (const agent of Object.values(agents)) {
            if (agent.parentId !== null || agent.childIds.length === 0) continue;
            const queue = [agent.id];
            while (queue.length > 0) {
                const id = queue.shift();
                const node = agents[id];
                if (!node) continue;
                total += 1;
                if (node.status === 'running') running += 1;
                else if (node.status === 'success') complete += 1;
                else if (node.status === 'error') error += 1;
                queue.push(...node.childIds);
            }
        }
        return { total, running, complete, error };
    }, [agents]);
}
