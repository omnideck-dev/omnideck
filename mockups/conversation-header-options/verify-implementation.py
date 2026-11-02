"""Exercise the real header components against deterministic review data.

Run with Vite on port 5178. This checks presentation independently of an LLM.
The workspace controller's real close/reopen behavior is tested in Vitest.
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
    const h = React.createElement;
    const source = {
        conversationId: 'review', rootId: 'root',
        turns: [{children: [{kind: 'file_output', path: '/workshop.docx'}]}],
        agents: {
            root: {id: 'root', parentId: null, name: 'Primary', usageByIteration: {0: 31400}, contextUsage: {context_used: 46000, context_limit: 100000, compaction_threshold: 0.75}},
            child: {id: 'child', parentId: 'root', name: 'Interview analyst', status: 'running', usageByIteration: {0: 8900}},
        },
        workspace: {
            root: {browserTabs: {1: {screenshot: 'png'}}, terminalLines: [{cmd: 'true'}]},
            child: {browserTabs: {2: {screenshot: 'png'}}, terminalLines: [{cmd: 'ls'}]},
        },
    };
    function Review() {
        const [views, setViews] = React.useState({'workspace-resource:review:root:browser': {}});
        const model = buildConversationDetails(source);
        return h('div', {style: {height: '100vh', padding: 16, background: 'var(--canvas)'}},
            h('p', {style: {margin: '0 0 14px', color: 'var(--text-secondary)'}}, 'Implementation review · real components, sample conversation data'),
            h('div', {className: styles.panel, style: {height: 'calc(100% - 50px)', border: '1px solid var(--border)', borderRadius: 8}},
                h(Header, {title: 'Plan the customer research workshop', conversationId: 'review', model, onSelect: row => {
                    if (row.resourceId) setViews(current => ({...current, [row.id]: {}}));
                }}),
                h('div', {style: {padding: 16, display: 'flex', gap: 8}}, ...Object.keys(views).map(id => h('button', {key: id, onClick: () => setViews(current => Object.fromEntries(Object.entries(current).filter(([key]) => key !== id)))}, 'Close ' + id.split(':').at(-1)))),
                h('p', {style: {padding: 16}}, 'Your workshop agenda and interview summary are ready to review.')
            )
        );
    }
    createRoot(document.getElementById('review-root')).render(h(Review));
} """

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1000, "height": 820})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: print(f"Request failed: {request.url}: {request.failure}"))
    page.on("console", lambda message: print(message.text) if message.type == "error" else None)
    page.route("**/details-review", lambda route: route.fulfill(content_type="text/html", body=HTML))
    page.goto("http://127.0.0.1:5178/details-review")
    page.wait_for_function("window.__vite_plugin_react_preamble_installed__ === true")
    page.evaluate(MOUNT)
    page.get_by_role("button", name="Details", exact=False).click()
    expect(page.get_by_role("button", name="Primary agent Browser", exact=False)).to_be_visible()
    page.get_by_role("button", name="Primary agent Terminal", exact=False).click()
    expect(page.get_by_role("button", name="Close terminal")).to_be_visible()
    page.get_by_role("button", name="Close terminal").click()
    page.get_by_role("button", name="Details", exact=True).click()
    expect(page.get_by_role("button", name="Primary agent Terminal", exact=False)).to_be_visible()
    page.locator("summary").click()
    for width, theme in [(1000, "dark"), (360, "dark"), (360, "light")]:
        page.set_viewport_size({"width": width, "height": 820})
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        region = page.get_by_role("region", name="Conversation details")
        page.wait_for_function("""() => {
            const box = document.querySelector('[aria-label="Conversation details"]').parentElement.getBoundingClientRect();
            return box.x >= 0 && box.right <= window.innerWidth && box.bottom <= window.innerHeight;
        }""")
        bounds = region.locator("..").bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
        assert bounds["y"] + bounds["height"] <= 820
        trigger = page.get_by_role("button", name="Details", exact=True)
        trigger_bounds = trigger.bounding_box()
        assert abs(bounds["y"] - trigger_bounds["y"] - trigger_bounds["height"] - 6) < 1
        assert trigger.evaluate("el => getComputedStyle(el, '::after').content") == "none"
        page.screenshot(path=str(OUTPUT / f"implementation-{width}-{theme}.png"))
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Details", exact=True)).to_be_focused()
    assert not errors, errors
    browser.close()
print("Browser review passed: reopen/close, acknowledgement, keyboard dismissal, and narrow/light layouts.")
