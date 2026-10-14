"""Email broker: authenticated client candidates shared by startup and live updates."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from brokering._control import CredentialRejected
from brokering._env import capture_connection_fields, env_required, parse_bool
from brokering._perms import PROCESS_UMASK, disable_core_dumps
from brokering.brokers._common._runtime import run_integration_broker
from brokering.brokers.email_broker._caldav_client import CalDavAuthError, CalDavClient
from brokering.brokers.email_broker._imap_client import ImapAuthError, ImapClient
from brokering.brokers.email_broker._smtp_client import SmtpAuthError, SmtpClient
from brokering.brokers.email_broker._verbs import VerbDispatcher
from integrations.operation_grants import operation_grants_from_env

os.umask(PROCESS_UMASK)
disable_core_dumps()


@asynccontextmanager
async def create_session(connection_fields: dict[str, str], attachments_dir: Path) -> AsyncIterator[VerbDispatcher]:
    """Create an email session: dispatcher plus configured IMAP/SMTP/CalDAV clients.

    Authenticate before yielding; the exit stack closes clients on rejection,
    discard, replacement, or shutdown, including partially built sessions.
    """
    async with AsyncExitStack() as cleanup:
        imap = ImapClient(
            host=connection_fields["IMAP_HOST"], port=int(connection_fields["IMAP_PORT"]),
            user=connection_fields["EMAIL_USER"], password=connection_fields["EMAIL_PASS"],
            use_tls=parse_bool(connection_fields.get("IMAP_TLS", "true")),
        )
        cleanup.callback(imap.close)
        smtp = None
        caldav = None
        try:
            await imap.connect()
            if connection_fields.get("SMTP_HOST") and connection_fields.get("SMTP_PORT"):
                smtp = SmtpClient(
                    host=connection_fields["SMTP_HOST"], port=int(connection_fields["SMTP_PORT"]),
                    user=connection_fields["EMAIL_USER"], password=connection_fields["EMAIL_PASS"],
                    starttls=parse_bool(connection_fields.get("SMTP_STARTTLS", "true")),
                )
                cleanup.callback(smtp.close)
                await smtp.connect()
            if connection_fields.get("CALDAV_URL"):
                caldav = CalDavClient(
                    url=connection_fields["CALDAV_URL"], username=connection_fields["EMAIL_USER"], password=connection_fields["EMAIL_PASS"],
                )
                cleanup.callback(caldav.close)
                await caldav.connect()
        except (ImapAuthError, SmtpAuthError, CalDavAuthError) as exc:
            raise CredentialRejected("AUTH") from exc
        yield VerbDispatcher(
            imap=imap, smtp=smtp, caldav=caldav,
            operation_grants=frozenset(), attachments_dir=attachments_dir,
        )


async def _run() -> None:
    socket_path = Path(env_required("BROKER_SOCKET"))
    grants = operation_grants_from_env(env_required("OPERATION_GRANTS"))
    attachments_dir = Path(env_required("ATTACHMENTS_DIR"))
    connection_fields = capture_connection_fields(
        ("IMAP_HOST", "IMAP_PORT", "EMAIL_USER", "EMAIL_PASS"),
        ("IMAP_TLS", "SMTP_HOST", "SMTP_PORT", "SMTP_STARTTLS", "CALDAV_URL"),
    )
    await run_integration_broker(
        socket_path, connection_fields, grants,
        lambda candidate_fields: create_session(candidate_fields, attachments_dir),
    )

def main() -> None:
    """Run the broker; startup rejection uses the supervisor's auth exit code."""
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO,
        format=f"[email_broker[{env_required('INTEGRATION_ID')}]] %(asctime)s %(levelname)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except CredentialRejected as exc:
        sys.exit(77 if exc.code == "AUTH" else 1)
    except Exception as exc:
        # Upstream exceptions can contain tokens or passwords.
        logging.error("broker failed during startup or control handling (%s)", type(exc).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
