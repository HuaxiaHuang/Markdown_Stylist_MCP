from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "validation_final"
HTML = max(OUTPUT_DIR.glob("toc_and_math*.html"), key=lambda path: path.stat().st_mtime)


def launch_chromium(playwright):
    try:
        return playwright.chromium.launch()
    except Exception:
        return playwright.chromium.launch(executable_path=playwright.chromium.executable_path)


with sync_playwright() as p:
    browser = launch_chromium(p)

    page = browser.new_page(viewport={"width": 1366, "height": 900})
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(HTML.as_uri(), wait_until="networkidle")
    page.evaluate("localStorage.removeItem('markdownStylistTocCollapsed')")
    page.reload(wait_until="networkidle")
    assert not page_errors, page_errors
    assert page.locator(".sidebar .toc-link").count() >= 8
    assert page.locator(".content .toc").count() == 1
    assert page.locator("math").count() >= 5
    assert page.locator(".toc-panel-close").is_visible()
    page.locator(".toc-panel-close").click()
    page.wait_for_timeout(250)
    assert "toc-panel-collapsed" in page.locator("body").get_attribute("class")
    assert page.locator(".toc-panel-open").is_visible()
    assert page.locator(".sidebar").bounding_box()["x"] < 0
    page.locator(".toc-panel-open").click()
    page.wait_for_timeout(250)
    assert "toc-panel-collapsed" not in (page.locator("body").get_attribute("class") or "")
    assert page.locator(".sidebar").bounding_box()["x"] >= 0
    page.locator(".sidebar .toc-link", has_text="Matrix Section").first.click()
    page.wait_for_timeout(700)
    assert "matrix-section" in page.evaluate("location.hash")
    page.mouse.wheel(0, 900)
    page.wait_for_timeout(700)
    active_count = page.locator(".sidebar .toc-link.is-active").count()
    assert active_count >= 1, {
        "active_count": active_count,
        "hash": page.evaluate("location.hash"),
        "scrollY": page.evaluate("scrollY"),
        "mapped_headings": page.evaluate("""Array.from(document.querySelectorAll('.sidebar .toc-link'))
            .map(function(link) { return (link.getAttribute('href') || '').replace(/^#/, ''); })
            .filter(function(id) { return document.getElementById(id); }).length"""),
        "first_ids": page.evaluate("""Array.from(document.querySelectorAll('.content h1,.content h2,.content h3'))
            .slice(0, 5).map(function(h) { return h.id; })"""),
        "first_hrefs": page.evaluate("""Array.from(document.querySelectorAll('.sidebar .toc-link'))
            .slice(0, 5).map(function(a) { return a.getAttribute('href'); })"""),
        "errors": page_errors,
    }
    page.locator(".toc-toggle").first.click()
    assert page.locator(".toc-children.is-collapsed").count() >= 1
    page.screenshot(path=str(ROOT / "output" / "validation_final" / "desktop.png"), full_page=True)

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
    mobile.goto(HTML.as_uri(), wait_until="networkidle")
    assert mobile.locator(".sidebar").bounding_box()["x"] < 0
    mobile.locator(".mobile-toc-button").click()
    mobile.wait_for_timeout(250)
    assert mobile.locator(".sidebar").bounding_box()["x"] >= 0
    mobile.locator(".drawer-close").click()
    mobile.wait_for_timeout(250)
    assert mobile.locator(".sidebar").bounding_box()["x"] < 0
    mobile.screenshot(path=str(ROOT / "output" / "validation_final" / "mobile.png"), full_page=True)

    browser.close()

print("browser-validation=pass")
