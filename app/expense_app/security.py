"""CSRF protection, session-based login and the current user."""
import secrets
from functools import wraps

from flask import abort, current_app, flash, g, jsonify, redirect, request, session, url_for

from . import db


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf():
    if request.method != "POST" or not current_app.config.get("CSRF_ENABLED", True):
        return
    sent = request.form.get("csrf_token", "")
    expected = session.get("_csrf", "")
    if not sent or not expected or not secrets.compare_digest(sent, expected):
        abort(400, description="This form expired. Go back, refresh the page and try again.")


def load_current_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    g.user = db.query(
        "SELECT id, name, email, currency, created_at FROM users WHERE id = ?", (user_id,), one=True
    )
    if g.user is None:  # account was deleted
        session.clear()


def login_user(user_id: int, remember: bool = False):
    token = session.get("_csrf")
    session.clear()  # new session id on login (prevents session fixation)
    session["user_id"] = user_id
    session.permanent = remember
    if token:
        session["_csrf"] = token


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="login required"), 401
            flash("Log in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
