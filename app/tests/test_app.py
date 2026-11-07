from datetime import date

from conftest import signup

TODAY = date.today().isoformat()
THIS_MONTH = TODAY[:7]


def add(client, **overrides):
    data = {"title": "Groceries", "amount": "1,250.50", "category": "Food & Groceries",
            "spent_on": TODAY, "note": "weekly shop"}
    data.update(overrides)
    return client.post("/expenses/new", data=data, follow_redirects=True)


# ---------- public pages & health ----------
def test_landing_page_is_public(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"Know where every rupee went" in res.data
    assert b"Khata Expense Tracker" in res.data


def test_health_reports_database_ok(client):
    body = client.get("/health").get_json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert "instance" in body and "version" in body


def test_app_pages_require_login(client):
    for path in ["/dashboard", "/expenses", "/budgets", "/settings", "/expenses/new"]:
        res = client.get(path)
        assert res.status_code == 302 and "/login" in res.headers["Location"], path
    assert client.get("/api/summary").status_code == 401


def test_unknown_page_is_404(client):
    res = client.get("/no-such-page")
    assert res.status_code == 404 and b"Page not found" in res.data


# ---------- accounts ----------
def test_signup_logs_in_and_shows_empty_dashboard(client):
    res = signup(client)
    assert b"Your account is ready" in res.data
    assert b"Your khata is empty" in res.data


def test_signup_validation(client):
    res = client.post("/signup", data={"name": "", "email": "bad", "password": "short", "confirm": "short"},
                      follow_redirects=True)
    assert b"Enter your name" in res.data
    assert b"valid email" in res.data
    assert b"at least 8 characters" in res.data


def test_duplicate_email_rejected(client):
    signup(client)
    client.post("/logout")
    res = signup(client, email="SARA@example.com")
    assert b"already exists" in res.data


def test_login_logout(client):
    signup(client)
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302
    res = client.post("/login", data={"email": "sara@example.com", "password": "wrong-password"}, follow_redirects=True)
    assert b"don&#39;t match an account" in res.data
    res = client.post("/login", data={"email": "sara@example.com", "password": "correct-horse"}, follow_redirects=True)
    assert b"Hello Sara" in res.data


def test_login_next_is_restricted_to_local_paths(client):
    signup(client)
    client.post("/logout")
    res = client.post("/login?next=https://evil.example", data={"email": "sara@example.com", "password": "correct-horse"})
    assert res.headers["Location"].endswith("/dashboard")


def test_signup_with_sample_data_fills_dashboard(client):
    res = signup(client, sample=True)
    assert b"Last six months" in res.data
    assert b"Budget left" in res.data
    body = client.get(f"/api/summary?month={THIS_MONTH}").get_json()
    assert body["total"] > 0


# ---------- expenses ----------
def test_add_expense_and_see_it(user):
    res = add(user)
    assert b"Added Groceries" in res.data
    assert b"1,250.50" in res.data


def test_expense_validation(user):
    res = add(user, title="", amount="-5", category="Nope", spent_on="31-31-2026")
    for msg in [b"Give the expense a title", b"Enter an amount", b"Choose a category", b"valid date"]:
        assert msg in res.data
    assert b"No expenses here" in user.get("/expenses").data


def test_edit_and_delete(user, app):
    add(user)
    res = user.post("/expenses/1/edit", data={"title": "Fuel", "amount": "3000", "category": "Transport",
                                               "spent_on": TODAY, "note": ""}, follow_redirects=True)
    assert b"Saved your changes" in res.data and b"Fuel" in res.data and b"3,000.00" in res.data
    res = user.post("/expenses/1/delete", follow_redirects=True)
    assert b"Deleted Fuel" in res.data
    assert user.get("/expenses/1/edit").status_code == 404


def test_users_cannot_see_each_others_expenses(client):
    signup(client, email="a@example.com")
    add(client, title="Secret purchase")
    client.post("/logout")
    signup(client, email="b@example.com", name="Bilal")
    assert b"Secret purchase" not in client.get("/expenses?month=all").data
    assert client.get("/expenses/1/edit").status_code == 404
    assert client.post("/expenses/1/delete").status_code == 404
    assert client.get(f"/api/summary?month={THIS_MONTH}").get_json()["total"] == 0


def test_filters_search_and_month(user):
    add(user, title="Old rent", amount="20000", category="Rent", spent_on="2020-01-15")
    add(user, title="Bus card", amount="500", category="Transport")
    assert b"Old rent" not in user.get(f"/expenses?month={THIS_MONTH}").data
    assert b"Old rent" in user.get("/expenses?month=2020-01").data
    res = user.get("/expenses?month=all&q=bus")
    assert b"Bus card" in res.data and b"Old rent" not in res.data
    res = user.get("/expenses?month=all&category=Rent")
    assert b"Old rent" in res.data and b"Bus card" not in res.data


def test_csv_export(user):
    add(user, title='Chai, "special"', amount="180")
    res = user.get("/expenses/export.csv?month=all")
    assert res.mimetype == "text/csv"
    text = res.data.decode("utf-8-sig")
    assert text.splitlines()[0] == "Date,Title,Category,Amount (Rs),Note"
    assert '"Chai, ""special""",Food & Groceries,180.00' in text


def test_summary_api(user):
    add(user, title="Lunch", amount="500")
    add(user, title="Dinner", amount="700")
    add(user, title="Bus", amount="100", category="Transport")
    body = user.get(f"/api/summary?month={THIS_MONTH}").get_json()
    assert body["total"] == 1300.0
    assert body["by_category"] == {"Food & Groceries": 1200.0, "Transport": 100.0}


# ---------- budgets & dashboard ----------
def test_budgets_save_and_flag_overspending(user):
    res = user.post("/budgets", data={"b___total__": "1000", "b_Food & Groceries": "500"}, follow_redirects=True)
    assert b"Saved your budgets" in res.data
    add(user, title="Feast", amount="800")
    res = user.get("/dashboard")
    assert b"over budget" in res.data            # category over 500
    assert b"of Rs 1,000" in res.data            # total budget shown
    res = user.post("/budgets", data={"b___total__": "abc"}, follow_redirects=True)
    assert b"enter a positive amount" in res.data


def test_dashboard_month_navigation(user):
    add(user, title="Old rent", amount="20000", category="Rent", spent_on="2020-01-15")
    res = user.get("/dashboard?month=2020-01")
    assert b"January 2020" in res.data and b"20,000" in res.data


# ---------- settings ----------
def test_settings_profile_password_delete(client):
    signup(client)
    res = client.post("/settings", data={"action": "profile", "name": "Sara K", "currency": "$"}, follow_redirects=True)
    assert b"Saved your profile" in res.data
    res = client.post("/settings", data={"action": "password", "current_password": "nope",
                                          "new_password": "new-password-1", "confirm_password": "new-password-1"},
                      follow_redirects=True)
    assert b"current password isn" in res.data
    res = client.post("/settings", data={"action": "password", "current_password": "correct-horse",
                                          "new_password": "new-password-1", "confirm_password": "new-password-1"},
                      follow_redirects=True)
    assert b"Changed your password" in res.data
    add(client)
    res = client.post("/settings", data={"action": "delete", "confirm_email": "sara@example.com"}, follow_redirects=True)
    assert b"have been deleted" in res.data
    res = client.post("/login", data={"email": "sara@example.com", "password": "new-password-1"}, follow_redirects=True)
    assert b"don&#39;t match an account" in res.data


# ---------- security ----------
def test_csrf_blocks_posts_without_token(app):
    app.config["CSRF_ENABLED"] = True
    client = app.test_client()
    res = client.post("/signup", data={"name": "x"})
    assert res.status_code == 400 and b"form expired" in res.data


def test_csrf_token_allows_post(app):
    app.config["CSRF_ENABLED"] = True
    client = app.test_client()
    client.get("/signup")
    with client.session_transaction() as s:
        token = s["_csrf"]
    res = client.post("/signup", data={"csrf_token": token, "name": "Ali", "email": "ali@example.com",
                                       "password": "password123", "confirm": "password123", "currency": "Rs"})
    assert res.status_code == 302


def test_passwords_are_hashed(client, app):
    signup(client)
    with app.app_context():
        from expense_app import db
        row = db.query("SELECT password_hash FROM users", one=True)
    assert "correct-horse" not in row["password_hash"]
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_receipt_upload_rejected_when_s3_not_configured(user):
    from io import BytesIO
    res = user.post("/expenses/new", data={"title": "Book", "amount": "900", "category": "Education",
                                           "spent_on": TODAY, "receipt": (BytesIO(b"fake"), "r.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"aren&#39;t set up" in res.data
