import { useLayoutEffect } from 'react';

import { useDesktopViewCatalog, useVisibleViewIds } from '../desktop/DesktopViewRuntime.jsx';
import { useConversationCatalog } from './catalog/ConversationCatalog.jsx';
import { useActiveConversationId } from './session/ConversationSession.jsx';

/** Translate desktop visibility into conversation notification state. */
export default function ConversationDesktopEffects() {
    const visibleIds = useVisibleViewIds();
    const { openViewsById } = useDesktopViewCatalog();
    const conversationId = useActiveConversationId();
    const { setVisibleConversation } = useConversationCatalog();
    const visibleConversationId = visibleIds.some(
        (id) => openViewsById[id].type === 'conversation',
    ) ? conversationId : null;

    // Update before paint so reopening a chat clears its dot in the same frame.
    useLayoutEffect(() => {
        setVisibleConversation(visibleConversationId);
    }, [setVisibleConversation, visibleConversationId]);
    useLayoutEffect(() => () => setVisibleConversation(null), [setVisibleConversation]);
    return null;
}
