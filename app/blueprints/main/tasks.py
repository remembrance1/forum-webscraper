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
        # Initialise progress info
        RUNS[run_id]["progress"].update({"status": "running", "current": 0, "total": max_pages})
        all_links = []

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
            all_links.extend(extract_links(html_text, page_url))
            RUNS[run_id]["progress"].update({"current": i})

        matches = filter_links(
            all_links, keyword, match_text, match_url, same_domain, base_url=url
        )
        if sub_keyword:
            matches = subfilter_links(matches, sub_keyword, match_text=match_text, match_url=match_url)

        RUNS[run_id].update({
            "results": matches,
            "meta": {
                "source_url": url,
                "keyword": keyword,
                "sub_keyword": sub_keyword,
            }
        })
        RUNS[run_id]["progress"].update({"status": "done"})
    except Exception as e:
        RUNS[run_id]["progress"].update({"status": "error", "message": str(e)})
