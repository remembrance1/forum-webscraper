# app/models/scan.py
from datetime import datetime
from app.extensions import db

class Scan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    source_url = db.Column(db.String(2048), nullable=False)
    keyword = db.Column(db.String(255))
    num_matches = db.Column(db.Integer, default=0)
    #subkeyword  = db.Column(db.String(255))        # NEW
    #logic = db.Column(db.String(3))          # NEW: 'AND' or 'OR

    # Keep it simple and portable for SQLite:
    # store any raw results as JSON text (optional)
    results_json = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
