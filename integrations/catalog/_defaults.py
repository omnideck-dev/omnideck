"""Built-in integration and model-provider presets.

Definitions are shared across consumers. Runtime process state and user
credentials belong to the supervisor, not to this catalog.
"""

from __future__ import annotations

import os
from typing import Literal

from integrations.drivers import BrokerDriver, HostPathBinding
from integrations.operations import OPERATIONS_BY_GROUP

from ._types import CatalogEntry, IntegrationCatalogEntry, ModelProviderCatalogEntry, OperationDisplayGroup

_EMAIL_DRIVER = BrokerDriver(
    id="native.email",
    command=("python", "-m", "integrations.brokers.email_broker"),
    env_injection={"email": "EMAIL_USER", "password": "EMAIL_PASS"},
    host_paths=(HostPathBinding(role="downloads", env_var="ATTACHMENTS_DIR", mode="write"),),
)

_GOOGLE_WORKSPACE_DRIVER = BrokerDriver(
    id="native.google_workspace",
    command=("python", "-m", "integrations.brokers.google_workspace_broker"),
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
    command=("python", "-m", "integrations.brokers.http_broker"),
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
    command=("python", "-m", "integrations.brokers.test_broker"),
    env_injection={"token": "TEST_TOKEN"},
)

_LLM_PROXY_DRIVER = BrokerDriver(
    id="model_provider.http_proxy",
    command=("python", "-m", "integrations.brokers.llm_proxy"),
    env_injection={"api_key": "LLM_API_KEY"},
)

_LLM_OPENAI_COMPAT_DRIVER = BrokerDriver(
    id="model_provider.openai_compatible_proxy",
    command=("python", "-m", "integrations.brokers.llm_proxy"),
    env_injection={"api_key": "LLM_API_KEY", "base_url": "LLM_BASE_URL"},
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


def _provider(
    slug: str,
    title: str,
    protocol: Literal["openai", "anthropic"],
    config: dict[str, str],
    *,
    driver: BrokerDriver = _LLM_PROXY_DRIVER,
) -> ModelProviderCatalogEntry:
    return ModelProviderCatalogEntry(
        slug=slug,
        title=title,
        provider_protocol=protocol,
        driver=driver,
        driver_config=config,
    )


_LLM_OPENAI = _provider(
    "llm_openai",
    "OpenAI API",
    "openai",
    {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://api.openai.com"},
)
_LLM_ANTHROPIC = _provider(
    "llm_anthropic",
    "Anthropic API",
    "anthropic",
    {"LLM_PROVIDER": "anthropic", "LLM_BASE_URL": "https://api.anthropic.com"},
)
_LLM_OPENROUTER = _provider(
    "llm_openrouter",
    "OpenRouter",
    "openai",
    {"LLM_PROVIDER": "openai", "LLM_BASE_URL": "https://openrouter.ai/api"},
)
_LLM_OPENAI_COMPAT = _provider(
    "llm_openai_compat",
    "OpenAI-compatible",
    "openai",
    {"LLM_PROVIDER": "openai"},
    driver=_LLM_OPENAI_COMPAT_DRIVER,
)


_STANDARD_CATALOG_ENTRIES: tuple[CatalogEntry, ...] = (
    _ICLOUD,
    _GMAIL,
    _GOOGLE_WORKSPACE,
    _HTTP,
    _LLM_OPENAI,
    _LLM_ANTHROPIC,
    _LLM_OPENROUTER,
    _LLM_OPENAI_COMPAT,
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


def build_default_catalog(*, include_test_integrations: bool | None = None) -> dict[str, CatalogEntry]:
    """Build the process catalog, optionally including deterministic test entries."""
    include_test = test_integrations_enabled() if include_test_integrations is None else include_test_integrations
    entries = _STANDARD_CATALOG_ENTRIES + ((_TEST,) if include_test else ())
    return {entry.slug: entry for entry in entries}


DEFAULT_CATALOG: dict[str, CatalogEntry] = build_default_catalog()


def integration_catalog() -> dict[str, IntegrationCatalogEntry]:
    return {slug: entry for slug, entry in DEFAULT_CATALOG.items() if isinstance(entry, IntegrationCatalogEntry)}


def model_provider_catalog() -> dict[str, ModelProviderCatalogEntry]:
    return {slug: entry for slug, entry in DEFAULT_CATALOG.items() if isinstance(entry, ModelProviderCatalogEntry)}
