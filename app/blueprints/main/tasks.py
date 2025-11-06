import time

from .parser_utils import (
    extract_links, filter_links, subfilter_links, iterate_forum_pages
)

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
                matches_accum.extend(page_matches)

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
