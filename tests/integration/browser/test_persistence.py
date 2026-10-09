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


async def test_invalid_indexeddb_keys_do_not_block_profile_login(aiohttp_server, tmp_path):
    async def report(request):
        response = web.Response(text="<html><body>restored</body></html>", content_type="text/html")
        response.headers["X-Seen-Cookies"] = json.dumps(dict(request.cookies))
        return response

    app = web.Application()
    app.router.add_get("/report", report)
    server = await aiohttp_server(app)
    base = str(server.make_url("/")).rstrip("/")
    state = {
        "cookies": [
            {
                "name": "session",
                "value": "signed-in",
                "domain": urlparse(base).hostname,
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [
            {
                "origin": base,
                "localStorage": [{"name": "profile-value", "value": "saved"}],
                "indexedDB": [
                    {
                        "name": "cache",
                        "version": 1,
                        "stores": [
                            {
                                "name": "records",
                                "keyPath": "id",
                                "autoIncrement": False,
                                "indexes": [],
                                "records": [
                                    {
                                        "valueEncoded": {
                                            "o": [
                                                {"k": "id", "v": {"o": [], "id": 2}},
                                                {"k": "payload", "v": "broken cache"},
                                            ],
                                            "id": 1,
                                        }
                                    },
                                    {"value": {"id": "good", "payload": "retained"}},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "storage_state.json"
    original = json.dumps(state)
    path.write_text(original)

    # Exercise both direct snapshots and storage-state filenames.
    for source in (state, str(path)):
        browser = await Browser.start(storage_state=source, headless=True)
        try:
            page = await browser._context.new_page()
            response = await page.goto(f"{base}/report")
            seen_cookies = json.loads((await response.all_headers())["x-seen-cookies"])
            assert seen_cookies["session"] == "signed-in"
            assert await page.evaluate("localStorage.getItem('profile-value')") == "saved"
            assert "session=" not in await page.evaluate("document.cookie")
            restored = await browser.capture_storage_state()
            database = restored["origins"][0]["indexedDB"][0]
            assert database["stores"][0]["records"] == [{"value": {"id": "good", "payload": "retained"}}]
        finally:
            await browser.close()
    assert path.read_text() == original
    assert len(state["origins"][0]["indexedDB"][0]["stores"][0]["records"]) == 2


async def test_binary_indexeddb_keys_and_values_survive_profile_export(aiohttp_server, tmp_path):
    async def report(request):
        response = web.Response(text="<html><body>binary profile</body></html>", content_type="text/html")
        response.headers["X-Seen-Cookies"] = json.dumps(dict(request.cookies))
        return response

    app = web.Application()
    app.router.add_get("/", report)
    server = await aiohttp_server(app)
    base = str(server.make_url("/"))
    store = BrowserProfileStore(tmp_path / "profiles")

    source = await Browser.start(headless=True)
    try:
        page = await source._context.new_page()
        await page.goto(base)
        await source._context.add_cookies([{"name": "session", "value": "saved", "url": base, "httpOnly": True}])
        await page.evaluate("""async () => {
            localStorage.setItem('profile-value', 'saved');
            const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open('binary-db', 1);
                request.onupgradeneeded = () => {
                    request.result.createObjectStore('inline', {keyPath: 'id'});
                    request.result.createObjectStore('out-of-line');
                    request.result.createObjectStore('compound', {keyPath: ['id', 'version']});
                };
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
            await new Promise((resolve, reject) => {
                const tx = db.transaction([...db.objectStoreNames], 'readwrite');
                const buffer = bytes => new Uint8Array(bytes).buffer;
                tx.objectStore('inline').add({
                    id: buffer([0, 1, 255]),
                    payload: buffer([5, 0, 254]),
                    nested: {empty: new ArrayBuffer(0), typed: new Uint8Array([8, 9])},
                });
                tx.objectStore('out-of-line').add(buffer([7, 6, 5]), buffer([2, 3]));
                tx.objectStore('compound').add({id: buffer([4, 5]), version: 1, payload: buffer([9, 8])});
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
            });
            db.close();
        }""")
        profile = store.create(name="Binary keys", icon="bi-globe2", storage_state=await source.capture_storage_state())
    finally:
        await source.close()

    # Reopen from the saved JSON after stopping the original Chromium process.
    restored = await Browser.start(storage_state=store.load_state(profile.id), headless=True)
    try:
        page = await restored._context.new_page()
        response = await page.goto(base)
        assert json.loads((await response.all_headers())["x-seen-cookies"])["session"] == "saved"
        assert await page.evaluate("localStorage.getItem('profile-value')") == "saved"
        actual = await page.evaluate("""async () => {
            const request = indexedDB.open('binary-db');
            const db = await new Promise((resolve, reject) => {
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
            const read = (name, key) => new Promise((resolve, reject) => {
                const request = db.transaction(name).objectStore(name).get(key);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
            const buffer = bytes => new Uint8Array(bytes).buffer;
            const inline = await read('inline', buffer([0, 1, 255]));
            const outOfLine = await read('out-of-line', buffer([2, 3]));
            const compound = await read('compound', [buffer([4, 5]), 1]);
            const bytes = value => value instanceof ArrayBuffer ? [...new Uint8Array(value)] : null;
            const result = {
                inlineKey: bytes(inline?.id),
                inlinePayload: bytes(inline?.payload),
                emptyBuffer: bytes(inline?.nested.empty),
                typedArray: inline?.nested.typed instanceof Uint8Array ? [...inline.nested.typed] : null,
                outOfLinePayload: bytes(outOfLine),
                compoundKey: bytes(compound?.id),
                compoundPayload: bytes(compound?.payload),
            };
            db.close();
            return result;
        }""")
        assert actual == {
            "inlineKey": [0, 1, 255],
            "inlinePayload": [5, 0, 254],
            "emptyBuffer": [],
            "typedArray": [8, 9],
            "outOfLinePayload": [7, 6, 5],
            "compoundKey": [4, 5],
            "compoundPayload": [9, 8],
        }
    finally:
        await restored.close()
