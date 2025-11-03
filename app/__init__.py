from flask import Flask

def create_app():
    app = Flask(__name__, template_folder="templates")
    # Set your key via env in prod: export FLASK_SECRET_KEY='change-me'
    import os
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Register blueprints
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app
