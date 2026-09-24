import { useCallback } from 'react';

import RoutinesView from '../../components/routines/RoutinesView.jsx';
import {
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';

export default function RoutinesDesktopView() {
    const { newConversation } = useConversationSessionCommands();
    const navigation = useDesktopNavigationCommands();
    const composeInNewConversation = useCallback(async (text) => {
        const conversationId = await newConversation({ draft: text });
        navigation.openChat(conversationId);
        return conversationId;
    }, [navigation, newConversation]);

    return <RoutinesView onComposeInChat={composeInNewConversation} />;
}
