"""Provider-independent setup contracts. No HTTP framework or SDK state here."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from integrations.discovery import DiscoveredOperation
from .callback import OAuthCallback


class SetupError(Exception):
    """An explicitly safe error that can be shown in setup status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, repr=False)
class PreparedConnection:
    credentials: dict[str, str]
    operations: tuple[DiscoveredOperation, ...] = ()


@dataclass(frozen=True)
class NewConnection:
    slug: str
    label: str
    user_suffix: str
    operation_grants: tuple[str, ...]


@dataclass(frozen=True)
class Reconnect:
    connection_id: str


@dataclass(repr=False)
class BrowserAuthorization:
    receiver: OAuthCallback
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    authorize_url: str | None = None

    def present(self, url: str) -> None:
        self.receiver.arm(url)
        self.authorize_url = url
        self.ready.set()


class OAuthAdapter(Protocol):
    async def prepare(self, browser: BrowserAuthorization) -> PreparedConnection: ...


Status = Literal["pending", "committing", "success", "denied", "expired", "cancelled", "error"]
Commit = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(repr=False)
class SetupAttempt:
    handle: str
    browser: BrowserAuthorization
    task: asyncio.Task[None] | None = None
    status: Status = "pending"
    integration_id: str | None = None
    error: dict[str, str] | None = None
    completed_at: float | None = None

    def public_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {"state": self.handle, "status": self.status}
        if self.integration_id is not None:
            result["integration_id"] = self.integration_id
        if self.error is not None:
            result["error"] = self.error
        return result
