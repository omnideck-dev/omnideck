import { useGoals } from './GoalsState.jsx';
import { goalNeedsAnswer } from './goalStatus.js';

/** The conversations whose goal is waiting for the user or stopped by an error. */
export function useNeedsYou(items) {
    const { enabled, goalsByConversation } = useGoals();
    if (!enabled) return [];
    return items.filter((item) => goalNeedsAnswer(goalsByConversation[item.conversation_id]));
}
