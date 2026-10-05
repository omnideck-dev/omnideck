"""Built-in tool-integration presets.

Definitions are shared across consumers. Runtime process state and user
credentials belong to the supervisor, not to this catalog.
"""

from __future__ import annotations

import os

from brokering.drivers import BrokerDriver, HostPathBinding
from brokering.brokers.mcp_broker.catalog import MCP_DRIVER
from integrations.operations import OPERATIONS_BY_GROUP

from ._types import IntegrationCatalogEntry, OperationDisplayGroup

_EMAIL_DRIVER = BrokerDriver(
    id="native.email",
    command=("python", "-m", "brokering.brokers.email_broker"),
    env_injection={"email": "EMAIL_USER", "password": "EMAIL_PASS"},
    host_paths=(HostPathBinding(role="downloads", env_var="ATTACHMENTS_DIR", mode="write"),),
)

_GOOGLE_WORKSPACE_DRIVER = BrokerDriver(
    id="native.google_workspace",
    command=("python", "-m", "brokering.brokers.google_workspace_broker"),
    env_injection={
        "client_id": "OAUTH_CLIENT_ID",
        "client_secret": "OAUTH_CLIENT_SECRET",
        "access_token": "OAUTH_ACCESS_TOKEN",
        "refresh_token": "OAUTH_REFRESH_TOKEN",
        "token_uri": "OAUTH_TOKEN_URI",
        "scopes": "OAUTH_SCOPES",
        "expires_at": "OAUTH_EXPIRES_AT",
    },
    host_paths=(HostPathBinding(role="downloads", env_var="DOWNLOADS_DIR", mode="write"),),
)

_HTTP_DRIVER = BrokerDriver(
    id="native.http",
    command=("python", "-m", "brokering.brokers.http_broker"),
    env_injection={
        "base_url": "BASE_URL",
        "header_name": "AUTH_HEADER_NAME",
        "header_template": "AUTH_HEADER_TEMPLATE",
        "token": "TOKEN",
    },
    host_paths=(HostPathBinding(role="downloads", env_var="DOWNLOADS_DIR", mode="write"),),
)

_TEST_DRIVER = BrokerDriver(
    id="test.fake",
    command=("python", "-m", "brokering.brokers.test_broker"),
    env_injection={"token": "TEST_TOKEN"},
)

_EMAIL_GROUP = OperationDisplayGroup(
    id="email",
    title="Email",
    operation_ids=OPERATIONS_BY_GROUP["email"],
)
_CALENDAR_GROUP = OperationDisplayGroup(
    id="calendar",
    title="Calendar",
    operation_ids=OPERATIONS_BY_GROUP["calendar"],
)
_DRIVE_GROUP = OperationDisplayGroup(
    id="drive",
    title="Drive",
    operation_ids=OPERATIONS_BY_GROUP["drive"],
)
_CONTACTS_GROUP = OperationDisplayGroup(
    id="contacts",
    title="Contacts",
    operation_ids=OPERATIONS_BY_GROUP["contacts"],
)


_ICLOUD = IntegrationCatalogEntry(
    slug="icloud",
    title="iCloud",
    description="Email and calendar",
    category="Email & Calendar",
    driver=_EMAIL_DRIVER,
    operations=OPERATIONS_BY_GROUP["email"] | OPERATIONS_BY_GROUP["calendar"],
    operation_groups=(_EMAIL_GROUP, _CALENDAR_GROUP),
    driver_config={
        "IMAP_HOST": "imap.mail.me.com",
        "IMAP_PORT": "993",
        "SMTP_HOST": "smtp.mail.me.com",
        "SMTP_PORT": "587",
        "CALDAV_URL": "https://caldav.icloud.com",
    },
)

_GMAIL = IntegrationCatalogEntry(
    slug="gmail",
    title="Gmail",
    description="Email with an app password",
    category="Email & Calendar",
    driver=_EMAIL_DRIVER,
    operations=OPERATIONS_BY_GROUP["email"],
    operation_groups=(_EMAIL_GROUP,),
    driver_config={
        "IMAP_HOST": "imap.gmail.com",
        "IMAP_PORT": "993",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
    },
)

_HTTP = IntegrationCatalogEntry(
    slug="http",
    title="Custom HTTP API",
    description="Any REST endpoint with a static token",
    category="Custom",
    driver=_HTTP_DRIVER,
    operations=OPERATIONS_BY_GROUP["http"],
)

_TEST = IntegrationCatalogEntry(
    slug="test",
    title="Test Integration",
    description="Deterministic local integration for development and testing",
    category="Development",
    driver=_TEST_DRIVER,
    operations=OPERATIONS_BY_GROUP["test"],
    driver_config={
        "TEST_EXPECTED_TOKEN": "omnideck-test-token",
        "TEST_INITIAL_VALUE": "initial value",
    },
)

_GOOGLE_WORKSPACE = IntegrationCatalogEntry(
    slug="google_workspace",
    title="Google Workspace",
    description="Gmail, Calendar, Drive, and Contacts",
    category="Productivity Suites",
    driver=_GOOGLE_WORKSPACE_DRIVER,
    operation_groups=(_EMAIL_GROUP, _CALENDAR_GROUP, _DRIVE_GROUP, _CONTACTS_GROUP),
    scope_operations={
        "https://www.googleapis.com/auth/gmail.readonly": frozenset(
            {
                "email.mailboxes.list",
                "email.messages.list",
                "email.messages.search",
                "email.messages.get",
                "email.attachments.download",
            }
        ),
        "https://www.googleapis.com/auth/gmail.modify": OPERATIONS_BY_GROUP["email"],
        "https://www.googleapis.com/auth/calendar.readonly": frozenset(
            {
                "calendar.calendars.list",
                "calendar.events.list",
                "calendar.events.search",
            }
        ),
        "https://www.googleapis.com/auth/calendar.events": OPERATIONS_BY_GROUP["calendar"],
        "https://www.googleapis.com/auth/drive.readonly": frozenset(
            {
                "drive.files.list",
                "drive.files.search",
                "drive.files.get_metadata",
                "drive.files.export",
            }
        ),
        "https://www.googleapis.com/auth/drive.file": OPERATIONS_BY_GROUP["drive"],
        "https://www.googleapis.com/auth/contacts.readonly": OPERATIONS_BY_GROUP["contacts"],
    },
)


_STANDARD_CATALOG_ENTRIES: tuple[IntegrationCatalogEntry, ...] = (
    _ICLOUD,
    _GMAIL,
    _GOOGLE_WORKSPACE,
    _HTTP,
)

_MCP_ENTRIES = (
    IntegrationCatalogEntry(slug="slack", title="Slack", description="Search and work with your Slack workspace",
                            category="Communication", driver=MCP_DRIVER),
    IntegrationCatalogEntry(slug="mcp", title="MCP server", description="Connect tools from a remote service",
                            category="Custom", driver=MCP_DRIVER),
)

TEST_INTEGRATIONS_ENV = "OMNIDECK_ENABLE_TEST_INTEGRATIONS"


def test_integrations_enabled() -> bool:
    """Whether development-only integration catalog entries are enabled."""
    return os.environ.get(TEST_INTEGRATIONS_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_integration_catalog(*, include_test_integrations: bool | None = None) -> dict[str, IntegrationCatalogEntry]:
    """Build the process catalog, optionally including deterministic test entries."""
    include_test = test_integrations_enabled() if include_test_integrations is None else include_test_integrations
    entries = _STANDARD_CATALOG_ENTRIES + ((_TEST,) if include_test else ())
    # Do not offer consent until the runtime supplies its trusted host callback
    # address. Container-internal ports and arbitrary request Host headers are
    # not a safe substitute for the published desktop address.
    if os.environ.get("OMNIDECK_EXTERNAL_URL"):
        entries += _MCP_ENTRIES
    return {entry.slug: entry for entry in entries}


_DEFAULT_INTEGRATIONS = build_integration_catalog()


def integration_catalog() -> dict[str, IntegrationCatalogEntry]:
    """Return tool presets enabled for this process."""
    return dict(_DEFAULT_INTEGRATIONS)
