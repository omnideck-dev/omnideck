"""Messages on the app-wide activity stream."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from goals import Goal


class RunIdentity(BaseModel):
    """One active or finished run of a conversation."""

    conversation_id: str
    run_id: str


class RunSnapshotMessage(BaseModel):
    """The runs active when the stream connected."""

    type: Literal["run_snapshot"]
    runs: list[RunIdentity]


class RunStartedMessage(BaseModel):
    """A run started."""

    type: Literal["run_started"]
    runs: list[RunIdentity]


class RunFinishedMessage(BaseModel):
    """A run finished."""

    type: Literal["run_finished"]
    runs: list[RunIdentity]


class GoalSnapshotMessage(BaseModel):
    """The newest goal of each active chat when the stream connected."""

    type: Literal["goal_snapshot"]
    goals: list[Goal]


class GoalChangedMessage(BaseModel):
    """A goal was saved."""

    type: Literal["goal_changed"]
    conversation_id: str
    goal: Goal


ActivityMessage = Annotated[
    RunSnapshotMessage | RunStartedMessage | RunFinishedMessage | GoalSnapshotMessage | GoalChangedMessage,
    Field(discriminator="type"),
]

__all__ = [
    "ActivityMessage", "GoalChangedMessage", "GoalSnapshotMessage", "RunFinishedMessage", "RunIdentity",
    "RunSnapshotMessage", "RunStartedMessage",
]
