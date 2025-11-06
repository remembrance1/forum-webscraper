# app/blueprints/auth/routes.py
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import User
from app.extensions import db
from . import bp

@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("login.html", title="Sign in", minimal=True)

@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    pw = request.form.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.pw_hash, pw):
        flash("Invalid email or password.", "error")
        return redirect(url_for("auth.login"))
    login_user(user, remember=True)
    return redirect(url_for("main.dashboard"))

@bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("register.html", title="Create account")

@bp.post("/register")
def register_post():
    email = (request.form.get("email") or "").strip().lower()
    pw = request.form.get("password") or ""
    pw2 = request.form.get("password2") or ""

    if not email or not pw or not pw2:
        flash("Email, password, and confirmation are required.", "error")
        return redirect(url_for("auth.register"))
    if pw != pw2:
        flash("Passwords do not match.", "error")
        return redirect(url_for("auth.register"))
    if len(pw) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("auth.register"))
    if User.query.filter_by(email=email).first():
        flash("Email is already registered.", "error")
        return redirect(url_for("auth.register"))

    user = User(email=email, pw_hash=generate_password_hash(pw))
    db.session.add(user)
    db.session.commit()

    flash("Account created successfully. Please sign in.", "success")
    return redirect(url_for("auth.login"))

@bp.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
