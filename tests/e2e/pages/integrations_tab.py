"""POM for the Integrations tab inside Settings + the Add modal wizard."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class AddIntegrationModal:
    """Multi-step wizard launched by the Add buttons.

    Step 1: provider picker — one card per catalog entry, each tagged
    ``provider-<slug>``.
    Step 2: explainer — has a ``Next`` button (testid ``wizard-next``).
    Step 3: credentials form — email + app password + Verify button.
    Step 4: verifying spinner / success page.
    """

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        """The modal heading — anchors waits for "is the modal open?"."""
        return self.page.get_by_text("ADD INTEGRATION", exact=True)

    def pick_provider(self, slug: str) -> "AddIntegrationModal":
        """Click a provider card on step 1 and advance to the explainer."""
        self.page.get_by_test_id(f"provider-{slug}").click()
        return self

    def next_(self) -> "AddIntegrationModal":
        """Advance from the explainer to the credentials step."""
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
        """Verify & save button on the credentials step."""
        return self.page.get_by_test_id("wizard-submit")

    @property
    def done(self) -> Locator:
        """Done button on the success screen."""
        return self.page.get_by_test_id("wizard-done")

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
    ) -> "AddIntegrationModal":
        """Fill the token-flow credentials step (assumes it's visible)."""
        self.base_url_input.fill(base_url)
        self.token_input.fill(token)
        if label:
            self.label_input.fill(label)
        return self

    # ── CLI-exec flow fields ──────────────────────────────────────────
    @property
    def cli_command_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-cli-command")

    def cli_var_name_input(self, idx: int = 0) -> Locator:
        return self.page.get_by_test_id(f"wizard-cli-var-name-{idx}")

    def cli_var_value_input(self, idx: int = 0) -> Locator:
        return self.page.get_by_test_id(f"wizard-cli-var-value-{idx}")

    @property
    def cli_add_var(self) -> Locator:
        return self.page.get_by_test_id("wizard-cli-add-var")

    @property
    def cli_path_prefix_input(self) -> Locator:
        return self.page.get_by_test_id("wizard-cli-path-prefix")

    def fill_cli(
        self,
        *,
        command: str,
        var_name: str,
        var_value: str,
        label: str = "",
    ) -> "AddIntegrationModal":
        """Fill the CLI-exec credentials step (assumes it's visible)."""
        self.cli_command_input.fill(command)
        self.cli_var_name_input().fill(var_name)
        self.cli_var_value_input().fill(var_value)
        if label:
            self.label_input.fill(label)
        return self

    def cancel(self) -> None:
        """Close via the footer Cancel link."""
        self.page.get_by_role("button", name="Cancel").first.click()


class IntegrationsTab:
    """The Integrations tab inside Settings."""

    def __init__(self, page: Page):
        self.page = page
        self.add_modal = AddIntegrationModal(page)

    # ── Empty / unavailable states ───────────────────────────────────
    @property
    def empty_state_heading(self) -> Locator:
        """Heading shown when no integrations are registered."""
        return self.page.get_by_text("Connect your first integration")

    @property
    def empty_state_add(self) -> Locator:
        """The CTA in the empty state — opens the Add modal."""
        return self.page.get_by_test_id("integrations-add-first")

    @property
    def unavailable_heading(self) -> Locator:
        """Heading shown when the supervisor RPC is unreachable."""
        return self.page.get_by_text("Integrations unavailable")

    @property
    def retry_button(self) -> Locator:
        """The "Try again" button on the unavailable state."""
        return self.page.get_by_test_id("integrations-retry")

    # ── Add modal launch ─────────────────────────────────────────────
    def open_add_modal_from_empty(self) -> AddIntegrationModal:
        """Click the empty-state CTA to open the Add modal."""
        self.empty_state_add.click()
        self.add_modal.root.wait_for(state="visible")
        return self.add_modal

    def open_add_modal_from_list(self) -> AddIntegrationModal:
        """Click the in-list ADD button (only present when the list isn't empty)."""
        self.page.get_by_test_id("integrations-add-another").click()
        self.add_modal.root.wait_for(state="visible")
        return self.add_modal

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

    def remove_button(self, integration_id: str) -> Locator:
        return self.page.get_by_test_id(f"integrations-remove-{integration_id}")
