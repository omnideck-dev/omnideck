import GoalStatus from './GoalStatus.jsx';
import { useGoals } from './GoalsState.jsx';

export default function ConversationGoalStatus({ conversationId }) {
    const { goalsByConversation } = useGoals();
    const goal = goalsByConversation[conversationId];
    return goal ? <GoalStatus goal={goal} compact /> : null;
}
