import { useMemo } from 'react';
import { useAgentState } from '../../agent/AgentState.jsx';
import { useWorkspaceState } from '../../workspace/WorkspaceState.jsx';
import { useDesktopViewCatalog } from '../../desktop/DesktopViewRuntime.jsx';
import { buildConversationDetails } from './conversationDetailsModel.js';

export default function useConversationDetails(conversationId, turns) {
    const { agents, rootId } = useAgentState();
    const { byAgentId } = useWorkspaceState();
    const { openViewsById } = useDesktopViewCatalog();
    return useMemo(() => buildConversationDetails({
        conversationId, turns, agents, rootId, workspace: byAgentId, openViewsById,
    }), [conversationId, turns, agents, rootId, byAgentId, openViewsById]);
}
