"""Sign up, log in, log out."""
import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, services
from .constants import CURRENCIES
from .security import login_user

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A real hash to compare against when the email is unknown, so a wrong email
# and a wrong password take the same time to reject.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def safe_next(target: str | None) -> str:
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("main.dashboard"))
    form = {"currency": "Rs", "sample": "1"}
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        currency = form.get("currency", "Rs")
        errors = []
        if not name or len(name) > 80:
            errors.append("Enter your name (up to 80 characters).")
        if not EMAIL_RE.match(email) or len(email) > 255:
            errors.append("Enter a valid email address.")
        if len(password) < 8:
            errors.append("Use a password of at least 8 characters.")
        elif password != form.get("confirm", ""):
            errors.append("The two passwords don't match.")
        if currency not in CURRENCIES:
            currency = "Rs"
        if not errors and db.query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            errors.append("An account with this email already exists. Log in instead.")
        if not errors:
            user_id = db.execute(
                "INSERT INTO users (name, email, password_hash, currency, created_at) VALUES (?, ?, ?, ?, ?)",
                (name, email, generate_password_hash(password), currency, db.now_str()),
            )
            if form.get("sample"):
                services.add_sample_data(user_id)
            login_user(user_id, remember=True)
            flash(f"Welcome, {name.split()[0]}. Your account is ready.", "success")
            return redirect(url_for("main.dashboard"))
        for e in errors:
            flash(e, "error")
    return render_template("auth/signup.html", form=form, currencies=CURRENCIES)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.query("SELECT id, password_hash FROM users WHERE email = ?", (email,), one=True)
        valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
        if user and valid:
            login_user(user["id"], remember=bool(request.form.get("remember")))
            return redirect(safe_next(request.args.get("next")))
        flash("That email and password don't match an account.", "error")
    return render_template("auth/login.html", email=email)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.landing"))
