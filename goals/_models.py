"""Durable goal, checklist, progress, and wakeup values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GoalKind = Literal["finite", "ongoing"]
GoalStatus = Literal["active", "scheduled", "needs_input", "paused", "completed", "cancelled"]
TERMINAL_STATUSES = frozenset({"completed", "cancelled"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp(value: str | datetime) -> str:
    """Normalize an explicitly zoned timestamp to UTC."""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat()


class GoalStep(BaseModel):
    """One durable checklist item whose identity survives plan revisions."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$",
        description="Stable step ID; preserve it when revising the same step.",
    )
    title: str = Field(min_length=1, max_length=2000, description="Concrete action or milestone for this step.")
    status: Literal["pending", "in_progress", "done", "blocked", "skipped"] = Field(
        default="pending", description="Current progress of this step.",
    )
    notes: str = Field(default="", description="Evidence, results, or blockers. Preserve existing notes unless explicitly revising them.")
    depends_on: list[str] = Field(default_factory=list, description="Dependency step IDs. Preserve existing dependencies even when those steps are done, unless explicitly asked to change them.")

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Step title cannot be blank")
        return value.strip()


class GoalPlanStep(GoalStep):
    """Complete agent replacement input: omissions cannot erase saved step details."""

    status: Literal["pending", "in_progress", "done", "blocked", "skipped"] = Field(
        description=GoalStep.model_fields["status"].description,
    )
    notes: str = Field(description=GoalStep.model_fields["notes"].description)
    depends_on: list[str] = Field(description=GoalStep.model_fields["depends_on"].description)


class GoalProgress(BaseModel):
    """An agent-authored progress entry retained with the goal."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=utc_now)
    summary: str = Field(min_length=1)
    next_action: str = ""


class GoalQuestionChange(BaseModel):
    """An agent-authored revision to one durable question."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$", description="Stable question ID; preserve for the same question.")
    question: str = Field(min_length=1, max_length=4000, description="Question to show the user.")
    status: Literal["open", "resolved", "withdrawn"] = Field(description="open: still needs an answer; resolved: sufficient answer found; withdrawn: no longer relevant after a change of direction.")
    choices: list[str] = Field(default_factory=list, max_length=12, description="Optional suggested answers. Free text is always allowed.")

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()

    @field_validator("choices")
    @classmethod
    def valid_choices(cls, values: list[str]) -> list[str]:
        values = [value.strip() for value in values]
        if any(not value or len(value) > 2000 for value in values) or len(set(values)) != len(values):
            raise ValueError("Choices must be unique, nonempty text of at most 2000 characters")
        return values


class GoalAnswerInput(BaseModel):
    """One user's answer tied to the question version they actually saw."""

    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1)
    question_revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=20000)

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer cannot be blank")
        return value.strip()


class GoalAnswer(GoalAnswerInput):
    """An immutable user answer; submission does not resolve the question."""

    created_at: str = Field(default_factory=utc_now)


class GoalAnswerSubmission(BaseModel):
    """Structured answers sent through the normal chat or nudge channel."""

    model_config = ConfigDict(extra="forbid")
    goal_id: str
    answers: list[GoalAnswerInput] = Field(min_length=1, max_length=50)


class GoalQuestion(GoalQuestionChange):
    """A question's current wording, pending answers and recent reviewed answers."""

    revision: int = Field(default=1, ge=1)
    updated_at: str = Field(default_factory=utc_now)
    answers: list[GoalAnswer] = Field(default_factory=list)
    reviewed_answer_count: int = Field(default=0, ge=0)


class Goal(BaseModel):
    """A goal attached to one conversation, including its single pending wake."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex)
    conversation_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    kind: GoalKind = "finite"
    status: GoalStatus = "active"
    plan: list[GoalStep] = Field(default_factory=list)
    progress: list[GoalProgress] = Field(default_factory=list)
    questions: list[GoalQuestion] = Field(default_factory=list)
    summary: str = Field(default="", max_length=12000)
    progress_count: int = Field(default=0, ge=0)
    history_count: int = Field(default=0, ge=0)
    known_facts: str = Field(default="", max_length=12000)
    blocking_question_ids: list[str] = Field(default_factory=list)
    next_action: str = ""
    status_reason: str = ""
    outcome: str | None = None
    revision: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    wake_id: str | None = None
    resume_at: str | None = None
    wake_reason: str | None = None
    claimed_run_id: str | None = None
    claimed_wake_id: str | None = None
    claimed_resume_at: str | None = None
    claimed_wake_reason: str | None = None
    claimed_next_action: str | None = None
    claim_revision: int | None = None
    last_run_id: str | None = None

    @field_validator("conversation_id", "objective", "profile_id")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @field_validator("resume_at", "claimed_resume_at")
    @classmethod
    def normalize_time(cls, value: str | None) -> str | None:
        return utc_timestamp(value) if value is not None else None

    @model_validator(mode="after")
    def validate_plan_and_wake(self) -> Goal:
        ids = {step.id for step in self.plan}
        if len(ids) != len(self.plan):
            raise ValueError("Plan step IDs must be unique")
        dependencies = {step.id: step.depends_on for step in self.plan}
        for step in self.plan:
            if any(dependency not in ids for dependency in step.depends_on):
                raise ValueError(f"Unknown dependency for step '{step.id}'")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("Plan dependencies cannot contain cycles")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)
        if (self.wake_id is None) != (self.resume_at is None):
            raise ValueError("Wake ID and resume time must be saved together")
        if self.status in {"paused", "needs_input", *TERMINAL_STATUSES} and self.wake_id is not None:
            raise ValueError("An inactive goal cannot have a pending wake")
        return self
