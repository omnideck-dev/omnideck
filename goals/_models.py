"""Durable goal, plan, question, and next-action values."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

StepStatus = Literal["pending", "in_progress", "done", "blocked", "skipped"]
WakeReason = Literal["planned", "run_now", "retry", "interrupted"]
HistoryActor = Literal["agent", "user", "system"]
ENDED_KINDS = frozenset({"done", "cancelled"})
NOTE_MAX_LENGTH = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_timestamp(value: str | datetime) -> str:
    """Normalize an explicitly zoned timestamp to UTC."""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat()


def local_time(value: str | datetime) -> str:
    """Show a time in the container's zone, such as "Fri Nov 14, 9:00 AM CST"."""
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    local = parsed.astimezone()
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%a %b} {local.day}, {hour}:{local:%M %p} {local.tzname() or ''}".rstrip()


class GoalHistoryEntry(TypedDict):
    """One committed entry in a goal's journal.

    ``actor`` says who made the change and ``claim_id`` ties the entry to the
    run that made it, so one run's changes can be shown together.
    """

    id: int
    kind: str
    created_at: str
    summary: str
    actor: HistoryActor
    claim_id: str | None
    data: dict[str, Any]


class GoalStep(BaseModel):
    """One durable checklist item whose identity survives plan revisions."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$",
        description="Stable step ID; preserve it when revising the same step.",
    )
    title: str = Field(min_length=1, max_length=2000, description="Concrete action or milestone for this step.")
    status: StepStatus = Field(default="pending", description="Current progress of this step.")
    notes: str = Field(default="", description="Evidence, results, blockers, and where work left off.")
    depends_on: list[str] = Field(default_factory=list, description="IDs of steps that must finish first.")

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Step title cannot be blank")
        return value.strip()


class GoalStepChange(BaseModel):
    """A change to one plan step, named by its ID; fields left out keep their saved values."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(
        min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$",
        description="Step ID. A new ID adds a step and needs a title.",
    )
    title: str | None = Field(default=None, min_length=1, max_length=2000, description="Concrete action or milestone.")
    status: StepStatus | None = Field(default=None, description="pending, in_progress, done, blocked, or skipped.")
    notes: str | None = Field(default=None, description="Evidence, results, blockers, and where work left off.")
    depends_on: list[str] | None = Field(default=None, description="IDs of steps that must finish first.")
    before: str | None = Field(default=None, description="For a new step only: the ID of the step to insert it before.")
    remove: bool = Field(default=False, description="True deletes the step and drops links to it from other steps.")


def apply_step_changes(plan: list[GoalStep], changes: list[GoalStepChange]) -> list[GoalStep]:
    """Merge step changes by ID into a copy of the plan."""
    if len({change.id for change in changes}) != len(changes):
        raise ValueError("Change each step at most once per update")
    steps = [step.model_copy(deep=True) for step in plan]
    for change in changes:
        index = next((i for i, step in enumerate(steps) if step.id == change.id), None)
        if change.remove:
            if index is None:
                raise ValueError(f"Step '{change.id}' does not exist")
            del steps[index]
            for step in steps:
                step.depends_on = [item for item in step.depends_on if item != change.id]
            continue
        # Some models send null for fields they leave out; null never clears a saved value.
        fields = {name: value for name, value in change.model_dump(exclude={"id", "before", "remove"}).items()
                  if value is not None}
        if index is None:
            if change.title is None:
                raise ValueError(f"New step '{change.id}' needs a title")
            step = GoalStep(id=change.id, **fields)
            position = len(steps)
            if change.before is not None:
                position = next((i for i, item in enumerate(steps) if item.id == change.before), -1)
                if position < 0:
                    raise ValueError(f"Step '{change.before}' does not exist")
            steps.insert(position, step)
            continue
        if change.before is not None:
            raise ValueError("Use before only when adding a step")
        steps[index] = GoalStep.model_validate({**steps[index].model_dump(), **fields})
    return steps


def next_step(plan: list[GoalStep]) -> GoalStep | None:
    """The step the next run works on: the one in progress, else the first ready pending step."""
    in_progress = next((step for step in plan if step.status == "in_progress"), None)
    if in_progress is not None:
        return in_progress
    finished = {step.id for step in plan if step.status in {"done", "skipped"}}
    return next((step for step in plan if step.status == "pending"
                 and all(item in finished for item in step.depends_on)), None)


def has_open_step(plan: list[GoalStep]) -> bool:
    return any(step.status in {"pending", "in_progress"} for step in plan)


class GoalWake(BaseModel):
    """A planned run. A time that has passed means run now."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["wake"] = "wake"
    id: str = Field(default_factory=lambda: uuid4().hex)
    at: str
    reason: WakeReason = "planned"

    @field_validator("at")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return utc_timestamp(value)


class GoalWait(BaseModel):
    """Wait for the user. No question IDs means the agent stopped without choosing."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["wait"] = "wait"
    question_ids: list[str] = Field(default_factory=list)


class GoalError(BaseModel):
    """The last run failed before the agent chose what happens next."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["error"] = "error"
    message: str


class GoalDone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["done"] = "done"
    outcome: str


class GoalCancelled(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["cancelled"] = "cancelled"


GoalNext = Annotated[GoalWake | GoalWait | GoalError | GoalDone | GoalCancelled, Field(discriminator="kind")]


class GoalClaim(BaseModel):
    """The run that owns the goal. ``wake_id`` is the wake it took, or none for a chat turn."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    wake_id: str | None = None


class _ChoiceNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=NOTE_MAX_LENGTH, description="One or two plain sentences for the user about what this run did.")

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note cannot be blank")
        return value.strip()


class ContinueChoice(_ChoiceNote):
    """Run again right after this run ends."""

    action: Literal["continue"]


class ScheduleChoice(_ChoiceNote):
    """Run again at a later time."""

    action: Literal["schedule"]
    at: str = Field(description="ISO 8601 time with a timezone offset.")


class WaitChoice(_ChoiceNote):
    """Wait until the user answers open questions that block all useful work."""

    action: Literal["wait_for_input"]
    question_ids: list[str] = Field(min_length=1, description="IDs of open questions that block all useful work.")


class CompleteChoice(_ChoiceNote):
    """End a goal whose outcome is done and checked."""

    action: Literal["complete"]
    outcome: str = Field(min_length=1, description="What was achieved and how it was checked.")


class GoalChoice(RootModel[Annotated[
    ContinueChoice | ScheduleChoice | WaitChoice | CompleteChoice,
    Field(discriminator="action"),
]]):
    """One next action with only the fields that action needs."""


class GoalQuestionChange(BaseModel):
    """An agent change to one question; fields left out keep their saved values."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$", description="Question ID. A new ID adds a question.")
    question: str | None = Field(default=None, min_length=1, max_length=4000, description="Question text to show the user. Required for a new question.")
    status: Literal["open", "resolved", "withdrawn"] | None = Field(default=None, description="open: still needs an answer; resolved: answered well enough; withdrawn: no longer applies.")
    choices: list[str] | None = Field(default=None, max_length=12, description="Suggested answers. Free text is always allowed.")

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("choices")
    @classmethod
    def valid_choices(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
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


class AcceptedGoalAnswer(GoalAnswerInput):
    """An accepted reply with the question wording captured during validation."""

    question: str


class GoalAnswerSubmission(BaseModel):
    """Structured answers sent through the normal chat or nudge channel."""

    model_config = ConfigDict(extra="forbid")
    goal_id: str
    answers: list[GoalAnswerInput] = Field(min_length=1, max_length=50)


class GoalQuestion(BaseModel):
    """A question's current wording, pending answers and recent reviewed answers."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    question: str = Field(min_length=1, max_length=4000)
    status: Literal["open", "resolved", "withdrawn"] = "open"
    choices: list[str] = Field(default_factory=list, max_length=12)
    revision: int = Field(default=1, ge=1)
    updated_at: str = Field(default_factory=utc_now)
    answers: list[GoalAnswer] = Field(default_factory=list)
    reviewed_answer_count: int = Field(default=0, ge=0)


class Goal(BaseModel):
    """A goal attached to one conversation and the one thing that happens next."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid4().hex)
    conversation_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    next: GoalNext = Field(default_factory=lambda: GoalWake(at=utc_now()))
    paused: bool = False
    note: str = Field(default="", max_length=NOTE_MAX_LENGTH)
    claim: GoalClaim | None = None
    plan: list[GoalStep] = Field(default_factory=list)
    questions: list[GoalQuestion] = Field(default_factory=list)
    summary: str = Field(default="", max_length=12000)
    history_count: int = Field(default=0, ge=0)
    revision: int = Field(default=1, ge=1)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    last_run_id: str | None = None

    @property
    def ended(self) -> bool:
        return self.next.kind in ENDED_KINDS

    @field_validator("conversation_id", "objective", "profile_id")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def validate_plan(self) -> Goal:
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
        return self
