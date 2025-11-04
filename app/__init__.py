# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from pathlib import Path
import os

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"  # where to send unauthenticated users


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # 🔐 Secret key management
    key_file = Path(__file__).resolve().parent.parent / ".flask_secret_key"
    if key_file.exists():
        app.secret_key = key_file.read_text().strip()
    else:
        app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

    # ⚙️ Database configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///webscan.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Models must be imported after db init
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from .routes import main_bp
    from .auth import auth_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # First-run: create database tables
    with app.app_context():
        db.create_all()

    # Optional: allow {{ now() }} in templates
    from datetime import datetime

    @app.context_processor
    def inject_now():
        return {"now": datetime.utcnow}

    return app
