# app/models/scan.py
from datetime import datetime
from app.extensions import db

class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    source_url = db.Column(db.String(2048), nullable=False)
    keyword = db.Column(db.String(255))
    num_matches = db.Column(db.Integer, default=0)
    subkeyword  = db.Column(db.String(255))        # NEW
    logic = db.Column(db.String(3))          # NEW: 'AND' or 'OR

    # Keep it simple and portable for SQLite:
    # store any raw results as JSON text (optional)
    results_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

class Crawl(db.Model):
    __tablename__ = "crawl"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
     # From crawler_start form:
    start_url = db.Column(db.String(2048), nullable=False)
    keyword = db.Column(db.String(255), nullable=False)
    sub_keyword = db.Column(db.String(255))
    match_text = db.Column(db.Boolean, default=False)
    match_url = db.Column(db.Boolean, default=False)
    same_domain = db.Column(db.Boolean, default=True)
    backend = db.Column(db.String(50), default="auto")
    pause_seconds = db.Column(db.Float, default=0.3)
    max_pages = db.Column(db.Integer, default=500)
     # For dashboard stats:
    pages_crawled = db.Column(db.Integer, default=0)  # sum for pages visited
    status = db.Column(db.String(50), default="in_progress")  # e.g., completed, failed
    num_matches = db.Column(db.Integer, default=0) 
    # For storing results:
    results_json = db.Column(db.Text)  # JSON dump of matches if needed
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)