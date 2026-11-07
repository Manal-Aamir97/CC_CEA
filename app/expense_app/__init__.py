"""Expense Tracker - application tier (Flask).

All configuration comes from environment variables so the same container
image runs unchanged on a laptop, in CI and on AWS. No credentials live in the
code or the image: on EC2 they are read from AWS SSM Parameter Store at deploy
time and passed in as environment variables.

Database: MySQL (Amazon RDS) when DB_HOST is set, otherwise a local SQLite file.
"""
import logging
import os
import socket
from datetime import timedelta

from flask import Flask, g, render_template

from . import db, storage
from .constants import CATEGORIES, CURRENCIES
from .security import check_csrf, csrf_token, load_current_user
from .services import format_money


def _existing_file(path: str) -> str:
    return path if path and os.path.isfile(path) else ""


def create_app(test_config: dict | None = None) -> Flask:
    # static_folder=None in production: Nginx (web tier) serves /static/.
    # For a plain local run without Nginx, set SERVE_STATIC=1.
    static_dir = os.environ.get("STATIC_DIR") or os.path.join(os.path.dirname(__file__), "..", "..", "web", "static")
    serve_static = os.environ.get("SERVE_STATIC") == "1" and os.path.isdir(static_dir)
    app = Flask(
        __name__,
        static_folder=os.path.abspath(static_dir) if serve_static else None,
        static_url_path="/static",
    )

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DB_HOST=os.environ.get("DB_HOST", ""),
        DB_PORT=os.environ.get("DB_PORT", "3306"),
        DB_NAME=os.environ.get("DB_NAME", "expensedb"),
        DB_USER=os.environ.get("DB_USER", "expense"),
        DB_PASSWORD=os.environ.get("DB_PASSWORD", ""),
        DB_SSL_CA=_existing_file(os.environ.get("DB_SSL_CA", "")),
        SQLITE_PATH=os.environ.get("SQLITE_PATH", os.path.join(os.getcwd(), "expenses.db")),
        S3_BUCKET=os.environ.get("S3_BUCKET", ""),
        AWS_REGION=os.environ.get("AWS_REGION", "us-east-1"),
        INSTANCE_ID=os.environ.get("INSTANCE_ID") or socket.gethostname(),
        APP_VERSION=os.environ.get("APP_VERSION", "dev"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,  # 5 MB receipts
        CSRF_ENABLED=True,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",  # set to 1 once HTTPS is on
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db.init_app(app)

    with app.app_context():
        try:
            db.init_schema()
        except Exception:  # DB may not be reachable yet; /health reports it
            app.logger.exception("Could not create tables at startup")

    @app.before_request
    def before():
        load_current_user()
        check_csrf()

    @app.context_processor
    def globals_():
        currency = g.user["currency"] if getattr(g, "user", None) else "Rs"
        return {
            "csrf_token": csrf_token,
            "currency": currency,
            "currencies": CURRENCIES,
            "categories": CATEGORIES,
            "instance_id": app.config["INSTANCE_ID"],
            "app_version": app.config["APP_VERSION"],
            "receipts_enabled": storage.enabled(),
        }

    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["money0"] = lambda c: format_money(c, decimals=False)

    from . import auth, views

    app.register_blueprint(auth.bp)
    app.register_blueprint(views.bp)

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, title="Page not found",
                               message="That page doesn't exist, or it belongs to another account."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, title="Something was wrong with that request",
                               message=getattr(e, "description", "")), 400

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("error.html", code=413, title="That file is too large",
                               message="Receipts can be up to 5 MB."), 413

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500, title="Something went wrong on our side",
                               message="Try again in a minute."), 500

    return app
