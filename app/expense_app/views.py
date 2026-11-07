"""Pages of the Expense Tracker (landing page and the signed-in app)."""
import csv
import io
from datetime import date, datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, services, storage
from .constants import CATEGORIES, CATEGORY_COLORS, CURRENCIES, TOTAL_BUDGET_KEY
from .security import login_required

bp = Blueprint("main", __name__)
PAGE_SIZE = 25


# --------------------------------------------------------------------------- #
# Public pages
# --------------------------------------------------------------------------- #
@bp.route("/")
def landing():
    if g.user:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@bp.route("/health")
def health():
    """Used by the ALB target group and the CI/CD pipeline."""
    info = {"instance": current_app.config["INSTANCE_ID"], "version": current_app.config["APP_VERSION"]}
    try:
        db.ping()
        return jsonify(status="ok", database="ok", **info), 200
    except Exception:
        current_app.logger.exception("Health check failed")
        return jsonify(status="error", database="unreachable", **info), 503


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@bp.route("/dashboard")
@login_required
def dashboard():
    start = services.month_start(request.args.get("month"))
    data = services.dashboard_data(g.user["id"], start)
    recent, total_count, _ = services.find_expenses(g.user["id"], None, limit=6)
    return render_template(
        "dashboard.html",
        d=data,
        recent=recent,
        has_any=total_count > 0,
        month=start,
        prev_month=services.add_months(start, -1),
        next_month=services.add_months(start, 1),
        is_current=start == date.today().replace(day=1),
    )


@bp.route("/sample-data", methods=["POST"])
@login_required
def sample_data():
    n = services.add_sample_data(g.user["id"])
    flash(f"Added {n} sample expenses across the last three months. Delete any of them whenever you like.", "success")
    return redirect(url_for("main.dashboard"))


# --------------------------------------------------------------------------- #
# Expenses
# --------------------------------------------------------------------------- #
def _filters():
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    start = None if month == "all" else services.month_start(month)
    category = request.args.get("category", "")
    search = request.args.get("q", "").strip()
    return month, start, category, search


@bp.route("/expenses")
@login_required
def expenses():
    month, start, category, search = _filters()
    page = max(request.args.get("page", 1, type=int), 1)
    rows, count, total = services.find_expenses(
        g.user["id"], start, category, search, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE
    )
    month_options = [services.add_months(date.today().replace(day=1), -i) for i in range(12)]
    return render_template(
        "expenses.html",
        rows=rows,
        count=count,
        total=total,
        page=page,
        pages=max((count + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        month=month,
        start=start,
        category=category,
        search=search,
        month_options=month_options,
    )


def _parse_expense_form(form):
    errors = []
    title = form.get("title", "").strip()
    if not title:
        errors.append("Give the expense a title.")
    elif len(title) > 120:
        errors.append("Keep the title under 120 characters.")
    cents = services.parse_amount(form.get("amount", ""))
    if cents is None:
        errors.append("Enter an amount between 0.01 and 10,000,000.")
    category = form.get("category", "")
    if category not in CATEGORIES:
        errors.append("Choose a category.")
    try:
        spent_on = datetime.strptime(form.get("spent_on", ""), "%Y-%m-%d").date()
        if spent_on.year < 2000 or spent_on > date.today().replace(year=date.today().year + 1):
            raise ValueError
    except ValueError:
        spent_on = None
        errors.append("Enter a valid date.")
    note = form.get("note", "").strip()[:500] or None
    return {"title": title, "amount_cents": cents, "category": category, "spent_on": spent_on, "note": note}, errors


def _upload_receipt(existing_key=None):
    """Returns (new_key or existing_key, error)."""
    file = request.files.get("receipt")
    if not file or not file.filename:
        return existing_key, None
    if not storage.enabled():
        return existing_key, "Receipt uploads aren't set up on this server."
    if not storage.allowed_file(file.filename):
        return existing_key, "Receipts must be PNG, JPG, WEBP or PDF files."
    key = storage.upload_receipt(file, g.user["id"])
    if existing_key:
        storage.delete_receipt(existing_key)
    return key, None


@bp.route("/expenses/new", methods=["GET", "POST"])
@login_required
def new_expense():
    form = {"spent_on": date.today().isoformat(), "category": request.args.get("category", "")}
    if request.method == "POST":
        data, errors = _parse_expense_form(request.form)
        key = None
        if not errors:
            key, err = _upload_receipt()
            if err:
                errors.append(err)
        if not errors:
            db.execute(
                "INSERT INTO expenses (user_id, title, amount_cents, category, spent_on, note, receipt_key, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (g.user["id"], data["title"], data["amount_cents"], data["category"],
                 data["spent_on"].isoformat(), data["note"], key, db.now_str()),
            )
            flash(f"Added {data['title']}.", "success")
            if request.form.get("again"):
                return redirect(url_for("main.new_expense", category=data["category"]))
            return redirect(url_for("main.expenses", month=data["spent_on"].strftime("%Y-%m")))
        for e in errors:
            flash(e, "error")
        form = request.form
    return render_template("expense_form.html", form=form, expense=None)


@bp.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = services.get_expense(g.user["id"], expense_id) or abort(404)
    if request.method == "POST":
        data, errors = _parse_expense_form(request.form)
        key = expense["receipt_key"]
        if not errors:
            key, err = _upload_receipt(expense["receipt_key"])
            if err:
                errors.append(err)
        if not errors:
            db.execute(
                "UPDATE expenses SET title = ?, amount_cents = ?, category = ?, spent_on = ?, note = ?, receipt_key = ? "
                "WHERE id = ? AND user_id = ?",
                (data["title"], data["amount_cents"], data["category"], data["spent_on"].isoformat(),
                 data["note"], key, expense_id, g.user["id"]),
            )
            flash("Saved your changes.", "success")
            return redirect(url_for("main.expenses", month=data["spent_on"].strftime("%Y-%m")))
        for e in errors:
            flash(e, "error")
        form = request.form
    else:
        form = {
            "title": expense["title"],
            "amount": f"{expense['amount_cents'] / 100:.2f}",
            "category": expense["category"],
            "spent_on": expense["spent_on"].isoformat(),
            "note": expense["note"] or "",
        }
    return render_template("expense_form.html", form=form, expense=expense)


@bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = services.get_expense(g.user["id"], expense_id) or abort(404)
    if expense["receipt_key"] and storage.enabled():
        storage.delete_receipt(expense["receipt_key"])
    db.execute("DELETE FROM expenses WHERE id = ? AND user_id = ?", (expense_id, g.user["id"]))
    flash(f"Deleted {expense['title']}.", "success")
    back = request.form.get("back", "")
    if not back.startswith("/") or back.startswith("//"):
        back = url_for("main.expenses")
    return redirect(back)


@bp.route("/expenses/<int:expense_id>/receipt")
@login_required
def view_receipt(expense_id):
    expense = services.get_expense(g.user["id"], expense_id) or abort(404)
    if not expense["receipt_key"] or not storage.enabled():
        abort(404)
    return redirect(storage.presigned_url(expense["receipt_key"]))


@bp.route("/expenses/export.csv")
@login_required
def export_csv():
    month, start, category, search = _filters()
    rows, _, _ = services.find_expenses(g.user["id"], start, category, search)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Title", "Category", f"Amount ({g.user['currency']})", "Note"])
    for r in rows:
        writer.writerow([r["spent_on"].isoformat(), r["title"], r["category"],
                         f"{r['amount_cents'] / 100:.2f}", r["note"] or ""])
    name = f"expenses-{month}.csv"
    return Response(
        "﻿" + buf.getvalue(),  # BOM so Excel opens UTF-8 correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #
@bp.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    user_id = g.user["id"]
    if request.method == "POST":
        new, errors = {}, []
        for key in [TOTAL_BUDGET_KEY] + CATEGORIES:
            raw = request.form.get(f"b_{key}", "").strip()
            if not raw:
                new[key] = None
                continue
            cents = services.parse_amount(raw)
            if cents is None:
                label = "Monthly total" if key == TOTAL_BUDGET_KEY else key
                errors.append(f"{label}: enter a positive amount or leave it empty.")
            else:
                new[key] = cents
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            services.save_budgets(user_id, new)
            flash("Saved your budgets.", "success")
            return redirect(url_for("main.budgets"))
    start = date.today().replace(day=1)
    spent = services.category_totals(user_id, start)
    return render_template(
        "budgets.html",
        budgets=services.get_budgets(user_id),
        spent=spent,
        spent_total=sum(spent.values()),
        month=start,
    )


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = g.user["id"]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = request.form.get("name", "").strip()
            currency = request.form.get("currency", "Rs")
            if not name or len(name) > 80 or currency not in CURRENCIES:
                flash("Enter a name (up to 80 characters) and choose a currency.", "error")
            else:
                db.execute("UPDATE users SET name = ?, currency = ? WHERE id = ?", (name, currency, user_id))
                flash("Saved your profile.", "success")
        elif action == "password":
            row = db.query("SELECT password_hash FROM users WHERE id = ?", (user_id,), one=True)
            new = request.form.get("new_password", "")
            if not check_password_hash(row["password_hash"], request.form.get("current_password", "")):
                flash("Your current password isn't right.", "error")
            elif len(new) < 8:
                flash("Use a new password of at least 8 characters.", "error")
            elif new != request.form.get("confirm_password", ""):
                flash("The new passwords don't match.", "error")
            else:
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), user_id))
                flash("Changed your password.", "success")
        elif action == "delete":
            if request.form.get("confirm_email", "").strip().lower() != g.user["email"]:
                flash("Type your email address exactly to delete your account.", "error")
            else:
                if storage.enabled():
                    for r in db.query(
                        "SELECT receipt_key FROM expenses WHERE user_id = ? AND receipt_key IS NOT NULL", (user_id,)
                    ):
                        storage.delete_receipt(r["receipt_key"])
                db.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,), commit=False)
                db.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,), commit=False)
                db.execute("DELETE FROM users WHERE id = ?", (user_id,))
                session.clear()
                flash("Your account and all its data have been deleted.", "info")
                return redirect(url_for("main.landing"))
        return redirect(url_for("main.settings"))
    stats = db.query(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM expenses WHERE user_id = ?",
        (user_id,),
        one=True,
    )
    return render_template("settings.html", currencies=CURRENCIES, stats=stats)


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #
@bp.route("/api/summary")
@login_required
def api_summary():
    start = services.month_start(request.args.get("month"))
    totals = services.category_totals(g.user["id"], start)
    return jsonify(
        month=start.strftime("%Y-%m"),
        currency=g.user["currency"],
        total=round(sum(totals.values()) / 100, 2),
        by_category={k: round(v / 100, 2) for k, v in totals.items()},
    )


@bp.app_template_global()
def category_color(name):
    return CATEGORY_COLORS.get(name, "#5b6474")
