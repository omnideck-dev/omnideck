"""POM for the Integrations tab and its modal setup flow."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class AddIntegrationFlow:
    """Modal settings subflow launched by the Add buttons.

    Step 1: integration picker — one card per catalog entry, each tagged
    ``provider-<slug>``.
    Step 2: concrete connection adapter.
    Step 3: exact operation picker.
    Step 4: review and finish.
    """

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("integration-setup-flow")

    def pick_provider(self, slug: str) -> "AddIntegrationFlow":
        self.page.get_by_test_id(f"provider-{slug}").click()
        return self

    def next_(self) -> "AddIntegrationFlow":
        self.page.get_by_test_id("wizard-next").click()
        return self

    @property
    def email_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-email")

    @property
    def password_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-password")

    @property
    def submit(self) -> Locator:
        """Connect button on the credentials step."""
        return self.page.get_by_test_id("wizard-submit")

    @property
    def done(self) -> Locator:
        """Add integration button on the Review step."""
        return self.page.get_by_test_id("wizard-done")

    @property
    def tools_heading(self) -> Locator:
        return self.page.get_by_text("Choose tools")

    # ── Token (http) flow fields ─────────────────────────────────────
    @property
    def base_url_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-base-url")

    @property
    def header_name_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-header-name")

    @property
    def header_template_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-header-template")

    @property
    def token_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-token")

    @property
    def label_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-label")

    def fill_http(
        self,
        *,
        base_url: str,
        token: str,
        label: str = "",
    ) -> "AddIntegrationFlow":
        """Fill the token-flow credentials step (assumes it's visible)."""
        self.base_url_input.fill(base_url)
        self.token_input.fill(token)
        if label:
            self.label_input.fill(label)
        return self

    def fill_test(
        self,
        *,
        token: str,
        label: str = "",
    ) -> "AddIntegrationFlow":
        """Fill the deterministic test-broker connection form."""
        self.token_input.fill(token)
        if label:
            self.label_input.fill(label)
        return self

    def cancel(self) -> None:
        """Exit before a connection has been registered."""
        self.page.get_by_role("button", name="Cancel").first.click()


class IntegrationsTab:
    """The Integrations tab inside Settings."""

    def __init__(self, page: Page):
        self.page = page
        self.add_flow = AddIntegrationFlow(page)

    # ── Empty / unavailable states ───────────────────────────────────
    @property
    def empty_state_heading(self) -> Locator:
        """Heading shown when no integrations are registered."""
        return self.page.get_by_text("Connect your first integration")

    @property
    def empty_state_add(self) -> Locator:
        """The CTA in the empty state — opens modal setup."""
        return self.page.get_by_test_id("integrations-add-first")

    @property
    def unavailable_heading(self) -> Locator:
        """Heading shown when the supervisor RPC is unreachable."""
        return self.page.get_by_text("Integrations unavailable")

    @property
    def retry_button(self) -> Locator:
        """The "Try again" button on the unavailable state."""
        return self.page.get_by_test_id("integrations-retry")

    # ── Modal setup launch ───────────────────────────────────────────
    def open_add_flow(self) -> AddIntegrationFlow:
        """Open setup from either the empty state or a populated list."""
        add_from_list = self.page.get_by_test_id("integrations-add-another")
        self.empty_state_add.or_(add_from_list).wait_for(state="visible")
        if self.empty_state_add.is_visible():
            return self.open_add_flow_from_empty()
        return self.open_add_flow_from_list()

    def open_add_flow_from_empty(self) -> AddIntegrationFlow:
        self.empty_state_add.click()
        self.add_flow.root.wait_for(state="visible")
        return self.add_flow

    def open_add_flow_from_list(self) -> AddIntegrationFlow:
        self.page.get_by_test_id("integrations-add-another").click()
        self.add_flow.root.wait_for(state="visible")
        return self.add_flow

    # ── List + detail (master-detail UI) ─────────────────────────────
    def row(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-row-{integration_id}")

    def open_detail(self, integration_id: str) -> None:
        """Click a row to open its detail tab group."""
        self.row(integration_id).click()

    def label_input(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-label-input-{integration_id}")

    def save_button(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-save-{integration_id}")

    def save_and_wait(self, integration_id: str) -> None:
        """Save an edit and wait for both persistence and the UI refresh."""
        integration_url = f"/api/integrations/{integration_id}"
        with (
            self.page.expect_response(
                lambda response: response.request.method == "PATCH"
                and response.url.endswith(integration_url),
            ) as saved,
            self.page.expect_response(
                lambda response: response.request.method == "GET"
                and response.url.rstrip("/").endswith("/api/integrations"),
            ) as refreshed,
        ):
            self.save_button(integration_id).click()
        assert saved.value.ok, saved.value.text()
        assert refreshed.value.ok, refreshed.value.text()

    def remove_button(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-remove-{integration_id}")

    @property
    def tools_tab(self) -> Locator:
        return self.page.get_by_test_id("integration-editor-tab-tools")

    @property
    def connection_tab(self) -> Locator:
        return self.page.get_by_test_id("integration-editor-tab-connection")

    def tool_checkbox(self, operation_id: str) -> Locator:
        return self.page.get_by_test_id(f"integration-tool-{operation_id}")

    def reconnect_button(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-reconnect-{integration_id}")
