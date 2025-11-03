from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time
import html
import re

from .fetch_utils import smart_fetch

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

def subfilter_links(pairs, sub_kw, match_text=True, match_url=True):
    """Second-level filter for (text, url) pairs."""
    if not sub_kw:
        return pairs
    pat = re.compile(re.escape(sub_kw), re.IGNORECASE)
    out = []
    for text, url in pairs:
        t_ok = bool(match_text and text and pat.search(text))
        u_ok = bool(match_url and url and pat.search(url))
        if t_ok or u_ok:
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

def find_next_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Try common Discuz!/forum 'next page' patterns."""
    a = soup.find("a", rel=lambda v: v and "next" in v.lower())
    if a and a.get("href"):
        return urljoin(base_url, a["href"].strip())

    a = soup.find("a", class_=lambda c: c and "nxt" in c)
    if a and a.get("href"):
        return urljoin(base_url, a["href"].strip())

    for txt in ("Next", "next", "下一页", "›", ">"):
        a = soup.find("a", string=lambda s: s and txt in s)
        if a and a.get("href"):
            return urljoin(base_url, a["href"].strip())
    return None

def iterate_forum_pages(start_url: str, max_pages: int, referer: str | None,
                        cookies_raw: str | None, backend: str = "auto",
                        pause_seconds: float = 0.5):
    """Yield (page_url, html_text, soup) following Next links (de-duplicated)."""
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
