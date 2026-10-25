"""Small browser regressions reproduced against real DOM and public tools."""

from urllib.parse import urlencode

import pytest

from tools.browser import browse_page, execute_javascript, read_page

from .._helpers import find_ref


@pytest.mark.parametrize("root", ["body", "html"])
async def test_fixed_page_root_does_not_expand_modal_surface(open_tab, servers, root):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    await execute_javascript(
        "document.body.innerHTML = `<button>Background action</button>"
        "<div role='dialog' aria-modal='true' style='position:fixed;top:0;left:0;"
        "width:100%;height:40vh;background:white'><button>Continue</button></div>`;"
        f"document.querySelector('{root}').style.cssText = 'position:fixed;inset:0;margin:0';",
        tab=tab,
    )
    view = await browse_page(tab=tab)
    assert "[Modal dialog open" in view
    assert find_ref(view, role="button", name="Continue") is not None
    assert find_ref(view, role="button", name="Background action") is None


async def test_page_reads_do_not_share_abbreviation_definitions(open_tab, servers):
    first = await open_tab(f"{servers.primary}/article/article.html")
    await execute_javascript(
        "document.body.innerHTML = '<p><abbr title=\"Private glossary\">PG</abbr></p>'",
        tab=first,
    )
    assert "Private glossary" in await read_page(tab=first)
    second = await open_tab(f"{servers.primary}/article/article.html")
    assert "Private glossary" not in await read_page(tab=second)


@pytest.mark.parametrize("scrolled", [False, True])
async def test_viewport_preserves_inline_words_of_straddling_paragraph(open_tab, servers, scrolled):
    tab = await open_tab(f"{servers.primary}/article/article.html")
    await execute_javascript(
        "document.body.style.cssText='margin:0'; document.body.innerHTML = `"
        "<div style='height:80vh'></div><p style='margin:0;line-height:15vh'>"
        "<a href='#first'>Austin</a> is<br>the <a href='#second'><em>capital</em></a><br>"
        "of <span>Texas</span><span hidden>Hidden secret</span></p>"
        "<div style='height:150vh'></div><p>Unrelated <a href='#far'>Faraway</a> words</p>`;"
        + ("window.scrollTo(0, innerHeight)" if scrolled else "window.scrollTo(0, 0)"),
        tab=tab,
    )
    view = await browse_page(tab=tab)
    for word in ("Austin", "capital", "Texas"):
        assert word in view
    assert "Hidden secret" not in view
    assert "Faraway" not in view
    offscreen = "Austin" if scrolled else "capital"
    assert find_ref(view, role="link", name=offscreen) is None


@pytest.mark.parametrize(
    ("markup", "vendor"),
    [
        ('<div id="px-captcha" style="width:300px;height:200px">Press and hold</div>', "PerimeterX"),
        ('<div data-dd-captcha-container style="width:300px;height:200px">Blocked</div>', "DataDome"),
        ('<iframe src="https://geo.captcha-delivery.com/captcha/" style="width:300px;height:200px"></iframe>', "DataDome"),
        ('<div id="px-captcha" style="display:none">Press and hold</div>', None),
        ('<div data-dd-captcha-container style="display:none">Blocked</div>', None),
        ('<script>window._pxAppId="ordinary-protection";</script><p>You have been blocked</p>', None),
        ('<iframe src="https://captcha-delivery.com.example.test/captcha/"></iframe>', None),
    ],
)
async def test_vendor_challenges_require_visible_vendor_evidence(open_tab, servers, markup, vendor):
    tab = await open_tab(
        f"{servers.primary}/rendering-regressions/vendor-challenge.html?{urlencode({'markup': markup})}"
    )
    view = await browse_page(tab=tab)
    if vendor:
        assert f"[{vendor} challenge detected]" in view
        assert "fetch_url" in view
    else:
        assert "challenge detected]" not in view
