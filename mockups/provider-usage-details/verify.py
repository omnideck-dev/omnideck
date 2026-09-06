"""Review actual Details components with sample usage, using Vite on port 5192.

Run: uv run python mockups/provider-usage-details/verify.py
No LLM calls or persistent conversation data are used.
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUTPUT = Path(__file__).parent / "screenshots"
HTML = """<html data-theme="dark"><head><script type="module">
import RefreshRuntime from '/@react-refresh';
RefreshRuntime.injectIntoGlobalHook(window);
window.$RefreshReg$ = () => {};
window.$RefreshSig$ = () => (type) => type;
window.__vite_plugin_react_preamble_installed__ = true;
</script></head><body><div id="review-root"></div></body></html>"""
MOUNT = """async () => {
    const React = (await import('/node_modules/.vite/deps/react.js')).default;
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
    const { default: Header } = await import('/src/features/conversation/details/ConversationHeader.jsx');
    const { buildConversationDetails } = await import('/src/features/conversation/details/conversationDetailsModel.js');
    const { default: styles } = await import('/src/components/ChatPanel.module.css');
    await import('/src/global.css');
    await import('/node_modules/bootstrap-icons/font/bootstrap-icons.css');
    const source = {
        conversationId: 'usage-review', rootId: 'root',
        turns: [{ children: [{ kind: 'file_output', path: '/workshop.docx' }] }],
        agents: {
            root: { id: 'root', parentId: null, usageByIteration: {
                0: { prompt_tokens: 48000, completion_tokens: 9600, cache_read_tokens: 32000, cache_creation_tokens: 8000, reported_cost_usd: 0.18 }
            }, contextUsage: { context_used: 46000, context_limit: 100000, compaction_threshold: 0.75 } },
            analyst: { id: 'analyst', parentId: 'root', name: 'Research analyst', status: 'success', usageByIteration: {
                0: { prompt_tokens: 20000, completion_tokens: 4000, cache_read_tokens: 12000, reported_cost_usd: 0.06 }
            } },
            reviewer: { id: 'reviewer', parentId: 'root', name: 'Reviewer', status: 'success', usageByIteration: {
                0: { prompt_tokens: 8000, completion_tokens: 1600 }
            } }
        }
    };
    const h = React.createElement;
    createRoot(document.getElementById('review-root')).render(
        h('div', { style: { padding: 16, height: '100vh', background: 'var(--canvas)' } },
            h('p', { style: { margin: '0 0 14px', color: 'var(--text-secondary)' } }, 'Component review · sample usage data'),
            h('div', { className: styles.panel, style: { height: 'calc(100% - 50px)', border: '1px solid var(--border)', borderRadius: 8 } },
                h(Header, { title: 'Plan the customer research workshop', conversationId: source.conversationId, model: buildConversationDetails(source), onSelect: () => {} }),
                h('p', { style: { padding: 16 } }, 'Your workshop agenda and interview summary are ready to review.')
            )
        )
    );
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/usage-review", lambda route: route.fulfill(content_type="text/html", body=HTML))
    page.goto("http://127.0.0.1:5192/usage-review")
    page.wait_for_function("window.__vite_plugin_react_preamble_installed__ === true")
    page.evaluate(MOUNT)
    trigger = page.get_by_role("button", name="Details", exact=False)
    trigger.click()
    page.locator("summary", has_text="Advanced").click()
    usage = page.get_by_role("region", name="Usage by agent")
    expect(usage.get_by_text("Of which cached").first).to_be_visible()
    expect(page.get_by_text("partial", exact=True)).to_be_visible()
    assert page.get_by_text("cache writes", exact=False).count() == 0
    # Native disclosures must remain keyboard operable inside the popover.
    analyst = usage.locator("summary", has_text="Research analyst")
    analyst.focus()
    page.keyboard.press("Enter")
    expect(usage.get_by_text("Of which cached").nth(1)).to_be_visible()
    page.keyboard.press("Enter")
    for width, theme in [(1000, "dark"), (360, "dark"), (360, "light")]:
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        page.get_by_role("region", name="Conversation details").locator("..").evaluate("el => { el.scrollTop = 0; }")
        page.wait_for_function("""() => {
            const el = document.querySelector('[aria-label="Conversation details"]').parentElement;
            const rect = el.getBoundingClientRect();
            return rect.x >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight && el.scrollWidth <= el.clientWidth;
        }""")
        page.screenshot(path=str(OUTPUT / f"usage-{width}-{theme}.png"))
    page.keyboard.press("Escape")
    expect(trigger).to_be_focused()
    assert not errors, errors
    browser.close()
print("Passed: usage breakdown, partial cost, keyboard disclosure, and narrow/light layouts.")
