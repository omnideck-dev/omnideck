"""Filling and submitting a form — the core interaction the tools exist for.

An agent lands on a signup page and has to complete it: type into text,
email, and password fields, choose from a ``<select>``, tick the required
consent box, and submit. This exercises ``browse_page`` element discovery,
``fill_field``, ``select_option``, and ``click`` against a real form, and
checks the page reacts to what was entered.
"""

from __future__ import annotations

from tools.browser.interactions import click, fill_field
from tools.browser.select import select_option
from tools.browser.snapshot_tool import browse_page

from ._helpers import find_ref


async def test_browse_page_lists_every_form_control(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/forms/signup.html")
    view = await browse_page(tab=tab)

    assert find_ref(view, role="textbox", name="Full name") is not None
    assert find_ref(view, role="textbox", name="Email address") is not None
    assert find_ref(view, role="textbox", name="Password") is not None
    assert find_ref(view, role="combobox", name="Country") is not None
    assert find_ref(view, role="checkbox", name="Subscribe to the newsletter") is not None
    assert find_ref(view, role="checkbox", name="I accept the terms of service") is not None
    assert find_ref(view, role="button", name="Create account") is not None


async def test_complete_and_submit_signup(browser_session, servers):
    tab = await browser_session.open(f"{servers.primary}/forms/signup.html")
    view = await browse_page(tab=tab)

    # Refs stay stable while the form structure is unchanged, so resolve them
    # once from the initial snapshot and drive the whole flow.
    name_ref = find_ref(view, role="textbox", name="Full name")
    email_ref = find_ref(view, role="textbox", name="Email address")
    password_ref = find_ref(view, role="textbox", name="Password")
    country_ref = find_ref(view, role="combobox", name="Country")
    newsletter_ref = find_ref(view, role="checkbox", name="Subscribe to the newsletter")
    terms_ref = find_ref(view, role="checkbox", name="I accept the terms of service")
    submit_ref = find_ref(view, role="button", name="Create account")
    assert None not in (
        name_ref, email_ref, password_ref, country_ref,
        newsletter_ref, terms_ref, submit_ref,
    )

    # Each interaction is verified by the value/state it leaves in the snapshot.
    view = await fill_field(name_ref, "Jane Doe", tab=tab)
    assert "Full name = Jane Doe" in view
    view = await fill_field(email_ref, "jane@example.com", tab=tab)
    assert "Email address = jane@example.com" in view
    view = await fill_field(password_ref, "hunter2!", tab=tab)
    assert "Password = hunter2!" in view

    view = await select_option(country_ref, "United States", tab=tab)
    assert "Country = United States" in view

    view = await click(newsletter_ref, tab=tab)
    assert "Subscribe to the newsletter (checked)" in view
    view = await click(terms_ref, tab=tab)
    assert "I accept the terms of service (checked)" in view

    view = await click(submit_ref, tab=tab)
    # The page consumed every field: the confirmation echoes the email, the
    # selected country value, and the newsletter checkbox state.
    assert "Account created for jane@example.com (us), newsletter=true" in view
