"""The application's webfont is bundled and loads without external font services."""

from urllib.parse import urlparse


def test_code_font_loads_from_application_assets_without_google_fonts(page):
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    # If an external font dependency returns, fail the assertions promptly
    # instead of waiting on a third-party request during page navigation.
    page.route("https://fonts.googleapis.com/**", lambda route: route.abort())
    page.route("https://fonts.gstatic.com/**", lambda route: route.abort())
    page.goto("/")
    faces = page.evaluate('''async () => {
        const loaded = [];
        for (const weight of [400, 500, 600]) {
            const fonts = await document.fonts.load(`${weight} 13px "JetBrains Mono"`);
            loaded.push({weight, count: fonts.length, ready: fonts.every(font => font.status === 'loaded')});
        }
        return loaded;
    }''')
    assert all(face["count"] > 0 and face["ready"] for face in faces), faces
    assert not any(urlparse(url).hostname in {"fonts.googleapis.com", "fonts.gstatic.com"} for url in requests)
    font_urls = [url for url in requests if "JetBrainsMono" in url and urlparse(url).path.endswith(".woff2")]
    assert font_urls, requests
    assert all(urlparse(url).netloc == urlparse(page.url).netloc for url in font_urls)
    license_response = page.request.get('/assets/licenses/JetBrainsMono-OFL.txt')
    assert license_response.status == 200
    assert 'SIL OPEN FONT LICENSE Version 1.1' in license_response.text()
