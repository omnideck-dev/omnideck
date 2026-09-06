import { useMemo } from 'react';
import { useAgentState } from '../../agent/AgentState.jsx';
import { useWorkspaceState } from '../../workspace/WorkspaceState.jsx';
import { buildConversationDetails } from './conversationDetailsModel.js';

export default function useConversationDetails(conversationId, turns) {
    const { agents, rootId } = useAgentState();
    const { byAgentId } = useWorkspaceState();
    return useMemo(() => buildConversationDetails({
        conversationId, turns, agents, rootId, workspace: byAgentId,
    }), [conversationId, turns, agents, rootId, byAgentId]);
}
