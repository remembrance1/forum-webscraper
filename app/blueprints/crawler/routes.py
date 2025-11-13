from flask import render_template, request, redirect, url_for, flash, session, jsonify, send_file
from urllib.parse import urlparse
import os, threading, io, time, math
from . import bp
from .tasks import CRAWLS, run_crawl_task
from app.blueprints.main.fetch_utils import BACKENDS  # for UI select, reuse
from app.blueprints.main.parser_utils import render_results_html  # reuse your exporter HTML

from app.models import Crawl
import re, html
from flask_login import login_required, current_user
from app.extensions import db
from json import dumps
import json 

TAG_RE = re.compile(r"<[^>]+>")

APP_TITLE = "Flask Site Crawler"

def _dedupe_by_url(items):
    seen = set()
    out = []
    for it in items:
        # Reuse your coercer to robustly extract the URL across dict/tuple/str
        _, url = _coerce_item(it)
        if url and url not in seen:
            seen.add(url)
            out.append(it)
    return out

def _coerce_item(item):
    """Return (text, url) from dict|tuple|str."""
    if isinstance(item, dict):
        url = item.get("url") or ""
        text = item.get("title") or item.get("text") or ""
        return (_clean(text) or url, url)
    elif isinstance(item, (list, tuple)):
        if len(item) >= 2:
            return (_clean(item[0] or ""), (item[1] or ""))
        elif len(item) == 1:
            x = item[0] or ""
            return (_clean(x), x)
    x = str(item)
    return (_clean(x), x)

def _clean(s: str) -> str:
    if not s:
        return ""
    # unescape any &lt;...&gt; etc.
    s = html.unescape(s)
    # drop tags
    s = TAG_RE.sub("", s)
    # collapse whitespace
    return " ".join(s.split())

@bp.get("/")
def crawler_form():
    session.pop("crawl_id", None)
    return render_template("crawler_index.html", title=APP_TITLE, backends=BACKENDS)

@bp.post("/")
def crawler_start():
    session.pop("crawl_id", None)
    session.pop("crawler_saved", None)
    url = (request.form.get("url") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    sub_keyword = (request.form.get("sub_keyword") or "").strip()

    match_text = request.form.get("match_text") == "on"
    match_url = request.form.get("match_url") == "on"
    same_domain = request.form.get("same_domain") != "off"  # default True
    backend = (request.form.get("backend") or os.environ.get("FETCH_BACKEND","auto")).strip().lower()
    if backend not in BACKENDS:
        backend = "auto"

    try:
        max_pages = int(request.form.get("max_pages") or 500)
    except ValueError:
        max_pages = 500
    max_pages = max(1, min(max_pages, 5000))  # hard safety cap

    try:
        pause_ms = int(request.form.get("pause_ms") or 300)
    except ValueError:
        pause_ms = 300
    pause_seconds = max(0, pause_ms) / 1000.0

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        flash("Please provide a full URL including https://", "error")
        return redirect(url_for("crawler.crawler_form"))
    if not keyword:
        flash("Keyword cannot be empty.", "error")
        return redirect(url_for("crawler.crawler_form"))

    crawl_id = run_crawl_task(
        start_url=url,
        keyword=keyword,
        sub_keyword=sub_keyword,
        match_text=match_text,
        match_url=match_url,
        same_domain=same_domain,
        backend=backend,
        pause_seconds=pause_seconds,
        max_pages=max_pages,
    )
    session["crawl_id"] = crawl_id
    return redirect(url_for("crawler.crawler_results", page=1))

@bp.get("/results")
def crawler_results():
    crawl_id = session.get("crawl_id")
    data = CRAWLS.get(crawl_id) if crawl_id else None
    if not data:
        flash("No crawl in progress. Start a new one.", "error")
        return redirect(url_for("crawler.crawler_form"))

    # progress/status info
    progress_data = data.get("progress", {}) or {}
    status = progress_data.get("status", "done")

    # results for display
    raw_matches = data.get("results") or []
    matches = _dedupe_by_url(raw_matches)

    meta = data.get("meta", {}) or {}
    total = len(matches)

    # --- persist once when done and authenticated ---
    if status == "done" and current_user.is_authenticated and not session.get("crawler_saved"):
        try:
            crawl = Crawl(
                user_id=current_user.id,
                start_url=(meta.get("start_url") or "")[:2048],
                keyword=(meta.get("keyword") or "")[:255],
                sub_keyword=meta.get("sub_keyword"),
                match_text=bool(meta.get("match_text")),
                match_url=bool(meta.get("match_url")),
                same_domain=bool(meta.get("same_domain", True)),
                backend=meta.get("backend") or "auto",
                pause_seconds=float(meta.get("pause_seconds") or 0.3),
                max_pages=int(meta.get("max_pages") or 500),
                pages_crawled=int(
                    progress_data.get("visited")
                    or progress_data.get("pages_crawled")
                    or progress_data.get("page")
                    or 0
                ),
                status=status,
                num_matches = total,
                results_json=dumps(matches),   # store deduped matches
            )
            db.session.add(crawl)
            db.session.commit()
            session["crawler_saved"] = True
        except Exception as e:
            db.session.rollback()
            flash(f"Saved crawl partially, but could not store history: {e}", "warning")

    # pagination
    per_page = 30

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page

    return render_template(
        "crawler_results.html",
        title="Flask Site Crawler",
        source_url=meta.get("start_url"),
        keyword=meta.get("keyword"),
        sub_keyword=meta.get("sub_keyword"),
        match_text=meta.get("match_text"),
        match_url=meta.get("match_url"),
        same_domain=meta.get("same_domain"),
        max_pages=meta.get("max_pages"),
        matches=matches[start:end],
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        total=total,
        start_index=start,
        run_id=crawl_id,
        status=status,
    )


@bp.get("/progress/<crawl_id>")
def progress(crawl_id):
    data = CRAWLS.get(crawl_id)
    if not data:
        return jsonify({"status":"missing"}), 404
    return jsonify(data["progress"])

@bp.get("/export/html")
def export_html():
    crawl_id = session.get("crawl_id")
    run = CRAWLS.get(crawl_id) if crawl_id else None
    if not run:
        flash("No results to export yet.", "error")
        return redirect(url_for("crawler.crawler_form"))

    html_content = render_results_html(run["results"], run["meta"]["start_url"], run["meta"]["keyword"])
    buf = io.BytesIO(html_content.encode("utf-8"))
    return send_file(buf, mimetype="text/html", as_attachment=True,
                     download_name=f"crawler_links_{int(time.time())}.html")

@bp.get("/export/csv")
def export_csv():
    crawl_id = session.get("crawl_id")
    run = CRAWLS.get(crawl_id) if crawl_id else None
    if not run:
        flash("No results to export yet.", "error")
        return redirect(url_for("crawler.crawler_form"))

    import csv
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(["#", "Text", "URL"])
    for i, (text, url) in enumerate(run["results"], start=1):
        w.writerow([i, text or url, url])
    mem = io.BytesIO(s.getvalue().encode("utf-8-sig"))
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                     download_name=f"crawler_links_{int(time.time())}.csv")

@bp.get("/export/xlsx")
def export_xlsx():
    crawl_id = session.get("crawl_id")
    run = CRAWLS.get(crawl_id) if crawl_id else None
    if not run:
        flash("No results to export yet.", "error")
        return redirect(url_for("crawler.crawler_form"))

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active; ws.title = "Links"
    ws.append(["#", "Text", "URL"])
    for i, (text, url) in enumerate(run["results"], start=1):
        ws.append([i, text or url, url])
    for col in ("A","B","C"):
        ws.column_dimensions[col].width = 40 if col != "A" else 6
    mem = io.BytesIO(); wb.save(mem); mem.seek(0)
    return send_file(mem,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"crawler_links_{int(time.time())}.xlsx")

@bp.get("/crawl/<int:crawl_id>")
@login_required
def crawl_detail(crawl_id):
    # Only show crawls belonging to the current user
    crawl = Crawl.query.filter_by(id=crawl_id, user_id=current_user.id).first_or_404()

    # Decode stored results
    try:
        raw_matches = json.loads(crawl.results_json) if crawl.results_json else []
    except Exception:
        raw_matches = []

    matches = _dedupe_by_url(raw_matches)
    total = len(matches)
    per_page = 30

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page

    return render_template(
        "crawler_results.html",
        title="Flask Site Crawler",
        source_url=crawl.start_url,
        keyword=crawl.keyword,
        sub_keyword=crawl.sub_keyword,
        match_text=crawl.match_text,
        match_url=crawl.match_url,
        same_domain=crawl.same_domain,
        max_pages=crawl.max_pages,
        matches=matches[start:end],
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        total=total,
        start_index=start,
        run_id=crawl.id,          # just an identifier for the template
        status=crawl.status,
    )
