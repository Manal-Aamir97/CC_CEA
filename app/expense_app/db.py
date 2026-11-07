"""Database access for the data tier.

Two back ends behind one small API:
  * MySQL (Amazon RDS in production) via PyMySQL, when DB_HOST is set
  * SQLite (Python standard library) for local runs and the test suite

All SQL in the app is written with "?" placeholders and portable syntax;
for MySQL the placeholders are rewritten to "%s". One connection is opened
per request and closed when the request ends.
"""
import sqlite3
from datetime import date, datetime

from flask import current_app, g

SCHEMA = {
    "sqlite": [
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(80) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'Rs',
            created_at VARCHAR(19) NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(120) NOT NULL,
            amount_cents BIGINT NOT NULL,
            category VARCHAR(40) NOT NULL,
            spent_on DATE NOT NULL,
            note VARCHAR(500),
            receipt_key VARCHAR(255),
            created_at VARCHAR(19) NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses (user_id, spent_on)",
        """CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category VARCHAR(40) NOT NULL,
            amount_cents BIGINT NOT NULL,
            UNIQUE (user_id, category)
        )""",
    ],
    "mysql": [
        """CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(80) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            currency VARCHAR(8) NOT NULL DEFAULT 'Rs',
            created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS expenses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(120) NOT NULL,
            amount_cents BIGINT NOT NULL,
            category VARCHAR(40) NOT NULL,
            spent_on DATE NOT NULL,
            note VARCHAR(500),
            receipt_key VARCHAR(255),
            created_at DATETIME NOT NULL,
            INDEX idx_expenses_user_date (user_id, spent_on),
            CONSTRAINT fk_expenses_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        """CREATE TABLE IF NOT EXISTS budgets (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            category VARCHAR(40) NOT NULL,
            amount_cents BIGINT NOT NULL,
            UNIQUE KEY uq_budget_user_category (user_id, category),
            CONSTRAINT fk_budgets_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    ],
}


def backend() -> str:
    return "mysql" if current_app.config.get("DB_HOST") else "sqlite"


def _connect():
    cfg = current_app.config
    if backend() == "mysql":
        import pymysql  # only needed in production

        ssl = {"ca": cfg["DB_SSL_CA"]} if cfg.get("DB_SSL_CA") else None
        return pymysql.connect(
            host=cfg["DB_HOST"],
            port=int(cfg.get("DB_PORT") or 3306),
            user=cfg["DB_USER"],
            password=cfg["DB_PASSWORD"],
            database=cfg["DB_NAME"],
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            ssl=ssl,
        )
    conn = sqlite3.connect(cfg["SQLITE_PATH"], timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect()
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _sql(sql: str) -> str:
    return sql.replace("?", "%s") if backend() == "mysql" else sql


def _normalize(row) -> dict:
    out = dict(row)
    for key in ("spent_on",):
        if isinstance(out.get(key), str):
            out[key] = date.fromisoformat(out[key][:10])
    return out


def query(sql: str, params=(), one: bool = False):
    cur = get_db().cursor()
    try:
        cur.execute(_sql(sql), tuple(params))
        rows = [_normalize(r) for r in cur.fetchall()]
    finally:
        cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, params=(), commit: bool = True) -> int:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(_sql(sql), tuple(params))
        last_id = cur.lastrowid
    finally:
        cur.close()
    if commit:
        conn.commit()
    return last_id


def executemany(sql: str, rows, commit: bool = True) -> None:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.executemany(_sql(sql), [tuple(r) for r in rows])
    finally:
        cur.close()
    if commit:
        conn.commit()


def commit():
    get_db().commit()


def ping() -> bool:
    query("SELECT 1 AS ok")
    return True


def now_str() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def init_schema() -> None:
    conn = get_db()
    cur = conn.cursor()
    try:
        for statement in SCHEMA[backend()]:
            cur.execute(statement)
    finally:
        cur.close()
    conn.commit()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
