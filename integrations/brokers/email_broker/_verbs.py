"""Verb dispatcher for the email broker.

Bridges two layers with different vocabularies:

- The RPC layer (``integrations._rpc``) speaks frames: ``(verb_name, args_dict)
  -> result_dict``. It has no idea what verbs exist or what they do.
- The client layer (``_imap_client``, ``_smtp_client``) speaks email: typed
  method calls, typed returns.

The shared broker dispatcher resolves canonical operation IDs and applies the
exact grant allowlist before this module's email-specific handler is invoked.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import secrets
from pathlib import Path
from typing import Any

from integrations._perms import ATTACHMENT_FILE_MODE
from integrations._rpc import RpcError
from integrations.brokers._common._dispatch import (
    OperationHandler,
    dispatch_granted_operation,
)
from integrations.brokers.email_broker._caldav_client import CalDavClient
from integrations.brokers.email_broker._imap_client import ImapClient
from integrations.brokers.email_broker._smtp_client import SmtpClient
from integrations.brokers.email_broker.types import Calendar, Event, OutboundAttachment
from integrations.calendar_refs import (
    CalendarTarget,
    InvalidCalendarRef,
    decode_event_ref,
    decode_series_ref,
    encode_event_ref,
    encode_series_ref,
)
from integrations.operation_grants import OperationGrants

# Total raw byte cap across all outbound attachments in one send. Above this
# we refuse rather than try — provider SMTP limits land near 25MB and we want
# the broker's BAD_REQUEST to fire before a multi-MB JSON frame works its way
# all the way to the SMTP server only to bounce. 30MB leaves headroom over
# the strictest providers without inviting OOM-shaped payloads.
_MAX_OUTBOUND_ATTACHMENT_BYTES = 30 * 1024 * 1024

class VerbDispatcher:
    """Route one RPC verb call to the right client method."""

    def __init__(
        self,
        imap: ImapClient,
        # SMTP is None when the catalog entry doesn't set SMTP_HOST (no
        # outbound path configured); send_message then returns "not
        # implemented" so the gate decision and the missing-config decision
        # are visibly distinct.
        smtp: SmtpClient | None,
        # caldav is None for catalog entries without calendar operations;
        # those handlers return "not implemented".
        caldav: CalDavClient | None = None,
        *,
        operation_grants: OperationGrants,
        attachments_dir: Path,
    ) -> None:
        self._imap = imap
        self._smtp = smtp
        self._caldav = caldav
        self._operation_grants = operation_grants
        self._attachments_dir = attachments_dir

        self._handlers: dict[str, OperationHandler] = {
            "email.mailboxes.list": self._handle_list_mailboxes,
            "email.messages.list": self._handle_list_messages,
            "email.messages.search": self._handle_search_messages,
            "email.messages.get": self._handle_fetch_message,
            "email.attachments.download": self._handle_fetch_attachment,
            "email.messages.move": self._handle_move_messages,
        }
        if smtp is not None:
            self._handlers["email.messages.send"] = self._handle_send_message
        if caldav is not None:
            self._handlers["calendar.calendars.list"] = self._handle_list_calendars
            self._handlers["calendar.events.list"] = self._handle_list_events
            self._handlers["calendar.events.search"] = self._handle_search_events
            self._handlers["calendar.events.create"] = self._handle_create_event
            self._handlers["calendar.events.update"] = self._handle_update_event
            self._handlers["calendar.events.delete"] = self._handle_delete_event
            self._handlers["calendar.series.update"] = self._handle_update_event_series
            self._handlers["calendar.series.delete"] = self._handle_delete_event_series

    async def dispatch(self, operation_id: str, args: dict[str, Any]) -> dict[str, Any]:
        """Entry point called by the RPC layer for every incoming frame."""
        return await dispatch_granted_operation(
            operation_id,
            args,
            operation_grants=self._operation_grants,
            handlers=self._handlers,
        )

    # --- handlers -----------------------------------------------------------

    async def _handle_list_mailboxes(self, _args: dict[str, Any]) -> dict[str, Any]:
        """``email.mailboxes.list`` takes no args; returns ``{"mailboxes": [...]}``.

        The client returns typed :class:`Mailbox` instances; we serialize via
        ``.model_dump()`` here because this is the wire boundary — the dict
        returned from this handler goes straight into the JSON RPC frame.
        """
        mailboxes = await self._imap.list_mailboxes()
        return {"mailboxes": [m.model_dump() for m in mailboxes]}

    async def _handle_list_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        """``list_messages {folder, limit}`` → ``{headers: [...]}``."""
        folder = _require_str(args, "folder")
        limit = _require_int(args, "limit", default=20)
        headers = await self._imap.list_messages(folder, limit)
        return {"headers": [h.model_dump() for h in headers]}

    async def _handle_search_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        """``search_messages {folder, query, limit}`` → ``{headers: [...]}``."""
        folder = _require_str(args, "folder")
        query = _require_str(args, "query")
        limit = _require_int(args, "limit", default=20)
        headers = await self._imap.search_messages(folder, query, limit)
        return {"headers": [h.model_dump() for h in headers]}

    async def _handle_fetch_message(self, args: dict[str, Any]) -> dict[str, Any]:
        """``fetch_message {folder, uid}`` → ``{message: {header, body_text}}``."""
        folder = _require_str(args, "folder")
        uid = _require_str(args, "uid")
        try:
            message = await self._imap.fetch_message(folder, uid)
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"message": message.model_dump()}

    async def _handle_fetch_attachment(self, args: dict[str, Any]) -> dict[str, Any]:
        """``fetch_attachment {folder, uid, attachment_id}`` → ``{path, filename, mime_type, size}``.

        Writes the attachment bytes to the configured attachments dir and
        returns the on-disk path. Original filename is preserved when
        possible; collisions get an 8-char hex suffix on the stem.
        """
        folder = _require_str(args, "folder")
        uid = _require_str(args, "uid")
        attachment_id = _require_str(args, "attachment_id")
        try:
            payload, filename, mime_type = await self._imap.fetch_attachment(
                folder, uid, attachment_id,
            )
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc

        path = _write_attachment(
            self._attachments_dir, payload, filename, mime_type,
        )
        return {
            "path": str(path),
            "filename": filename,
            "mime_type": mime_type,
            "size": len(payload),
        }

    async def _handle_move_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        """``move_messages {folder, uids, dest_folder}`` → ``{moved: true}``.

        ``uids`` is a JSON array of strings. The server moves whatever it
        recognizes and silently skips the rest, returning ``OK`` either
        way; we don't surface a count because the wire protocol doesn't
        expose a reliable one. Callers needing exact accounting must
        re-list the source folder.
        """
        folder = _require_str(args, "folder")
        uids = _require_str_list(args, "uids")
        dest_folder = _require_str(args, "dest_folder")
        if not uids:
            raise RpcError("BAD_REQUEST", "'uids' must not be empty")
        if len(uids) > 200:
            raise RpcError(
                "BAD_REQUEST",
                f"cannot move more than 200 messages per call (got {len(uids)})",
            )
        try:
            await self._imap.move_messages(folder, uids, dest_folder)
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"moved": True}

    async def _handle_send_message(self, args: dict[str, Any]) -> dict[str, Any]:
        """``send_message {to, subject, body, attachments?}`` → ``{sent: true, message_id}``.

        ``to`` is a JSON array of bare addresses. ``attachments``, when
        present, is an array of ``{filename, mime_type, data_b64}`` objects
        whose bytes get attached as ``Content-Disposition: attachment``
        parts. The broker does not validate addresses; the upstream MTA
        does, and we surface its rejection unchanged.
        """
        if self._smtp is None:
            raise RpcError("BAD_REQUEST", "smtp not configured for this integration")
        to = _require_str_list(args, "to")
        subject = _require_str(args, "subject")
        body = _require_str(args, "body")
        attachments = _parse_outbound_attachments(args.get("attachments"))
        message_id = await self._smtp.send_message(
            to=to, subject=subject, body=body, attachments=attachments,
        )
        return {"sent": True, "message_id": message_id}

    async def _handle_list_calendars(self, _args: dict[str, Any]) -> dict[str, Any]:
        """``calendar.calendars.list`` takes no args; returns ``{"calendars": [...]}``."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        calendars = await self._caldav.list_calendars()
        return {"calendars": [_wire_calendar(c) for c in calendars]}

    async def _handle_list_events(self, args: dict[str, Any]) -> dict[str, Any]:
        """List expanded occurrences identified by opaque mutation references."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        calendar_ref = _require_str(args, "calendar_ref")
        days_forward = _require_int(args, "days_forward", default=30)
        days_back = _require_int(args, "days_back", default=0)
        limit = _require_int(args, "limit", default=50)
        name, events = await self._caldav.list_events(
            calendar_ref, days_forward, days_back, limit,
        )
        return {
            "calendar_name": name,
            "events": [_wire_event(e, calendar_ref) for e in events],
        }

    async def _handle_search_events(self, args: dict[str, Any]) -> dict[str, Any]:
        """Search expanded occurrences identified by opaque mutation refs."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        calendar_ref = _require_str(args, "calendar_ref")
        query = _require_str(args, "query")
        days_forward = _require_int(args, "days_forward", default=365)
        days_back = _require_int(args, "days_back", default=0)
        limit = _require_int(args, "limit", default=50)
        try:
            name, events = await self._caldav.search_events(
                calendar_ref, query, days_forward, days_back, limit,
            )
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", str(exc)) from exc
        return {
            "calendar_name": name,
            "events": [_wire_event(e, calendar_ref) for e in events],
        }

    async def _handle_create_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """``calendar.events.create`` creates a VEVENT and returns its server representation."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        calendar_ref = _require_str(args, "calendar_ref")
        summary = _require_str(args, "summary")
        start = _require_str(args, "start")
        end = _require_str(args, "end")
        description = _optional_str(args, "description")
        location = _optional_str(args, "location")
        attendees = _optional_str_list(args, "attendees")
        recurrence_rule = _optional_str(args, "recurrence_rule") or None
        time_zone = _optional_str(args, "time_zone") or None
        try:
            event = await self._caldav.create_event(
                calendar_ref, summary, start, end,
                description, location, attendees,
                recurrence_rule=recurrence_rule,
                time_zone=time_zone,
            )
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", str(exc)) from exc
        return {"event": _wire_event(event, calendar_ref)}

    async def _handle_update_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """``calendar.events.update`` changes only the supplied VEVENT fields."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        event_ref = _require_str(args, "event_ref")
        target = _decode_event_target(event_ref)
        changes = _calendar_changes(args)
        try:
            event = await self._caldav.update_event(
                target.calendar_ref,
                target.event_id,
                recurrence_id=target.recurrence_id,
                href=target.href,
                **changes,
            )
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", str(exc)) from exc
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"event": _wire_event(event, target.calendar_ref)}

    async def _handle_delete_event(self, args: dict[str, Any]) -> dict[str, Any]:
        """``calendar.events.delete`` permanently removes a VEVENT."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        event_ref = _require_str(args, "event_ref")
        target = _decode_event_target(event_ref)
        try:
            await self._caldav.delete_event(
                target.calendar_ref,
                target.event_id,
                recurrence_id=target.recurrence_id,
                href=target.href,
            )
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"deleted": True}

    async def _handle_update_event_series(self, args: dict[str, Any]) -> dict[str, Any]:
        """Update every occurrence in a recurring series via its master."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        series_ref = _require_str(args, "series_ref")
        target = _decode_series_target(series_ref)
        changes = _calendar_changes(args, include_recurrence=True)
        try:
            event = await self._caldav.update_event_series(
                target.calendar_ref,
                target.event_id,
                href=target.href,
                **changes,
            )
        except ValueError as exc:
            raise RpcError("BAD_REQUEST", str(exc)) from exc
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"event": _wire_event(event, target.calendar_ref), "series_ref": series_ref}

    async def _handle_delete_event_series(self, args: dict[str, Any]) -> dict[str, Any]:
        """Permanently delete every occurrence in a recurring series."""
        if self._caldav is None:
            raise RpcError("BAD_REQUEST", "calendar not configured for this integration")
        series_ref = _require_str(args, "series_ref")
        target = _decode_series_target(series_ref)
        try:
            await self._caldav.delete_event_series(
                target.calendar_ref, target.event_id, href=target.href,
            )
        except LookupError as exc:
            raise RpcError("NOT_FOUND", str(exc)) from exc
        return {"deleted": True}


def _wire_calendar(calendar: Calendar) -> dict[str, str]:
    return {"name": calendar.name, "calendar_ref": calendar.url}


def _wire_event(event: Event, calendar_ref: str) -> dict[str, Any]:
    """Hide CalDAV routing details behind exact-occurrence and series refs."""
    result: dict[str, Any] = {
        "event_ref": encode_event_ref(
            provider="caldav",
            calendar_ref=calendar_ref,
            event_id=event.uid,
            recurrence_id=event.recurrence_id or None,
            href=event.href or None,
        ),
        "summary": event.summary,
        "start": event.start,
        "end": event.end,
        "location": event.location,
        "description": event.description,
        "is_recurring": event.recurring,
    }
    if event.recurring:
        result["series_ref"] = encode_series_ref(
            provider="caldav",
            calendar_ref=calendar_ref,
            event_id=event.uid,
            href=event.href or None,
        )
    return result


def _decode_event_target(value: str) -> CalendarTarget:
    try:
        return decode_event_ref(value, provider="caldav")
    except InvalidCalendarRef as exc:
        raise RpcError("BAD_REQUEST", str(exc)) from exc


def _decode_series_target(value: str) -> CalendarTarget:
    try:
        return decode_series_ref(value, provider="caldav")
    except InvalidCalendarRef as exc:
        raise RpcError("BAD_REQUEST", str(exc)) from exc


def _calendar_changes(
    args: dict[str, Any], *, include_recurrence: bool = False,
) -> dict[str, Any]:
    changes = {
        "summary": _optional_update_str(args, "summary"),
        "start": _optional_update_str(args, "start"),
        "end": _optional_update_str(args, "end"),
        "description": _optional_update_str(args, "description"),
        "location": _optional_update_str(args, "location"),
        "attendees": _optional_str_list(args, "attendees"),
    }
    if include_recurrence:
        changes["recurrence_rule"] = _optional_update_str(args, "recurrence_rule")
        changes["time_zone"] = _optional_update_str(args, "time_zone")
        if any(
            isinstance(changes[field], str) and "T" in changes[field]
            for field in ("start", "end")
        ) and changes["time_zone"] is None:
            raise RpcError(
                "BAD_REQUEST", "time_zone is required when changing a timed recurring series",
            )
    if not any(value is not None for value in changes.values()):
        raise RpcError("BAD_REQUEST", "update requires at least one field to change")
    return changes


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise RpcError("BAD_REQUEST", f"{key!r} required (non-empty string)")
    return value


def _require_int(args: dict[str, Any], key: str, *, default: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RpcError("BAD_REQUEST", f"{key!r} must be an integer")
    return value


def _optional_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key, "")
    if not isinstance(value, str):
        raise RpcError("BAD_REQUEST", f"{key!r} must be a string")
    return value


def _optional_update_str(args: dict[str, Any], key: str) -> str | None:
    if key not in args:
        return None
    value = args[key]
    if not isinstance(value, str):
        raise RpcError("BAD_REQUEST", f"{key!r} must be a string")
    return value


def _optional_str_list(args: dict[str, Any], key: str) -> list[str] | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise RpcError(
            "BAD_REQUEST", f"{key!r} must be an array of non-empty strings",
        )
    return list(value)


def _require_str_list(args: dict[str, Any], key: str) -> list[str]:
    """Require ``key`` to be a non-empty JSON array of non-empty strings."""
    value = args.get(key)
    if not isinstance(value, list) or not value:
        raise RpcError("BAD_REQUEST", f"{key!r} required (non-empty array of strings)")
    if not all(isinstance(v, str) and v for v in value):
        raise RpcError("BAD_REQUEST", f"{key!r} must contain non-empty strings")
    return list(value)


def _parse_outbound_attachments(value: Any) -> list[OutboundAttachment]:
    """Validate the optional ``attachments`` arg on ``email.messages.send``.

    Each item must be an object with ``filename`` (non-empty str),
    ``mime_type`` (non-empty str), and ``data_b64`` (str). Bytes are decoded
    once here so the SMTP client gets raw payload. Total raw size is capped
    at :data:`_MAX_OUTBOUND_ATTACHMENT_BYTES` — over that we refuse with
    BAD_REQUEST rather than try to send something the upstream will bounce.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise RpcError("BAD_REQUEST", "'attachments' must be an array")

    out: list[OutboundAttachment] = []
    total_bytes = 0
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise RpcError("BAD_REQUEST", f"'attachments[{i}]' must be an object")
        filename = item.get("filename")
        mime_type = item.get("mime_type")
        data_b64 = item.get("data_b64")
        if not isinstance(filename, str) or not filename:
            raise RpcError(
                "BAD_REQUEST",
                f"'attachments[{i}].filename' required (non-empty string)",
            )
        if not isinstance(mime_type, str) or not mime_type:
            raise RpcError(
                "BAD_REQUEST",
                f"'attachments[{i}].mime_type' required (non-empty string)",
            )
        if not isinstance(data_b64, str):
            raise RpcError(
                "BAD_REQUEST",
                f"'attachments[{i}].data_b64' required (string)",
            )
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RpcError(
                "BAD_REQUEST",
                f"'attachments[{i}].data_b64' invalid base64: {exc}",
            ) from exc
        total_bytes += len(data)
        if total_bytes > _MAX_OUTBOUND_ATTACHMENT_BYTES:
            cap_mb = _MAX_OUTBOUND_ATTACHMENT_BYTES // (1024 * 1024)
            raise RpcError(
                "BAD_REQUEST",
                f"attachments exceed {cap_mb}MB total raw",
            )
        out.append((filename, mime_type, data))
    return out


def _write_attachment(
    dir_path: Path, payload: bytes, filename: str, mime_type: str,
) -> Path:
    """Write ``payload`` to ``dir_path/<filename>``; dedupe collisions.

    Naming rules: keep the original filename when one was provided;
    append an 8-char hex suffix to the stem if a same-named file
    already exists; fall back to a uuid + mime extension when no
    filename was given.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    if not filename:
        ext = mimetypes.guess_extension(mime_type) or ""
        filename = f"{secrets.token_hex(16)}{ext}"
    dest = dir_path / filename
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        dest = dir_path / f"{stem}_{secrets.token_hex(4)}{suffix}"
    dest.write_bytes(payload)
    dest.chmod(ATTACHMENT_FILE_MODE)
    return dest
