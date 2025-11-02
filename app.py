# app.py
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session
from urllib.parse import urljoin, urlparse
from pathlib import Path
import time
import html
import io
import os
import random
import requests
from bs4 import BeautifulSoup

APP_TITLE = "Flask Forum Link Scraper"
BACKENDS = ["auto", "requests", "cloudscraper", "playwright"]

# Rotating user agents for anti-403
USER_AGENTS = [
    # Windows Chrome
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/130.0.0.0 Safari/537.36"),
    # macOS Safari
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    # iPhone Safari
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
]

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


# ---------- Fetch logic section ----------
def make_session(user_agent: str | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent or random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    })
    return s


def apply_referer_and_cookies(session: requests.Session, url: str, referer: str | None, cookie_str: str | None):
    if referer:
        session.headers["Referer"] = referer
    if cookie_str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            session.cookies.set(k.strip(), v.strip(), domain=urlparse(url).hostname)


def fetch_requests(url: str, referer: str | None = None, cookie_str: str | None = None, timeout: int = 25) -> str:
    """Try plain requests with UA rotation"""
    errors = []
    for i in range(3):
        s = make_session()
        apply_referer_and_cookies(s, url, referer, cookie_str)
        try:
            r = s.get(url, timeout=timeout)
            if r.status_code == 403:
                errors.append(f"403 on try {i+1}")
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:
            errors.append(str(e))
            continue
    raise requests.HTTPError("; ".join(errors))


def fetch_cloudscraper(url: str, referer: str | None = None, cookie_str: str | None = None, timeout: int = 30) -> str:
    """Try with cloudscraper (Cloudflare bypass)"""
    import cloudscraper
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    })
    if referer:
        scraper.headers["Referer"] = referer
    if cookie_str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            scraper.cookies.set(k.strip(), v.strip(), domain=urlparse(url).hostname)

    r = scraper.get(url, timeout=timeout)
    if r.status_code == 403:
        raise requests.HTTPError("403 via cloudscraper")
    r.raise_for_status()
    return r.text


def fetch_playwright(url: str, referer: str | None = None, cookie_str: str | None = None, timeout_ms: int = 45000) -> str:
    """Full JS rendering using Playwright"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            java_script_enabled=True,
            viewport={"width": 1280, "height": 800},
        )
        if cookie_str:
            cookies = []
            for part in cookie_str.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                cookies.append({
                    "name": k.strip(),
                    "value": v.strip(),
                    "domain": urlparse(url).hostname,
                    "path": "/",
                })
            if cookies:
                context.add_cookies(cookies)
        page = context.new_page()
        if referer:
            page.set_extra_http_headers({"Referer": referer})
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        html_text = page.content()
        context.close()
        browser.close()
        return html_text


def smart_fetch(url: str, referer: str | None, cookie_str: str | None, backend: str = "auto") -> str:
    """Flexible fetching with selectable backend."""
    b = (backend or "auto").lower()

    def _req():
        return fetch_requests(url, referer, cookie_str)

    def _cloud():
        return fetch_cloudscraper(url, referer, cookie_str)

    def _play():
        return fetch_playwright(url, referer, cookie_str)

    if b == "requests":
        return _req()
    if b == "cloudscraper":
        return _cloud()
    if b == "playwright":
        return _play()

    # auto fallback chain
    try:
        return _req()
    except Exception as e1:
        try:
            return _cloud()
        except Exception as e2:
            try:
                return _play()
            except Exception as e3:
                raise RuntimeError(f"requests/cloudscraper/playwright failed: {e1} | {e2} | {e3}")


# ---------- Link parsing ----------
def extract_links(html_text: str, base_url: str):
    soup = BeautifulSoup(html_text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text(strip=True) or "").strip()
        href = a["href"].strip()
        abs_url = urljoin(base_url, href)
        links.append((text, abs_url))
    return links


def filter_links(links, keyword: str, match_in_text: bool = True, match_in_url: bool = True,
                 same_domain_only: bool = False, base_url: str = ""):
    kw = (keyword or "").lower()
    out = []
    seen = set()
    base_host = urlparse(base_url).netloc.lower() if same_domain_only and base_url else None

    for text, url in links:
        if same_domain_only and base_host and urlparse(url).netloc.lower() != base_host:
            continue
        ok_text = match_in_text and kw in (text or "").lower()
        ok_url = match_in_url and kw in url.lower()
        if ok_text or ok_url:
            if url not in seen:
                seen.add(url)
                out.append((text, url))
    return out


def render_results_html(links, source_url: str, keyword: str) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    items = []
    for text, url in links:
        label = text if text else url
        items.append(
            f'<li><a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'
            f'<div style="color:#666;font-size:.85rem;">{html.escape(url)}</div></li>'
        )
    empty_msg = "" if items else '<p style="color:red;">No matches found.</p>'
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Links for {html.escape(keyword)}</title></head>
<body><h1>Filtered links for “{html.escape(keyword)}”</h1>
<p>Source: <a href="{html.escape(source_url)}">{html.escape(source_url)}</a><br>Generated: {ts}</p>
<ul>{''.join(items)}</ul>{empty_msg}</body></html>"""

# ---------- Pagination helpers ----------
def find_next_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """
    Try common Discuz!/forum 'next page' patterns.
    - <a class="nxt"> for Discuz
    - Link text 'Next', '下一页', '›'
    - rel="next"
    Returns absolute URL or None if not found.
    """
    # 1) rel="next"
    a = soup.find("a", rel=lambda v: v and "next" in v.lower())
    if a and a.get("href"):
        return urljoin(base_url, a["href"].strip())

    # 2) Discuz class="nxt"
    a = soup.find("a", class_=lambda c: c and "nxt" in c)
    if a and a.get("href"):
        return urljoin(base_url, a["href"].strip())

    # 3) Common text variants
    for txt in ("Next", "next", "下一页", "›", ">"):
        a = soup.find("a", string=lambda s: s and txt in s)
        if a and a.get("href"):
            return urljoin(base_url, a["href"].strip())

    return None


def iterate_forum_pages(start_url: str, max_pages: int, referer: str | None,
                        cookies_raw: str | None, backend: str = "auto",
                        pause_seconds: float = 0.5):
    """
    Yield (page_url, html_text, soup) for up to max_pages, following the forum's Next link.
    De-duplicates by visited URL.
    """
    visited = set()
    current_url = start_url

    for _ in range(max_pages):
        if current_url in visited:
            break
        visited.add(current_url)

        html_text = smart_fetch(current_url, referer, cookies_raw, backend=backend)
        soup = BeautifulSoup(html_text, "html.parser")
        yield current_url, html_text, soup

        next_url = find_next_page_url(soup, current_url)
        if not next_url:
            break
        current_url = next_url
        if pause_seconds > 0:
            time.sleep(pause_seconds)


# ---------- Flask routes ----------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        keyword = (request.form.get("keyword") or "").strip()
        match_text = request.form.get("match_text") == "on"
        match_url = request.form.get("match_url") == "on"
        same_domain = request.form.get("same_domain") == "on"
        referer = (request.form.get("referer") or "").strip() or None
        cookies_raw = (request.form.get("cookies") or "").strip() or None
        backend = (request.form.get("backend") or os.environ.get("FETCH_BACKEND", "auto")).strip().lower()
        if backend not in BACKENDS:
            backend = "auto"

        # NEW: optional pagination inputs (safe defaults if fields not in template yet)
        try:
            max_pages = int(request.form.get("max_pages") or 1)
        except ValueError:
            max_pages = 1
        max_pages = max(1, max_pages)

        try:
            pause_ms = int(request.form.get("pause_ms") or 400)
        except ValueError:
            pause_ms = 400
        pause_seconds = max(0, pause_ms) / 1000.0

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            flash("Please provide a full URL including https://", "error")
            return redirect(url_for("index"))
        if not keyword:
            flash("Keyword cannot be empty.", "error")
            return redirect(url_for("index"))

        try:
            # Crawl up to max_pages by following the forum's Next link(s)
            all_links = []
            for page_url, html_text, soup in iterate_forum_pages(
                start_url=url,
                max_pages=max_pages,
                referer=referer,
                cookies_raw=cookies_raw,
                backend=backend,
                pause_seconds=pause_seconds,
            ):
                all_links.extend(extract_links(html_text, page_url))

            # Filter once over the union of links across all visited pages
            matches = filter_links(
                all_links,
                keyword,
                match_text,
                match_url,
                same_domain,
                base_url=url,
            )

        except Exception as e:
            flash(f"Failed to fetch or parse page: {e}", "error")
            return redirect(url_for("index"))

        session["last_results"] = {
            "source_url": url,
            "keyword": keyword,
            "matches": matches,
        }
        return render_template(
            "results.html",
            title=APP_TITLE,
            source_url=url,
            keyword=keyword,
            matches=matches,
            match_text=match_text,
            match_url=match_url,
            same_domain=same_domain,
            referer=referer,
            cookies_set=bool(cookies_raw),
            backend=backend,
        )

    return render_template("index.html", title=APP_TITLE, backends=BACKENDS)

@app.route("/export/html")
def export_html():
    data = session.get("last_results")
    if not data:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("index"))

    html_content = render_results_html(data["matches"], data["source_url"], data["keyword"])
    buf = io.BytesIO(html_content.encode("utf-8"))
    filename = f"filtered_links_{int(time.time())}.html"
    return send_file(buf, mimetype="text/html", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(debug=True)
