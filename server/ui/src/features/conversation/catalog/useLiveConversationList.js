import { useCallback, useRef } from 'react';

import { useAppEffectSubscription } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import { applyConversationChange, removeConversation } from './conversationListChanges.js';

/**
 * Keep a chat list current with chat changes from the activity stream.
 * A resync after the first one means the stream reconnected and may have
 * missed changes, so the list is fetched again.
 *
 * @param {{
 *   setItems: (update: (list: any[]) => any[]) => void,
 *   refetch: () => unknown,
 *   archived: boolean,
 * }} options
 */
export default function useLiveConversationList({ setItems, refetch, archived }) {
    const connectedRef = useRef(false);
    const onResync = useCallback(() => {
        if (connectedRef.current) void refetch();
        connectedRef.current = true;
    }, [refetch]);
    const onChanged = useCallback(/** @param {import('../../app/appEffects.types').AppEffect<'conversations/changed'>} effect */ (effect) => {
        setItems((list) => applyConversationChange(list, effect.payload, archived));
    }, [setItems, archived]);
    const onRemoved = useCallback(/** @param {import('../../app/appEffects.types').AppEffect<'conversations/removed'>} effect */ (effect) => {
        setItems((list) => removeConversation(list, effect.payload.conversationId));
    }, [setItems]);
    useAppEffectSubscription(APP_EFFECT_TYPES.CONVERSATIONS_RESYNC, onResync);
    useAppEffectSubscription(APP_EFFECT_TYPES.CONVERSATIONS_CHANGED, onChanged);
    useAppEffectSubscription(APP_EFFECT_TYPES.CONVERSATIONS_REMOVED, onRemoved);
}
