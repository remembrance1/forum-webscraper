import threading, time, uuid, collections, re
from urllib.parse import urlparse, urljoin, urldefrag
from urllib import robotparser

from app.blueprints.main.fetch_utils import smart_fetch
from app.blueprints.main.parser_utils import extract_links
from app.blueprints.main.parser_utils import subfilter_links  # your improved comma/plus logic

from app.models import Crawl
from app.extensions import db
import json
import traceback

CRAWLS = {}  # crawl_id -> {"results": [(text,url)...], "progress": {...}, "meta": {...}}

def _normalize_url(base, href):
    if not href:
        return None
    # absolute + strip fragment
    abs_url = urljoin(base, href)
    abs_url, _frag = urldefrag(abs_url)
    return abs_url

def _same_host(u1, u2):
    return urlparse(u1).netloc.lower() == urlparse(u2).netloc.lower()

def run_crawl_task(start_url, keyword, sub_keyword="", match_text=True, match_url=True,
                   same_domain=True, backend="auto", pause_seconds=0.30, max_pages=500, max_depth=4):
    crawl_id = str(uuid.uuid4())
    CRAWLS[crawl_id] = {
        "results": [],
        "progress": {"status":"queued", "current":0, "total":max_pages, "visited":0, "queued":1, "matches":0},
        "meta": {
            "start_url": start_url,
            "keyword": keyword,
            "sub_keyword": sub_keyword,
            "match_text": match_text,
            "match_url": match_url,
            "same_domain": same_domain,
            "max_pages": max_pages
        }
    }

    t = threading.Thread(target=_crawl_worker, kwargs=dict(
        crawl_id=crawl_id, start_url=start_url, keyword=keyword, sub_keyword=sub_keyword,
        match_text=match_text, match_url=match_url, same_domain=same_domain,
        backend=backend, pause_seconds=pause_seconds, max_pages=max_pages, max_depth=max_depth
    ), daemon=True)
    t.start()
    return crawl_id

def _crawl_worker(crawl_id, start_url, keyword, sub_keyword, match_text, match_url,
                  same_domain, backend, pause_seconds, max_pages, max_depth):
    state = CRAWLS[crawl_id]
    prog = state["progress"]
    results = state["results"]

    try:
        # robots.txt
        rp = robotparser.RobotFileParser()
        try:
            base = f"{urlparse(start_url).scheme}://{urlparse(start_url).netloc}"
            rp.set_url(urljoin(base, "/robots.txt"))
            rp.read()
        except Exception:
            rp = None  # best-effort only

        visited = set()
        q = collections.deque([(start_url, 0)])
        domain_root = start_url

        prog["status"] = "running"

        while q and len(visited) < max_pages:
            url, depth = q.popleft()
            if url in visited:
                continue
            if same_domain and not _same_host(domain_root, url):
                continue
            if rp and not rp.can_fetch("*", url):
                continue

            visited.add(url)
            prog["visited"] = len(visited)
            prog["queued"] = len(q)

            # fetch HTML (smart_fetch already handles headers/timeouts)
            html = smart_fetch(url, referer=None, cookie_str=None, backend=backend)
            final_url = url            # we don't get a redirect URL back; use the requested URL
            content_type = "text/html" # fetch_utils returns text only; treat as HTML

            if not html:
                continue

            # get links on this page
            pairs = extract_links(html, base_url=final_url or url)  # -> [(text, href), ...]
            # keyword filter
            kw = (keyword or "").strip().lower()
            if kw:
                pairs = [(t, u) for (t, u) in pairs if
                         ((match_text and t and kw in (t or "").lower()) or
                          (match_url and u and kw in (u or "").lower()))]

            # sub-filter (supports comma=OR, plus=AND as per your function)
            pairs = subfilter_links(pairs, sub_keyword,
                                    match_text=match_text, match_url=match_url)

            # add matches
            if pairs:
                results.extend(pairs)
                prog["matches"] = len(results)

            # enqueue discovered links (BFS)
            if depth < max_depth:
                for _t, href in extract_links(html, base_url=final_url or url):
                    nxt = _normalize_url(final_url or url, href)
                    if not nxt:
                        continue
                    if same_domain and not _same_host(domain_root, nxt):
                        continue
                    if nxt not in visited:
                        q.append((nxt, depth + 1))

            prog["current"] = len(visited)
            # politeness
            time.sleep(pause_seconds)

        prog["status"] = "done"

    except Exception as e:
        import traceback
        prog["status"] = "error"
        prog["message"] = f"{type(e).__name__}: {e}"
        # optionally log it to console for debugging
        traceback.print_exc()
    
    finally:
        # ✅ Update DB record when crawl finishes <- new!!!!!
        try:
            crawl = Crawl.query.get(crawl_id)
            if crawl:
                crawl.pages_crawled = prog.get("visited", 0)
                crawl.status = prog.get("status", "done")
                crawl.results_json = json.dumps(results)
                db.session.commit()
        except Exception as db_err:
            print(f"DB update failed: {db_err}")

