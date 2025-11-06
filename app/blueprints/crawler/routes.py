from flask import render_template, request, redirect, url_for, flash, session, jsonify, send_file
from urllib.parse import urlparse
import os, threading, io, time, math
from . import bp
from .tasks import CRAWLS, run_crawl_task
from app.blueprints.main.fetch_utils import BACKENDS  # for UI select, reuse
from app.blueprints.main.parser_utils import render_results_html  # reuse your exporter HTML

APP_TITLE = "Flask Site Crawler"

@bp.get("/")
def crawler_form():
    session.pop("crawl_id", None)
    return render_template("crawler_index.html", title=APP_TITLE, backends=BACKENDS)

@bp.post("/")
def crawler_start():
    session.pop("crawl_id", None)
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

    status = data["progress"]["status"]
    matches = data["results"]
    meta = data["meta"]

    per_page = 30
    total = len(matches)

    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1

    total_pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page

    return render_template(
        "crawler_results.html",        # ← use the new template
        title="Flask Site Crawler",
        source_url=meta.get("start_url"),
        keyword=meta.get("keyword"),
        sub_keyword=meta.get("sub_keyword"),
        match_text=meta.get("match_text"),        # pass flags for the details panel
        match_url=meta.get("match_url"),
        same_domain=meta.get("same_domain"),
        max_pages=meta.get("max_pages"),
        matches=matches[start:end],
        page=page, total_pages=total_pages, per_page=per_page, total=total,
        start_index=start, run_id=crawl_id, status=status
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
