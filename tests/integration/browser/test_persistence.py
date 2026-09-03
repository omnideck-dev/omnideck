import json
from urllib.parse import urlparse

from aiohttp import web

from browser.core.browser import Browser
from browser.profile_store import BrowserProfileStore

_SEED_PAGE = """<!doctype html>
<html><body>seed<script>
const value = new URLSearchParams(location.search).get('value');
document.cookie = `visible=${value}; path=/; SameSite=Lax`;
localStorage.setItem('profile-value', value);
const request = indexedDB.open('profile-db', 1);
request.onupgradeneeded = () => request.result.createObjectStore('values');
request.onsuccess = () => {
  const tx = request.result.transaction('values', 'readwrite');
  tx.objectStore('values').put(value, 'saved');
  tx.oncomplete = () => document.body.dataset.ready = 'true';
};
</script></body></html>"""

_REPORT_PAGE = """<!doctype html>
<html><body><script>
const request = indexedDB.open('profile-db');
request.onsuccess = () => {
  const tx = request.result.transaction('values');
  const read = tx.objectStore('values').get('saved');
  read.onsuccess = () => {
    document.body.textContent = JSON.stringify({
      local: localStorage.getItem('profile-value'),
      indexed: read.result,
    });
  };
};
</script></body></html>"""


async def test_explicit_snapshot_survives_chromium_restart_and_ignores_unsaved_changes(
    aiohttp_server,
    tmp_path,
):
    async def seed(_request):
        response = web.Response(text=_SEED_PAGE, content_type="text/html")
        response.set_cookie("http_only", _request.query["value"], httponly=True)
        return response

    async def report(request):
        response = web.Response(text=_REPORT_PAGE, content_type="text/html")
        response.headers["X-Seen-Cookies"] = json.dumps(dict(request.cookies))
        return response

    app = web.Application()
    app.router.add_get("/seed", seed)
    app.router.add_get("/report", report)
    server = await aiohttp_server(app)
    base = str(server.make_url("/")).rstrip("/")

    store = BrowserProfileStore(tmp_path / "profiles")
    store.ensure_default()

    browser = await Browser.start(headless=True)
    page = await browser._context.new_page()
    await page.goto(f"{base}/seed?value=alpha")
    await page.wait_for_selector('body[data-ready="true"]')
    store.save_state("default", await browser.capture_storage_state())

    # Change every storage surface but do not explicitly save again.
    await page.goto(f"{base}/seed?value=beta")
    await page.wait_for_selector('body[data-ready="true"]')
    await browser.close()

    restored = await Browser.start(
        storage_state=store.load_state("default"),
        headless=True,
    )
    restored_page = await restored._context.new_page()
    response = await restored_page.goto(f"{base}/report")
    assert response is not None
    await restored_page.wait_for_function("document.body.textContent.startsWith('{')")
    browser_values = json.loads(await restored_page.text_content("body"))
    seen_cookies = json.loads((await response.all_headers())["x-seen-cookies"])

    assert browser_values == {"local": "alpha", "indexed": "alpha"}
    assert seen_cookies["http_only"] == "alpha"
    assert seen_cookies["visible"] == "alpha"
    await restored.close()


async def test_saved_profiles_restore_into_isolated_browser_contexts(
    aiohttp_server,
    tmp_path,
):
    """Two saved profiles preserve distinct state on every storage surface."""

    async def seed(request):
        response = web.Response(text=_SEED_PAGE, content_type="text/html")
        response.set_cookie("http_only", request.query["value"], httponly=True)
        return response

    async def report(request):
        response = web.Response(text=_REPORT_PAGE, content_type="text/html")
        response.headers["X-Seen-Cookies"] = json.dumps(dict(request.cookies))
        return response

    app = web.Application()
    app.router.add_get("/seed", seed)
    app.router.add_get("/report", report)
    server = await aiohttp_server(app)
    base = str(server.make_url("/")).rstrip("/")
    store = BrowserProfileStore(tmp_path / "profiles")
    store.ensure_default()

    profile_ids = {}
    for value in ("alpha", "beta"):
        source = await Browser.start(headless=True)
        page = await source._context.new_page()
        await page.goto(f"{base}/seed?value={value}")
        await page.wait_for_selector('body[data-ready="true"]')
        profile = store.create(
            name=value.title(),
            icon="bi-globe2",
            storage_state=await source.capture_storage_state(),
        )
        profile_ids[value] = profile.id
        await source.close()

    restored = {
        value: await Browser.start(
            storage_state=store.load_state(profile_id),
            headless=True,
        )
        for value, profile_id in profile_ids.items()
    }
    try:
        for value, browser in restored.items():
            page = await browser._context.new_page()
            response = await page.goto(f"{base}/report")
            assert response is not None
            await page.wait_for_function("document.body.textContent.startsWith('{')")
            browser_values = json.loads(await page.text_content("body"))
            seen_cookies = json.loads((await response.all_headers())["x-seen-cookies"])

            assert browser_values == {"local": value, "indexed": value}
            assert seen_cookies["http_only"] == value
            assert seen_cookies["visible"] == value
    finally:
        for browser in restored.values():
            await browser.close()


async def test_removing_one_domain_and_clearing_state_survive_chromium_restart(
    aiohttp_server,
    tmp_path,
):
    async def seed(request):
        response = web.Response(text=_SEED_PAGE, content_type="text/html")
        response.set_cookie("http_only", request.query["value"], httponly=True)
        return response

    app = web.Application()
    app.router.add_get("/seed", seed)
    server = await aiohttp_server(app)
    numeric_base = str(server.make_url("/")).rstrip("/")
    named_base = f"http://localhost:{server.port}"
    removed_domain = urlparse(numeric_base).hostname
    kept_domain = urlparse(named_base).hostname
    assert removed_domain and kept_domain and removed_domain != kept_domain

    source = await Browser.start(headless=True)
    page = await source._context.new_page()
    for base, value in ((numeric_base, "remove"), (named_base, "keep")):
        await page.goto(f"{base}/seed?value={value}")
        await page.wait_for_selector('body[data-ready="true"]')

    store = BrowserProfileStore(tmp_path / "profiles")
    profile = store.create(
        name="Two sites",
        icon="bi-globe2",
        storage_state=await source.capture_storage_state(),
    )
    await source.close()

    store.remove_domains(profile.id, [removed_domain])
    restored = await Browser.start(storage_state=store.load_state(profile.id), headless=True)
    remaining = await restored.capture_storage_state()
    await restored.close()

    assert {cookie["domain"].lstrip(".") for cookie in remaining["cookies"]} == {kept_domain}
    assert {urlparse(origin["origin"]).hostname for origin in remaining["origins"]} == {kept_domain}

    store.clear_state(profile.id)
    empty = await Browser.start(storage_state=store.load_state(profile.id), headless=True)
    assert await empty.capture_storage_state() == {"cookies": [], "origins": []}
    await empty.close()
