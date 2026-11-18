import GoalStatus from './GoalStatus.jsx';
import { useGoals } from './GoalsState.jsx';

/** A chat row's goal status line, or nothing when the chat has no goal. */
export default function ConversationGoalStatus({ conversationId }) {
    const { goalsByConversation } = useGoals();
    const goal = goalsByConversation[conversationId];
    return goal ? <GoalStatus goal={goal} compact /> : null;
}
