"""Per-slug catalog used to spawn the broker for each integration.

A minimal in-Python table for now — later this loads from
``config/integrations_catalog/*.json`` at supervisor startup. Tests inject a
custom catalog so they can point broker spawn commands at the ``fake_email``
fixture's random ports.

One broker process per integration: whether the integration serves email,
calendar, both, or an MCP server, it's a single subprocess with one UDS
socket. See the ``CatalogEntry`` fields below for the spawn surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrations.permissions import Access, Capability, Permissions
from integrations.supervisor.types import HostPath, HostPathBinding


@dataclass(frozen=True)
class CatalogEntry:
    """Per-slug description of how to spawn the broker for an integration."""

    slug: str
    """Identifier matching the ``slug`` in ``<id>.meta`` files and in user-facing
    catalog pickers (e.g. ``"icloud"``, ``"gmail"``, ``"github"``)."""

    command: list[str]
    """The argv to exec for the broker subprocess
    (e.g. ``["python", "-m", "integrations.brokers.email_broker"]``)."""

    capabilities: dict[Capability, Access] = field(default_factory=dict)
    """Per-capability maximum access level for static providers (app-password
    integrations where the credential grants everything). Each capability
    corresponds to a family of agent tools."""

    static_env: dict[str, str] = field(default_factory=dict)
    """Env vars the supervisor provides directly — protocol hosts, ports, etc.
    Not derived from the user's credential blob."""

    env_injection: dict[str, str] = field(default_factory=dict)
    """Maps secret-bundle keys to env-var names. For example
    ``{"email": "EMAIL_USER", "password": "EMAIL_PASS"}`` means the supervisor
    reads ``email`` and ``password`` from the decrypted bundle and sets the
    corresponding env vars when it spawns the broker for this slug."""

    host_paths: tuple[HostPathBinding, ...] = ()
    """Shared directories on the container filesystem this integration's broker
    consumes. Each binding names a role in the supervisor's host-path registry,
    the env var the broker subprocess expects, and the access mode (read or
    write). Empty for integrations that don't touch shared state — the MCP
    broker, for example."""

    scope_capabilities: dict[str, tuple[Capability, Access]] = field(default_factory=dict)
    """Maps OAuth scope URIs to ``(capability, max_access)`` pairs. When
    non-empty, the per-integration max access is derived from the granted
    scopes in the auth blob instead of from the static ``capabilities``
    field. For each capability, the highest access level among all matching
    granted scopes wins."""

    injects_path_prefix: bool = False
    """When set, the spawn path always sets ``PATH_PREFIX`` from the secret
    bundle's optional ``path_prefix`` field (empty string when absent) —
    used by CLI-exec brokers to enforce folder-scoped secrets from inside
    the broker, not just at the tool-visibility layer."""

    redact_secret_env: bool = False
    """When set, the spawn path records which env-var names carry secret
    values (from ``env_injection`` and, for dynamic-spawn entries, the
    bundle's ``vars``) into ``SECRET_ENV_KEYS`` (a JSON list) — used by
    CLI-exec brokers to know which values to scrub from a child process's
    stdout/stderr before returning it over RPC."""

    dynamic_spawn: bool = False
    """When set, the command binary and injected env vars come from the
    secret bundle itself instead of this entry's ``static_env`` /
    ``env_injection`` — the bundle's ``command`` (list[str]) picks the
    binary/args and its ``vars`` (dict[str, str]) become injected env vars.
    Used for user-defined CLI integrations where the catalog can't know the
    binary or var names ahead of time. See ``_spawn.py`` for validation."""

    def resolve_capabilities(self, auth_blob: dict | None = None) -> dict[Capability, Access]:
        """Derive the max access level per capability for one integration.

        For static providers (iCloud, Gmail) returns ``self.capabilities``
        unchanged. For OAuth providers with ``scope_capabilities`` set,
        inspects the auth blob's ``"scopes"`` field and returns the highest
        granted access level per capability.
        """
        if not self.scope_capabilities or auth_blob is None:
            return dict(self.capabilities)
        granted = set((auth_blob.get("scopes") or "").split())
        ceiling: dict[Capability, Access] = {}
        for scope, (cap, access) in self.scope_capabilities.items():
            if scope in granted:
                ceiling[cap] = max(ceiling.get(cap, Access.OFF), access)
        return ceiling


_EMAIL_HOST_PATHS = (
    # Email attachments land in the shared "downloads" role alongside browser
    # saves: both are agent-initiated retrievals from outside the container.
    HostPathBinding(role="downloads", env_var="ATTACHMENTS_DIR", mode="write"),
)


_ICLOUD = CatalogEntry(
    slug="icloud",
    command=["python", "-m", "integrations.brokers.email_broker"],
    capabilities={
        Capability.EMAIL: Access.READ_WRITE,
        Capability.CALENDAR: Access.READ_WRITE,
    },
    static_env={
        "IMAP_HOST": "imap.mail.me.com",
        "IMAP_PORT": "993",
        "SMTP_HOST": "smtp.mail.me.com",
        "SMTP_PORT": "587",
        # CalDAV root — broker resolves the user's principal from here.
        # Same app-specific password authenticates IMAP and CalDAV.
        "CALDAV_URL": "https://caldav.icloud.com",
    },
    env_injection={
        "email": "EMAIL_USER",
        "password": "EMAIL_PASS",
    },
    host_paths=_EMAIL_HOST_PATHS,
)


_GMAIL = CatalogEntry(
    slug="gmail",
    command=["python", "-m", "integrations.brokers.email_broker"],
    capabilities={Capability.EMAIL: Access.READ_WRITE},
    static_env={
        "IMAP_HOST": "imap.gmail.com",
        "IMAP_PORT": "993",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
    },
    env_injection={
        "email": "EMAIL_USER",
        "password": "EMAIL_PASS",
    },
    host_paths=_EMAIL_HOST_PATHS,
)


_LLM_OPENAI = CatalogEntry(
    slug="llm_openai",
    command=["python", "-m", "integrations.brokers.llm_proxy"],
    capabilities={Capability.LLM_PROXY: Access.READ_WRITE},
    static_env={
        "LLM_PROVIDER": "openai",
        "LLM_BASE_URL": "https://api.openai.com",
    },
    env_injection={"api_key": "LLM_API_KEY"},
    host_paths=(),
)

_LLM_ANTHROPIC = CatalogEntry(
    slug="llm_anthropic",
    command=["python", "-m", "integrations.brokers.llm_proxy"],
    capabilities={Capability.LLM_PROXY: Access.READ_WRITE},
    static_env={
        "LLM_PROVIDER": "anthropic",
        "LLM_BASE_URL": "https://api.anthropic.com",
    },
    env_injection={"api_key": "LLM_API_KEY"},
    host_paths=(),
)

_LLM_OPENROUTER = CatalogEntry(
    slug="llm_openrouter",
    command=["python", "-m", "integrations.brokers.llm_proxy"],
    capabilities={Capability.LLM_PROXY: Access.READ_WRITE},
    static_env={
        "LLM_PROVIDER": "openai",
        "LLM_BASE_URL": "https://openrouter.ai/api",
    },
    env_injection={"api_key": "LLM_API_KEY"},
    host_paths=(),
)

_LLM_OPENAI_COMPAT = CatalogEntry(
    slug="llm_openai_compat",
    command=["python", "-m", "integrations.brokers.llm_proxy"],
    capabilities={Capability.LLM_PROXY: Access.READ_WRITE},
    static_env={"LLM_PROVIDER": "openai"},
    env_injection={"api_key": "LLM_API_KEY", "base_url": "LLM_BASE_URL"},
    host_paths=(),
)

_HTTP = CatalogEntry(
    slug="http",
    command=["python", "-m", "integrations.brokers.http_broker"],
    capabilities={Capability.HTTP: Access.READ_WRITE},
    static_env={},
    env_injection={
        # Base URL the broker scopes every request to. All paths resolve
        # against this and the resolved host must match — that's the only
        # thing keeping a prompt-injected agent from pointing the token
        # at an attacker-controlled URL.
        "base_url": "BASE_URL",
        # Header name to attach the token under. Broker defaults to
        # "Authorization" when absent.
        "header_name": "AUTH_HEADER_NAME",
        # Template for the header value; the literal "{token}" placeholder is
        # substituted with the secret. Broker defaults to "Bearer {token}".
        "header_template": "AUTH_HEADER_TEMPLATE",
        "token": "TOKEN",
    },
    host_paths=(
        HostPathBinding(role="downloads", env_var="DOWNLOADS_DIR", mode="write"),
    ),
)


_CLI_EXEC_HOST_PATHS = (
    # CLI-exec brokers cd into a caller-supplied path under here to run the
    # target binary and to enforce PATH_PREFIX — same workspace root
    # run_bash_cmd already uses, so folder scoping means the same thing in
    # both places.
    HostPathBinding(role="workspace", env_var="HOME_DIR", mode="read"),
)

_CLI = CatalogEntry(
    slug="cli",
    command=["python", "-m", "integrations.brokers.exec_broker"],
    capabilities={Capability.CLI: Access.READ},
    injects_path_prefix=True,
    redact_secret_env=True,
    dynamic_spawn=True,
    host_paths=_CLI_EXEC_HOST_PATHS,
)


_GOOGLE_WORKSPACE = CatalogEntry(
    slug="google_workspace",
    command=["python", "-m", "integrations.brokers.google_workspace_broker"],
    static_env={},
    env_injection={
        "client_id": "OAUTH_CLIENT_ID",
        "client_secret": "OAUTH_CLIENT_SECRET",
        "access_token": "OAUTH_ACCESS_TOKEN",
        "refresh_token": "OAUTH_REFRESH_TOKEN",
        "token_uri": "OAUTH_TOKEN_URI",
        "scopes": "OAUTH_SCOPES",
        "expires_at": "OAUTH_EXPIRES_AT",
    },
    scope_capabilities={
        "https://www.googleapis.com/auth/gmail.readonly": (Capability.EMAIL, Access.READ),
        "https://www.googleapis.com/auth/gmail.modify": (Capability.EMAIL, Access.READ_WRITE),
        "https://www.googleapis.com/auth/calendar.readonly": (Capability.CALENDAR, Access.READ),
        "https://www.googleapis.com/auth/calendar.events": (Capability.CALENDAR, Access.READ_WRITE),
        "https://www.googleapis.com/auth/drive.readonly": (Capability.DRIVE, Access.READ),
        "https://www.googleapis.com/auth/drive.file": (Capability.DRIVE, Access.READ_WRITE),
        "https://www.googleapis.com/auth/contacts.readonly": (Capability.CONTACTS, Access.READ),
    },
    host_paths=(
        HostPathBinding(role="downloads", env_var="DOWNLOADS_DIR", mode="write"),
    ),
)


DEFAULT_CATALOG: dict[str, CatalogEntry] = {
    "icloud": _ICLOUD,
    "gmail": _GMAIL,
    "llm_openai": _LLM_OPENAI,
    "llm_anthropic": _LLM_ANTHROPIC,
    "llm_openrouter": _LLM_OPENROUTER,
    "llm_openai_compat": _LLM_OPENAI_COMPAT,
    "google_workspace": _GOOGLE_WORKSPACE,
    "http": _HTTP,
    "cli": _CLI,
}


def validate_host_path_bindings(
    catalog: dict[str, CatalogEntry],
    host_paths: dict[str, HostPath],
) -> None:
    """Fail fast if any catalog entry references a role the registry doesn't define.

    Run once at supervisor startup so a typo in a catalog entry's
    ``host_paths`` trips the boot rather than the first user trying to add
    an integration. The spawn path checks the same condition defensively —
    this is just for clearer failure timing.
    """
    for slug, entry in catalog.items():
        for binding in entry.host_paths:
            if binding.role not in host_paths:
                msg = (
                    f"catalog entry {slug!r} binds host-path role "
                    f"{binding.role!r} which is not in the registry"
                )
                raise ValueError(msg)
