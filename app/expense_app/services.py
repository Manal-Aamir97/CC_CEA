"""Business logic: money handling, monthly summaries, budgets, sample data."""
import random
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import db
from .constants import CATEGORIES, CATEGORY_COLORS, TOTAL_BUDGET_KEY

MAX_AMOUNT_CENTS = 1_000_000_000  # 10,000,000.00


# --------------------------------------------------------------------------- #
# Money and dates
# --------------------------------------------------------------------------- #
def parse_amount(text) -> int | None:
    """'1,250.5' -> 125050 cents. Returns None if not a positive amount."""
    try:
        value = Decimal(str(text).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    cents = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents <= 0 or cents > MAX_AMOUNT_CENTS:
        return None
    return cents


def format_money(cents, decimals: bool = True) -> str:
    cents = int(cents or 0)
    if decimals:
        return f"{cents / 100:,.2f}"
    whole = (Decimal(cents) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{int(whole):,}"


def month_start(value: str | None = None) -> date:
    try:
        return datetime.strptime(value or "", "%Y-%m").date()
    except ValueError:
        return date.today().replace(day=1)


def add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def month_range(start: date) -> tuple[str, str]:
    return start.isoformat(), add_months(start, 1).isoformat()


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def category_totals(user_id: int, start: date) -> dict[str, int]:
    lo, hi = month_range(start)
    rows = db.query(
        "SELECT category, SUM(amount_cents) AS total, COUNT(*) AS n FROM expenses "
        "WHERE user_id = ? AND spent_on >= ? AND spent_on < ? GROUP BY category",
        (user_id, lo, hi),
    )
    return {r["category"]: int(r["total"] or 0) for r in rows}


def month_count(user_id: int, start: date) -> int:
    lo, hi = month_range(start)
    row = db.query(
        "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ? AND spent_on >= ? AND spent_on < ?",
        (user_id, lo, hi),
        one=True,
    )
    return int(row["n"])


def get_budgets(user_id: int) -> dict[str, int]:
    rows = db.query("SELECT category, amount_cents FROM budgets WHERE user_id = ?", (user_id,))
    return {r["category"]: int(r["amount_cents"]) for r in rows}


def save_budgets(user_id: int, budgets: dict[str, int | None]) -> None:
    """budgets maps category (or TOTAL_BUDGET_KEY) -> cents, or None to remove."""
    for category, cents in budgets.items():
        db.execute("DELETE FROM budgets WHERE user_id = ? AND category = ?", (user_id, category), commit=False)
        if cents:
            db.execute(
                "INSERT INTO budgets (user_id, category, amount_cents) VALUES (?, ?, ?)",
                (user_id, category, cents),
                commit=False,
            )
    db.commit()


def monthly_trend(user_id: int, months: int = 6, end: date | None = None) -> list[dict]:
    """Totals for the last `months` months, oldest first, ending with `end`'s month."""
    end = end or date.today().replace(day=1)
    first = add_months(end, -(months - 1))
    rows = db.query(
        "SELECT spent_on, SUM(amount_cents) AS total FROM expenses "
        "WHERE user_id = ? AND spent_on >= ? AND spent_on < ? GROUP BY spent_on",
        (user_id, first.isoformat(), add_months(end, 1).isoformat()),
    )
    totals = {add_months(first, i): 0 for i in range(months)}
    for r in rows:
        key = r["spent_on"].replace(day=1)
        totals[key] = totals.get(key, 0) + int(r["total"] or 0)
    peak = max(totals.values()) or 1
    return [
        {
            "month": m,
            "label": m.strftime("%b"),
            "total": t,
            "pct": round(t / peak * 100),
            "current": m == end,
        }
        for m, t in totals.items()
    ]


def dashboard_data(user_id: int, start: date) -> dict:
    totals = category_totals(user_id, start)
    budgets = get_budgets(user_id)
    spent = sum(totals.values())
    today = date.today()
    next_month = add_months(start, 1)
    if start > today:
        days_counted = 0
    elif next_month <= today:
        days_counted = (next_month - start).days
    else:
        days_counted = (today - start).days + 1
    days_left = max((next_month - today).days, 0) if start <= today < next_month else 0

    rows = []
    for category in CATEGORIES:
        amount = totals.get(category, 0)
        budget = budgets.get(category)
        if not amount and not budget:
            continue
        rows.append(
            {
                "category": category,
                "color": CATEGORY_COLORS[category],
                "spent": amount,
                "budget": budget,
                "share": round(amount / spent * 100) if spent else 0,
                "budget_pct": min(round(amount / budget * 100), 100) if budget else None,
                "over": bool(budget and amount > budget),
            }
        )
    rows.sort(key=lambda r: r["spent"], reverse=True)
    peak = max((r["spent"] for r in rows), default=0) or 1
    for r in rows:
        r["bar_pct"] = round(r["spent"] / peak * 100)

    total_budget = budgets.get(TOTAL_BUDGET_KEY)
    trend = monthly_trend(user_id, 6, start)
    prev_total = trend[-2]["total"]
    change = (spent - prev_total) if (prev_total or spent) else None
    return {
        "change": change,
        "change_pct": round(change / prev_total * 100) if (change is not None and prev_total) else None,
        "prev_label": trend[-2]["month"].strftime("%B"),
        "spent": spent,
        "count": month_count(user_id, start),
        "daily_avg": spent // days_counted if days_counted else 0,
        "days_left": days_left,
        "total_budget": total_budget,
        "budget_left": (total_budget - spent) if total_budget else None,
        "budget_pct": min(round(spent / total_budget * 100), 100) if total_budget else None,
        "categories": rows,
        "trend": trend,
    }


def find_expenses(user_id: int, start: date | None, category: str = "", search: str = "",
                  limit: int | None = None, offset: int = 0):
    where = ["user_id = ?"]
    params: list = [user_id]
    if start is not None:
        lo, hi = month_range(start)
        where += ["spent_on >= ?", "spent_on < ?"]
        params += [lo, hi]
    if category in CATEGORIES:
        where.append("category = ?")
        params.append(category)
    if search:
        where.append("(title LIKE ? OR note LIKE ?)")
        like = f"%{search[:60]}%"
        params += [like, like]
    clause = " AND ".join(where)
    summary = db.query(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(amount_cents), 0) AS total FROM expenses WHERE {clause}",
        params,
        one=True,
    )
    sql = f"SELECT * FROM expenses WHERE {clause} ORDER BY spent_on DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    return db.query(sql, params), int(summary["n"]), int(summary["total"])


def get_expense(user_id: int, expense_id: int):
    return db.query("SELECT * FROM expenses WHERE id = ? AND user_id = ?", (expense_id, user_id), one=True)


# --------------------------------------------------------------------------- #
# Sample data (so a new account has something to look at)
# --------------------------------------------------------------------------- #
SAMPLE_ITEMS = {
    "Food & Groceries": [("Weekly groceries", 3500, 7500), ("Lunch at the cafeteria", 350, 900),
                         ("Chai and samosas", 150, 400), ("Dinner with friends", 1500, 4000)],
    "Transport": [("Ride to campus", 300, 900), ("Bus card top-up", 500, 1500), ("Fuel", 2500, 6000)],
    "Bills & Utilities": [("Electricity bill", 3500, 9000), ("Mobile package", 600, 1500),
                          ("Internet bill", 2500, 4000)],
    "Education": [("Course books", 1500, 4500), ("Printing and photocopies", 100, 600),
                  ("Online course", 2000, 5000)],
    "Health": [("Pharmacy", 400, 2500), ("Doctor's visit", 1500, 3500)],
    "Shopping": [("Clothes", 2000, 7000), ("Phone charger", 800, 2000)],
    "Entertainment": [("Cinema tickets", 900, 2000), ("Streaming subscription", 450, 1200)],
}
SAMPLE_PER_MONTH = {"Food & Groceries": 9, "Transport": 6, "Bills & Utilities": 3, "Education": 2,
                    "Health": 1, "Shopping": 1, "Entertainment": 2}


def add_sample_data(user_id: int, months: int = 3) -> int:
    rng = random.Random(user_id * 7919)
    today = date.today()
    rows = []
    for back in range(months):
        start = add_months(today.replace(day=1), -back)
        last_day = (add_months(start, 1) - timedelta(days=1)).day
        max_day = today.day if back == 0 else last_day
        for category, count in SAMPLE_PER_MONTH.items():
            for _ in range(count if back else max(1, round(count * max_day / last_day))):
                title, lo, hi = rng.choice(SAMPLE_ITEMS[category])
                amount = rng.randrange(lo, hi, 10) * 100
                day = rng.randint(1, max_day)
                rows.append((user_id, title, amount, category, start.replace(day=day).isoformat(),
                             None, None, db.now_str()))
    db.executemany(
        "INSERT INTO expenses (user_id, title, amount_cents, category, spent_on, note, receipt_key, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
        commit=False,
    )
    if not get_budgets(user_id):
        save_budgets(user_id, {TOTAL_BUDGET_KEY: 6000000, "Food & Groceries": 2500000,
                               "Transport": 800000, "Entertainment": 300000})
    db.commit()
    return len(rows)
