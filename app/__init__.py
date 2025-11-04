# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import os

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"   # where to send unauthenticated users

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # secrets & DB
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")  # replace in prod
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///webscan.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    # models must be imported after db init
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # blueprints
    from .routes import main_bp
    from .auth import auth_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")

    # first-run DB create
    with app.app_context():
        db.create_all()

    # (optional) allow {{ now() }} in templates
    from datetime import datetime
    @app.context_processor
    def inject_now(): return {"now": datetime.utcnow}

    return app
