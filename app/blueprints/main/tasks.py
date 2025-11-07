import time

from .parser_utils import (
    extract_links, filter_links, subfilter_links, iterate_forum_pages
)

def _page_title_from_soup(soup):
    try:
        if soup and getattr(soup, "title", None) and soup.title.string:
            return soup.title.string.strip()
    except Exception:
        pass
    return None

def _make_snippet(text: str | None, terms: list[str], span: int = 60) -> str | None:
    if not text:
        return None
    t = text.replace("\n", " ")
    tl = t.lower()
    for term in terms:
        if not term:
            continue
        i = tl.find(term.lower())
        if i != -1:
            start = max(0, i - span)
            end = min(len(t), i + len(term) + span)
            return t[start:end].strip()
    return None

def _to_result_obj(item, page_title: str | None, page_text: str | None, terms: list[str]):
    """
    Normalise whatever filter_links/subfilter_links returned into:
      {"url": ..., "title": ..., "snippet": ...}
    Supports dicts, 2-tuples/lists like [matched_text, url], or raw url strings.
    """
    url = None
    title = None

    # Mapping (preferred)
    if isinstance(item, dict):
        url = item.get("url") or item.get("href") or item.get("link") or item.get("u")
        title = item.get("title") or item.get("text") or item.get("anchor")

    # Sequence (legacy: [matched_text, url] or [url])
    elif isinstance(item, (list, tuple)):
        if len(item) >= 2:
            title, url = item[0], item[1]
        elif len(item) == 1:
            url = item[0]

    # String fallback
    else:
        url = str(item)

    if not title:
        title = page_title  # fall back to page <title> if we have no anchor/match text

    snippet = _make_snippet(page_text, terms)
    return {"url": url, "title": title, "snippet": snippet}

# In-memory run registry for progress + results
RUNS = {}  # { run_id: { "results": [...], "meta": {...}, "progress": {...} } }

def run_scan_task(run_id, *, url, keyword, sub_keyword, match_text, match_url,
                  same_domain, referer, cookies_raw, backend, pause_seconds,
                  max_pages):
    try:
        start_ts = time.time()
        # initialise progress info with richer fields
        RUNS[run_id]["progress"].update({
            "status": "running",
            "current": 0,
            "total": max_pages,
            "pages_scanned": 0,
            "links_seen": 0,
            "matches": 0,
            "eta_seconds": None,
        })

        matches_accum = []
        links_seen = 0

        for i, (page_url, html_text, soup) in enumerate(
            iterate_forum_pages(
                start_url=url,
                max_pages=max_pages,
                referer=referer,
                cookies_raw=cookies_raw,
                backend=backend,
                pause_seconds=pause_seconds,
            ),
            start=1
        ):
            # collect links from this page
            page_links = extract_links(html_text, page_url)
            links_seen += len(page_links)

            # filter immediately so progress can show live matches
            page_matches = filter_links(
                page_links, keyword, match_text, match_url, same_domain, base_url=url
            )
            if sub_keyword:
                page_matches = subfilter_links(
                    page_matches, sub_keyword, match_text=match_text, match_url=match_url
                )

            if page_matches:
                terms = [t for t in [keyword, sub_keyword] if t]
                page_title = _page_title_from_soup(soup)
                result_objs = [
                    _to_result_obj(m, page_title=page_title, page_text=html_text, terms=terms)
                    for m in page_matches
                ]
                matches_accum.extend(result_objs)

            # progress & ETA
            elapsed = max(0.001, time.time() - start_ts)
            rate = i / elapsed  # pages per second
            remaining = max(0, max_pages - i)
            eta_seconds = int(remaining / rate) if rate > 0 else None

            RUNS[run_id]["progress"].update({
                "current": i,
                "pages_scanned": i,
                "links_seen": links_seen,
                "matches": len(matches_accum),
                "eta_seconds": eta_seconds,
                "message": f"Scanned {i}/{max_pages} pages",
            })

        # finalise
        RUNS[run_id].update({
            "results": matches_accum,
            "meta": {
                "source_url": url,
                "keyword": keyword,
                "sub_keyword": sub_keyword,
            }
        })
        RUNS[run_id]["progress"].update({"status": "done", "eta_seconds": 0})
    except Exception as e:
        RUNS[run_id]["progress"].update({"status": "error", "message": str(e)})
