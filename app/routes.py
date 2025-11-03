from flask import Blueprint, render_template, request, redirect, url_for, send_file, flash, session, jsonify
from urllib.parse import urlparse
import uuid
import threading
import io
import os
import math
import time
from datetime import datetime

from .tasks import run_scan_task, RUNS
from .parser_utils import render_results_html
from .fetch_utils import BACKENDS

main_bp = Blueprint("main", __name__)

APP_TITLE = "Flask Forum Link Scraper"

@main_bp.route("/scraper", methods=["GET", "POST"])
def scraper():
    if request.method == "GET":
        # Clear any previous run when loading the form
        session.pop("run_id", None)
        return render_template("index.html", title=APP_TITLE, backends=BACKENDS)

    # ---------- POST branch ----------
    session.pop("run_id", None)  # clear previous run just in case

    url = (request.form.get("url") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    sub_keyword = (request.form.get("sub_keyword") or "").strip()  # optional refine filter

    match_text = request.form.get("match_text") == "on"
    match_url = request.form.get("match_url") == "on"
    same_domain = request.form.get("same_domain") == "on"
    referer = (request.form.get("referer") or "").strip() or None
    cookies_raw = (request.form.get("cookies") or "").strip() or None
    backend = (request.form.get("backend") or os.environ.get("FETCH_BACKEND", "auto")).strip().lower()
    if backend not in BACKENDS:
        backend = "auto"

    # Optional pagination inputs
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

    # ---------- Start a background thread ----------
    run_id = str(uuid.uuid4())
    RUNS[run_id] = {
        "results": [],
        "meta": {
            "source_url": url,
            "keyword": keyword,
            "sub_keyword": sub_keyword,
        },
        "progress": {"status": "queued", "current": 0, "total": 0},
    }
    session["run_id"] = run_id  # small cookie-safe token

    t = threading.Thread(
        target=run_scan_task,
        kwargs=dict(
            run_id=run_id,
            url=url,
            keyword=keyword,
            sub_keyword=sub_keyword,
            match_text=match_text,
            match_url=match_url,
            same_domain=same_domain,
            referer=referer,
            cookies_raw=cookies_raw,
            backend=backend,
            pause_seconds=pause_seconds,
            max_pages=max_pages,
        ),
        daemon=True,
    )
    t.start()

    # Immediately redirect to the results page where progress will be displayed
    return redirect(url_for("main.results", page=1))


@main_bp.route("/export/html")
def export_html():
    # Legacy session store, else fall back to current run
    data = session.get("last_results")
    if not data:
        run_id = session.get("run_id")
        run = RUNS.get(run_id) if run_id else None
        if run:
            data = {
                "matches": run.get("results", []),
                "source_url": run.get("meta", {}).get("source_url", ""),
                "keyword": run.get("meta", {}).get("keyword", ""),
            }

    if not data:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    html_content = render_results_html(data["matches"], data["source_url"], data["keyword"])
    buf = io.BytesIO(html_content.encode("utf-8"))
    filename = f"filtered_links_{int(time.time())}.html"
    return send_file(buf, mimetype="text/html", as_attachment=True, download_name=filename)


@main_bp.get("/results")
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
    page_items = matches[start:end]

    return render_template(
        "results.html",
        title=APP_TITLE,
        source_url=meta.get("source_url"),
        keyword=meta.get("keyword"),
        sub_keyword=meta.get("sub_keyword"),
        matches=page_items,  # only the current slice
        match_text=request.args.get("match_text") == "on" if "match_text" in request.args else None,
        match_url=request.args.get("match_url") == "on" if "match_url" in request.args else None,
        same_domain=request.args.get("same_domain") == "on" if "same_domain" in request.args else None,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        total=total,
        start_index=start,  # for global numbering
        run_id=run_id,
        status=status,
    )

@main_bp.get("/progress/<run_id>")
def progress(run_id):
    data = RUNS.get(run_id)
    if not data:
        return jsonify({"status": "missing"}), 404
    prog = data.get("progress", {"current": 0, "total": 0, "status": "idle"})
    return jsonify(prog)

@main_bp.get("/export/csv")
def export_csv():
    run_id = session.get("run_id")
    run = RUNS.get(run_id) if run_id else None
    if not run:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    matches = run.get("results", [])
    import csv, io, time
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["#", "Text", "URL"])
    for i, (text, url) in enumerate(matches, start=1):
        w.writerow([i, text or url, url])

    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))  # BOM for Excel-friendly UTF-8
    filename = f"links_{int(time.time())}.csv"
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name=filename)


@main_bp.get("/export/xlsx")
def export_xlsx():
    run_id = session.get("run_id")
    run = RUNS.get(run_id) if run_id else None
    if not run:
        flash("No results to export yet. Run a scan first.", "error")
        return redirect(url_for("main.scraper"))

    matches = run.get("results", [])
    import io, time
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Links"
    ws.append(["#", "Text", "URL"])
    for i, (text, url) in enumerate(matches, start=1):
        ws.append([i, text or url, url])

    # Optional: autosize columns
    for col in ("A", "B", "C"):
        ws.column_dimensions[col].width = 40 if col != "A" else 6

    mem = io.BytesIO()
    wb.save(mem)
    mem.seek(0)
    filename = f"links_{int(time.time())}.xlsx"
    return send_file(mem, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=filename)

@main_bp.get("/")
def landing():
    return render_template("landing.html", title="Welcome", current_year=datetime.utcnow().year)

@main_bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html", title="Dashboard")

@main_bp.get("/history")
def history():
    # stub page for now
    return render_template("history.html", title="History", scans=[])
