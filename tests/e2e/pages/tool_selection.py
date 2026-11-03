"""Shared skill/tool/integration picker and selected rows in both editors."""

import re

from playwright.sync_api import Page


class ToolSelection:
    def __init__(self, page: Page):
        self.page = page
        self.trigger = page.get_by_role("button", name="Add", exact=True)
        self.picker = page.get_by_role("dialog", name="Add skills and tools")

    def open(self):
        self.trigger.click()
        self.picker.wait_for(state="visible")
        return self

    def option(self, group, name):
        return self.picker.get_by_role("region", name=group, exact=True).get_by_role(
            "button", name=re.compile(r"^" + re.escape(name) + r"(?:\s|$)"),
        )

    def add(self, group, name):
        self.open().option(group, name).click()
        self.picker.wait_for(state="hidden")

    def row(self, kind, item_id):
        return self.page.get_by_test_id(f"selected-{kind}:{item_id}")
