# app/blueprints/main/routes.py
from flask import render_template, request, redirect, url_for, send_file, flash, session, jsonify
from urllib.parse import urlparse
import uuid, threading, io, os, math, time
from datetime import datetime
from flask_login import login_required

from .tasks import run_scan_task, RUNS
from .parser_utils import render_results_html
from .fetch_utils import BACKENDS
from . import bp

APP_TITLE = "Flask Forum Link Scraper"

@bp.route("/scraper", methods=["GET","POST"])
def scraper():
    if request.method == "GET":
        session.pop("run_id", None)
        return render_template("index.html", title=APP_TITLE, backends=BACKENDS)

    session.pop("run_id", None)
    url = (request.form.get("url") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    sub_keyword = (request.form.get("sub_keyword") or "").strip()

    match_text = request.form.get("match_text") == "on"
    match_url = request.form.get("match_url") == "on"
    same_domain = request.form.get("same_domain") == "on"
    referer = (request.form.get("referer") or "").strip() or None
    cookies_raw = (request.form.get("cookies") or "").strip() or None
    backend = (request.form.get("backend") or os.environ.get("FETCH_BACKEND","auto")).strip().lower()
    if backend not in BACKENDS:
        backend = "auto"

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
        return redirect(url_for("main.scraper"))
    if not keyword:
        flash("Keyword cannot be empty.", "error")
        return redirect(url_for("main.scraper"))

    run_id = str(uuid.uuid4())
    RUNS[run_id] = {"results": [],
                    "meta": {"source_url": url, "keyword": keyword, "sub_keyword": sub_keyword},
                    "progress": {"status":"queued","current":0,"total":0}}
    session["run_id"] = run_id

    t = threading.Thread(target=run_scan_task, kwargs=dict(
        run_id=run_id, url=url, keyword=keyword, sub_keyword=sub_keyword,
        match_text=match_text, match_url=match_url, same_domain=same_domain,
        referer=referer, cookies_raw=cookies_raw, backend=backend,
        pause_seconds=pause_seconds, max_pages=max_pages
    ), daemon=True)
    t.start()

    return redirect(url_for("main.results", page=1))

@bp.get("/results")
def results():
    run_id = session.get("run_id")
    data = RUNS.get(run_id) if run_id else None
    if not data:
        flash("No results to display. Please run a new scan.", "error")
        return redirect(url_for("main.scraper"))

    status = data.get("progress", {}).get("status", "done")
    matches = data.get("results", [])
    meta = data.get("meta", {})
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

    return render_template("results.html",
        title=APP_TITLE,
        source_url=meta.get("source_url"),
        keyword=meta.get("keyword"),
        sub_keyword=meta.get("sub_keyword"),
        matches=matches[start:end],
        page=page, total_pages=total_pages, per_page=per_page, total=total,
        start_index=start, run_id=run_id, status=status
    )

@bp.get("/export/html")
def export_html():
    data = session.get("last_results")
    if not data:
        run_id = session.get("run_id")
        run = RUNS.get(run_id) if run_id else None
        if run:
            data = {"matches": run.get("results", []),
                    "source_url": run.get("meta", {}).get("source_url", ""),
                    "keyword": run.get("meta", {}).get("keyword", "")}
    if not data:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    html_content = render_results_html(data["matches"], data["source_url"], data["keyword"])
    buf = io.BytesIO(html_content.encode("utf-8"))
    return send_file(buf, mimetype="text/html", as_attachment=True,
                     download_name=f"filtered_links_{int(time.time())}.html")

@bp.get("/export/csv")
def export_csv():
    run_id = session.get("run_id")
    run = RUNS.get(run_id) if run_id else None
    if not run:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    matches = run.get("results", [])
    import csv
    s = io.StringIO()
    w = csv.writer(s)
    w.writerow(["#", "Text", "URL"])
    for i, (text, url) in enumerate(matches, start=1):
        w.writerow([i, text or url, url])

    mem = io.BytesIO(s.getvalue().encode("utf-8-sig"))
    return send_file(mem, mimetype="text/csv", as_attachment=True,
                     download_name=f"links_{int(time.time())}.csv")

@bp.get("/export/xlsx")
def export_xlsx():
    run_id = session.get("run_id")
    run = RUNS.get(run_id) if run_id else None
    if not run:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active; ws.title = "Links"
    ws.append(["#", "Text", "URL"])
    for i, (text, url) in enumerate(run.get("results", []), start=1):
        ws.append([i, text or url, url])
    for col in ("A","B","C"):
        ws.column_dimensions[col].width = 40 if col != "A" else 6

    mem = io.BytesIO(); wb.save(mem); mem.seek(0)
    return send_file(mem,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"links_{int(time.time())}.xlsx")

@bp.get("/")
def landing():
    return render_template("landing.html", title="Welcome", current_year=datetime.utcnow().year)

@bp.get("/dashboard")
@login_required
def dashboard():
    stats = {"total_scans": 0, "total_matches": 0, "last_scan": None}
    return render_template("dashboard.html", title="Dashboard", stats=stats, recent_scans=[])

@bp.get("/history")
@login_required
def history():
    return render_template("history.html", title="History", scans=[])

@bp.get("/progress/<run_id>")
def progress(run_id):
    data = RUNS.get(run_id)
    if not data:
        return jsonify({"status": "missing"}), 404
    prog = data.get("progress", {"current": 0, "total": 0, "status": "idle"})
    return jsonify(prog)
