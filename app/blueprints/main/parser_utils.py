# parser_utils.py
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import time
import html
import re

from .fetch_utils import smart_fetch


# ---------- Link extraction & filtering ----------

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
    """
    Refine results using sub-keywords.
    - Comma (,) separates OR terms: any match passes
    - Plus (+) separates AND terms: all must match
      e.g. 'jewish, israel' → OR
           'jewish + israel' → AND
    """
    if not sub_kw:
        return pairs

    require_all = "+" in sub_kw and "," not in sub_kw
    terms = [t.strip().lower() for t in re.split(r"[,+]", sub_kw) if t.strip()]
    if not terms:
        return pairs

    def hit(s: str) -> bool:
        s_l = (s or "").lower()
        if require_all:
            return all(term in s_l for term in terms)
        else:
            return any(term in s_l for term in terms)

    out = []
    for text, url in pairs:
        t_ok = match_text and hit(text)
        u_ok = match_url and hit(url)
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


# ---------- Pagination helpers (robust for query-string + Discuz!) ----------

def find_next_page_url(soup: BeautifulSoup, base_url: str) -> str | None:
    """Try common 'next page' anchor patterns first (Discuz! etc.)."""
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


def _current_page_number(url: str, param: str = "page") -> int:
    s = urlsplit(url)
    q = dict(parse_qsl(s.query, keep_blank_values=True))
    try:
        return int((q.get(param) or "1") or "1")
    except ValueError:
        return 1


def _same_path(u1: str, u2: str) -> bool:
    a, b = urlsplit(u1), urlsplit(u2)
    return (a.scheme == b.scheme) and (a.netloc == b.netloc) and (a.path == b.path)


def _find_next_by_query_page(soup, base_url: str, param: str = "page") -> str | None:
    """
    Look for an <a> on the SAME PATH whose ?page equals current+1.
    This handles cases where page=1 has no explicit 'next' text but numbered anchors exist.
    """
    s_base = urlsplit(base_url)
    cur = _current_page_number(base_url, param=param)
    target = cur + 1

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        candidate = urljoin(base_url, href)
        s = urlsplit(candidate)
        if not _same_path(base_url, candidate):
            continue
        q = dict(parse_qsl(s.query, keep_blank_values=True))
        try:
            if int((q.get(param) or "")) == target:
                return urlunsplit((s.scheme, s.netloc, s.path, s.query, s.fragment))
        except ValueError:
            continue
    return None


def _extract_pagination_template_pairs(soup, base_url: str, param: str = "page") -> list[tuple[str, str]] | None:
    """
    Find any same-path anchor that contains a ?page=... param and return its
    QUERY PAIRS (ordered, with blank values preserved). We use this as a template
    for building synthetic next-page URLs that match the site's expected shape.
    """
    s_base = urlsplit(base_url)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        candidate = urljoin(base_url, href)
        s = urlsplit(candidate)
        if not _same_path(base_url, candidate):
            continue
        pairs = parse_qsl(s.query, keep_blank_values=True)
        if any(k == param for k, _ in pairs):
            return pairs
    return None


def _bump_page_using_pairs(current_url: str, template_pairs: list[tuple[str, str]] | None,
                           param: str = "page") -> str | None:
    """
    Increment ?page while preserving parameter ORDER and blank values.
    If template_pairs provided, follow their order/keys; else use current URL's query order.
    """
    s_cur = urlsplit(current_url)
    cur_pairs = parse_qsl(s_cur.query, keep_blank_values=True)
    cur_map = dict(cur_pairs)

    # current page defaults to 1
    try:
        cur_page = int((cur_map.get(param) or "1") or "1")
    except ValueError:
        cur_page = 1
    new_page = str(cur_page + 1)

    # Choose ordering to follow
    pairs_to_follow = template_pairs if template_pairs is not None else cur_pairs

    seen = set()
    new_pairs = []
    inserted_page = False

    # Follow template (or current) order; fill values from current if present
    for k, v_tpl in pairs_to_follow:
        if k in seen:
            continue
        seen.add(k)
        if k == param:
            new_pairs.append((k, new_page))
            inserted_page = True
        else:
            v_cur = cur_map.get(k, v_tpl)
            new_pairs.append((k, v_cur))

    # Add any extra current params not in the template (preserve their order)
    for k, v in cur_pairs:
        if k not in seen and k != param:
            new_pairs.append((k, v))
            seen.add(k)

    if not inserted_page:
        new_pairs.append((param, new_page))

    new_query = urlencode(new_pairs, doseq=True)
    return urlunsplit((s_cur.scheme, s_cur.netloc, s_cur.path, new_query, s_cur.fragment))


# ---------- Page iterator (uses all of the above) ----------

def iterate_forum_pages(start_url: str, max_pages: int, referer: str | None,
                        cookies_raw: str | None, backend: str = "auto",
                        pause_seconds: float = 0.5):
    """
    Yield (page_url, html_text, soup) following next/numbered links.
    Robust to 'page' query-style pagination and preserves query shape (incl. blank values).
    """
    visited = set()
    current_url = start_url
    empty_streak = 0
    MAX_EMPTY = 2  # don't spin forever if blocked/thin HTML

    for _ in range(max_pages):
        if current_url in visited:
            break
        visited.add(current_url)

        # Polite first-hop referer: use the origin of start_url if none provided
        effective_referer = referer or (start_url.rsplit("/", 1)[0] + "/")

        html_text = smart_fetch(current_url, effective_referer, cookies_raw, backend=backend)

        if html_text:
            empty_streak = 0
            soup = BeautifulSoup(html_text, "html.parser")
            yield current_url, html_text, soup

            # 1) Common 'next' anchors
            next_url = find_next_page_url(soup, current_url)

            # 2) Same-path numbered link where page == current+1
            if not next_url:
                next_url = _find_next_by_query_page(soup, current_url, param="page")

            # 3) Learn a query template from any same-path pagination anchor
            template_pairs = _extract_pagination_template_pairs(soup, current_url, param="page")

            # 4) If still no next, synthesize by bumping page with the learned template
            if not next_url:
                next_url = _bump_page_using_pairs(current_url, template_pairs, param="page")
        else:
            # No HTML — try a limited number of synthetic bumps, then stop
            empty_streak += 1
            if empty_streak > MAX_EMPTY:
                break
            next_url = _bump_page_using_pairs(current_url, template_pairs=None, param="page")

        if not next_url or next_url == current_url or next_url in visited:
            break

        current_url = next_url
        if pause_seconds > 0:
            time.sleep(pause_seconds)
