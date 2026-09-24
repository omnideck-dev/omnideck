"""Gmail operations via the Gmail API v1."""

from __future__ import annotations

import base64
import email.encoders
import email.message
import email.mime.base
import email.mime.multipart
import email.mime.text
import logging
from collections.abc import Callable
from functools import partial
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from integrations.brokers._email._mime import (
    BodyUnavailableError,
    MimePart,
    is_attachment,
    render_email_body,
)

logger = logging.getLogger(__name__)


class GmailClient:
    """Thin wrapper around the Gmail v1 API."""

    def __init__(self, creds: Credentials) -> None:
        self._creds = creds
        self._label_cache: dict[str, str] | None = None

    def _service(self):  # noqa: ANN202
        return build("gmail", "v1", credentials=self._creds, cache_discovery=False)

    def list_labels(self) -> list[dict[str, Any]]:
        """List all labels visible to the user."""
        resp = self._service().users().labels().list(userId="me").execute()
        labels = resp.get("labels", [])
        self._label_cache = {l["name"]: l["id"] for l in labels if "name" in l and "id" in l}
        return labels

    def _resolve_label_id(self, name: str) -> str:
        """Map a human-readable label name to its Gmail label ID."""
        if self._label_cache is None:
            self.list_labels()
        label_id = self._label_cache.get(name)
        if label_id is None:
            logger.warning("Gmail label %r not found, passing as-is", name)
            return name
        return label_id

    def list_messages(
        self,
        label_name: str = "INBOX",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent messages under a label, with headers."""
        label_id = self._resolve_label_id(label_name)
        message_ids = self._list_message_ids(label_ids=[label_id], limit=limit)
        return [self._get_metadata(mid) for mid in message_ids]

    def search_messages(
        self,
        query: str,
        label_name: str = "INBOX",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search messages with Gmail query syntax."""
        label_id = self._resolve_label_id(label_name)
        message_ids = self._list_message_ids(
            label_ids=[label_id], query=query, limit=limit,
        )
        return [self._get_metadata(mid) for mid in message_ids]

    def get_message(self, message_id: str) -> dict[str, Any]:
        """Fetch a full message with body and attachment metadata."""
        msg = (
            self._service().users().messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = _headers_dict(payload)
        body_loader = partial(self._load_body_part_data, msg["id"])
        return {
            "header": {
                "uid": msg["id"],
                "from_": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
            },
            "body_text": _extract_text_body(payload, body_loader=body_loader),
            "attachments": _list_attachments(msg["id"], payload),
        }

    def get_attachment(
        self, message_id: str, attachment_id: str,
    ) -> tuple[bytes, str, str]:
        """Download one attachment. Returns (bytes, filename, mime_type)."""
        data = self._download_part_data(message_id, attachment_id)
        filename, mime_type = self._find_attachment_meta(
            message_id, attachment_id,
        )
        return data, filename, mime_type

    def _download_part_data(self, message_id: str, attachment_id: str) -> bytes:
        """Download bytes stored separately from a Gmail message payload."""
        resp = (
            self._service().users().messages().attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = _decode_base64url(resp["data"])
        if data is None:
            raise ValueError("Gmail returned invalid base64url part data")
        return data

    def _load_body_part_data(self, message_id: str, attachment_id: str) -> bytes:
        """Load an inline body part, marking corrupt data as a failed candidate."""
        try:
            return self._download_part_data(message_id, attachment_id)
        except ValueError as exc:
            raise BodyUnavailableError(str(exc)) from exc

    def _find_attachment_meta(
        self, message_id: str, attachment_id: str,
    ) -> tuple[str, str]:
        """Look up filename and mime_type for an attachment ID."""
        msg = (
            self._service().users().messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        for part in _walk_parts(msg.get("payload", {})):
            body = part.get("body", {})
            if body.get("attachmentId") == attachment_id:
                return (
                    part.get("filename", ""),
                    part.get("mimeType", "application/octet-stream"),
                )
        return ("", "application/octet-stream")

    # --- write operations -----------------------------------------------------

    def send_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        """Send an email. Returns the Gmail message ID.

        Args:
            to: Recipient addresses.
            subject: Subject line.
            body: Plain-text body.
            attachments: Optional list of ``{filename, mime_type, data_b64}`` dicts.
        """
        if attachments:
            msg = email.mime.multipart.MIMEMultipart()
            msg.attach(email.mime.text.MIMEText(body, "plain"))
            for att in attachments:
                part = email.mime.base.MIMEBase(*att["mime_type"].split("/", 1))
                part.set_payload(base64.b64decode(att["data_b64"]))
                email.encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", "attachment",
                    filename=att.get("filename", "attachment"),
                )
                msg.attach(part)
        else:
            msg = email.mime.text.MIMEText(body, "plain")

        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        result = (
            self._service().users().messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        return result.get("id", "")

    def move_messages(
        self,
        folder: str,
        uids: list[str],
        dest_folder: str,
    ) -> None:
        """Move messages from one label to another.

        Translates the IMAP-style folder/move semantics into Gmail
        label add/remove operations.
        """
        remove_id = self._resolve_label_id(folder)
        add_id = self._resolve_label_id(dest_folder)
        for uid in uids:
            self._service().users().messages().modify(
                userId="me",
                id=uid,
                body={
                    "addLabelIds": [add_id],
                    "removeLabelIds": [remove_id],
                },
            ).execute()

    # --- internal helpers ----------------------------------------------------

    def _list_message_ids(
        self,
        *,
        label_ids: list[str] | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[str]:
        """Paginated message ID fetch."""
        results: list[str] = []
        page_token: str | None = None
        while len(results) < limit:
            page_size = min(limit - len(results), 100)
            kwargs: dict[str, Any] = {
                "userId": "me",
                "maxResults": page_size,
            }
            if label_ids:
                kwargs["labelIds"] = label_ids
            if query:
                kwargs["q"] = query
            if page_token:
                kwargs["pageToken"] = page_token

            resp = self._service().users().messages().list(**kwargs).execute()
            for m in resp.get("messages", []):
                results.append(m["id"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results[:limit]

    def _get_metadata(self, message_id: str) -> dict[str, Any]:
        """Fetch just the envelope headers for one message."""
        msg = (
            self._service().users().messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        headers = _headers_dict(msg.get("payload", {}))
        return {
            "uid": msg["id"],
            "from_": headers.get("From", ""),
            "to": headers.get("To", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
        }


def _headers_dict(payload: dict[str, Any]) -> dict[str, str]:
    """Extract headers list into a name→value dict."""
    return {
        h["name"]: h["value"]
        for h in payload.get("headers", [])
        if "name" in h and "value" in h
    }


def _extract_text_body(
    payload: dict[str, Any],
    *,
    body_loader: Callable[[str], bytes] | None = None,
) -> str:
    """Render the best readable body from a Gmail API MIME payload.

    The optional loader may perform provider I/O for large inline body parts.
    ``BodyUnavailableError`` rejects only that MIME candidate so an earlier
    alternative can be tried; network and other provider errors propagate.
    """
    return render_email_body(_gmail_payload_to_mime_part(payload, body_loader=body_loader))


def _gmail_payload_to_mime_part(
    payload: dict[str, Any],
    *,
    body_loader: Callable[[str], bytes] | None = None,
) -> MimePart:
    """Adapt a Gmail API message part to the provider-neutral MIME model."""
    metadata = _gmail_part_metadata(payload)

    body_block = payload.get("body", {})
    body_data = body_block.get("data")
    body = _decode_base64url(body_data) if isinstance(body_data, str) else None
    attachment_id = body_block.get("attachmentId")
    lazy_body_loader: Callable[[], bytes] | None = None
    if body is None and isinstance(attachment_id, str) and body_loader is not None:
        lazy_body_loader = partial(body_loader, attachment_id)
    related_start = metadata.get_param("start", header="content-type")
    filename = payload.get("filename") or metadata.get_filename()
    return MimePart(
        content_type=str(payload.get("mimeType") or metadata.get_content_type()),
        body=body,
        body_loader=lazy_body_loader,
        charset=metadata.get_content_charset(),
        disposition=metadata.get_content_disposition(),
        filename=str(filename) if filename else None,
        content_id=_part_header(payload, "Content-ID") or None,
        related_start=related_start if isinstance(related_start, str) else None,
        children=tuple(
            _gmail_payload_to_mime_part(part, body_loader=body_loader)
            for part in payload.get("parts", [])
            if isinstance(part, dict)
        ),
    )


def _part_header(payload: dict[str, Any], wanted_name: str) -> str:
    for header in payload.get("headers", []):
        if (
            isinstance(header, dict)
            and str(header.get("name", "")).casefold() == wanted_name.casefold()
        ):
            return str(header.get("value", ""))
    return ""


def _gmail_part_metadata(payload: dict[str, Any]) -> email.message.Message:
    """Parse MIME headers without traversing or decoding a Gmail part."""
    metadata = email.message.Message()
    content_type_header = _part_header(payload, "Content-Type")
    disposition_header = _part_header(payload, "Content-Disposition")
    if content_type_header:
        metadata["Content-Type"] = content_type_header
    if disposition_header:
        metadata["Content-Disposition"] = disposition_header
    return metadata


def _decode_base64url(data: str) -> bytes | None:
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return None


def _list_attachments(
    message_id: str, payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect attachment metadata from MIME parts."""
    attachments: list[dict[str, Any]] = []
    for part in _walk_parts(payload):
        body = part.get("body", {})
        metadata = _gmail_part_metadata(part)
        filename = part.get("filename") or metadata.get_filename()
        if body.get("attachmentId") and is_attachment(
            metadata.get_content_disposition(),
            str(filename) if filename else None,
        ):
            attachments.append({
                "id": body["attachmentId"],
                "filename": part.get("filename", ""),
                "mime_type": part.get("mimeType", "application/octet-stream"),
                "size": body.get("size", 0),
            })
    return attachments


def _walk_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the nested MIME part tree into a list."""
    parts: list[dict[str, Any]] = []
    for part in payload.get("parts", []):
        parts.append(part)
        parts.extend(_walk_parts(part))
    return parts
