"""Goal answers sent as an ordinary user message with question context."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from agent_core.events import AgentEvent, GoalQuestionContext, UserMessagePayload

from ._models import AcceptedGoalAnswer, GoalAnswerInput, GoalAnswerSubmission
from ._store import GoalStore

logger = logging.getLogger(__name__)


def answer_message(goal_id: str, accepted: Sequence[AcceptedGoalAnswer]) -> tuple[str, tuple[GoalQuestionContext, ...]]:
    """Build the chat text and question context for checked answers."""
    context = tuple(GoalQuestionContext(
        type="goal_question", goal_id=goal_id, question_id=answer.question_id,
        question_revision=answer.question_revision, question=answer.question, answer=answer.answer,
    ) for answer in accepted)
    return "\n\n".join(answer.answer for answer in accepted), context


class GoalAnswerRecorder:
    """Save answers on the goal once the agent receives the message carrying them."""

    def __init__(self, store: GoalStore, enabled: Callable[[], bool] | None = None) -> None:
        self._store = store
        self._enabled = enabled if enabled is not None else lambda: True

    def handle_event(self, conversation_id: str, event: AgentEvent) -> None:
        """Save any goal answers in a published user message. Logs a refused save."""
        payload = event.payload
        if not isinstance(payload, UserMessagePayload) or not payload.context or not self._enabled():
            return
        by_goal: dict[str, list[GoalAnswerInput]] = {}
        for item in payload.context:
            by_goal.setdefault(item.goal_id, []).append(GoalAnswerInput(
                question_id=item.question_id, question_revision=item.question_revision, answer=item.answer,
            ))
        for goal_id, answers in by_goal.items():
            try:
                self._store.save_answers(conversation_id, GoalAnswerSubmission(goal_id=goal_id, answers=answers))
            except Exception as exc:
                # The agent still reads the message and can update the question itself.
                logger.warning("Goal answers for goal %s were not saved: %s", goal_id, exc)
