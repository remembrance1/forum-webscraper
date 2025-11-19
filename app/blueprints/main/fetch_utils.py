from urllib.parse import urlparse
import requests
import random

# Which backends the UI can select
BACKENDS = ["auto", "requests", "cloudscraper", "selenium"] #, "playwright"]

# Rotating user agents for anti-403
USER_AGENTS = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
     "AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/130.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
     "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"),
]

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
        for part in (cookie_str or "").split(";"):
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
        for part in (cookie_str or "").split(";"):
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

# def fetch_playwright(url: str, referer: str | None = None, cookie_str: str | None = None, timeout_ms: int = 45000) -> str:
#     """Full JS rendering using Playwright"""
#     from playwright.sync_api import sync_playwright

#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         context = browser.new_context(
#             user_agent=random.choice(USER_AGENTS),
#             java_script_enabled=True,
#             viewport={"width": 1280, "height": 800},
#         )
#         if cookie_str:
#             cookies = []
#             for part in (cookie_str or "").split(";"):
#                 part = part.strip()
#                 if not part or "=" not in part:
#                     continue
#                 k, v = part.split("=", 1)
#                 cookies.append({
#                     "name": k.strip(),
#                     "value": v.strip(),
#                     "domain": urlparse(url).hostname,
#                     "path": "/",
#                 })
#             if cookies:
#                 context.add_cookies(cookies)
#         page = context.new_page()
#         if referer:
#             page.set_extra_http_headers({"Referer": referer})
#         page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
#         html_text = page.content()
#         context.close()
#         browser.close()
#         return html_text

def fetch_selenium(
    url: str,
    referer: str | None = None,
    cookie_str: str | None = None,
    timeout: int = 45,
) -> str:
    """
    Full-page fetch using Selenium + Chrome in headless mode.

    Requires:
      pip install selenium
      and a working Chrome/Chromium + chromedriver on PATH.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    import time

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,800")
    options.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(timeout)

    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.hostname}"

        # 1) Open a "warm up" page so Selenium knows the domain
        start_url = referer or base
        driver.get(start_url)

        # 2) Apply cookies, if provided (same format as your existing code)
        if cookie_str:
            host = parsed.hostname
            for part in (cookie_str or "").split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                driver.add_cookie(
                    {
                        "name": k.strip(),
                        "value": v.strip(),
                        "domain": host,
                        "path": "/",
                    }
                )

        # 3) Now load the actual target URL
        driver.get(url)

        # Small wait so JS can finish
        time.sleep(2)

        html_text = driver.page_source
        if not html_text or "<html" not in html_text.lower():
            raise RuntimeError("Empty or invalid HTML from Selenium")

        return html_text
    finally:
        driver.quit()

def smart_fetch(
    url: str,
    referer: str | None,
    cookie_str: str | None,
    backend: str = "auto",
) -> str:
    """Flexible fetching with selectable backend."""
    b = (backend or "auto").lower()

    # Explicit backend choice
    if b == "requests":
        return fetch_requests(url, referer, cookie_str)
    if b == "cloudscraper":
        return fetch_cloudscraper(url, referer, cookie_str)
    if b == "selenium":
        return fetch_selenium(url, referer, cookie_str)
    # if b == "playwright":
    #     return fetch_playwright(url, referer, cookie_str)

    # auto fallback chain: requests → cloudscraper → selenium → playwright
    try:
        return fetch_requests(url, referer, cookie_str)
    except Exception as e1:
        try:
            return fetch_cloudscraper(url, referer, cookie_str)
        except Exception as e2:
            try:
                return fetch_selenium(url, referer, cookie_str)
            except Exception as e3:
            #     try:
            #         return fetch_playwright(url, referer, cookie_str)
            #    except Exception as e4:
                    raise RuntimeError(
                        "requests/cloudscraper/selenium failed: "
                        f"{e1} | {e2} | {e3} "
                    )
