# Khata Expense Tracker: three-tier cloud deployment (SE-490 CEA)

Khata is a multi-user expense tracker. People create an account, record what they spend, set monthly budgets and see where their money goes. It is built as a containerized three-tier web app and deployed on AWS with a GitHub Actions CI/CD pipeline.

## Features

- Landing page, sign up, log in and log out (passwords hashed with scrypt, sessions in signed cookies)
- Every user sees only their own data
- Dashboard: month total, budget left, daily average, six-month trend, spending by category against budgets, recent expenses, month-by-month navigation
- Expenses: add, edit and delete, with filters by month, category and search; pagination; CSV download
- Budgets: a whole-month limit and per-category limits, with warnings at 80% and over budget
- Receipts: optional PNG, JPG, WEBP or PDF uploads stored privately in Amazon S3
- Settings: name, currency, password change, download all data, delete account
- Optional sample data (three months) so a new account has something to show
- `/health` for the load balancer and pipeline; `/api/summary` JSON for the signed-in user
- Responsive down to phone width, with dark mode

## Three tiers

| Tier | What runs | Where on AWS |
|---|---|---|
| Web | Nginx container (`web/`): static CSS/JS, security headers, reverse proxy | EC2 instances in private subnets, behind an Application Load Balancer |
| Application | Flask + Gunicorn container (`app/`) | Same EC2 hosts, internal Docker network only |
| Database | MySQL 8 (Amazon RDS) | Private DB subnets, reachable only from the app hosts, over TLS |

When `DB_HOST` is not set, the app uses a local SQLite file instead, which is how you can run it on a laptop without Docker or MySQL.

## Run it on your laptop (no Docker needed)

Requires Python 3.10 or newer.

```bash
cd app
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install Flask
python wsgi.py
```

Open http://127.0.0.1:5000, create an account (tick *sample expenses* to get a populated dashboard), and click around. Data is stored in `app/expenses.db`; delete that file to start over.

Run the tests:

```bash
pip install pytest
pytest -q
```

## Run all three tiers with Docker (optional)

```bash
docker compose up --build     # http://localhost:8080  (Nginx -> Flask -> MySQL)
```

## Repository layout

```
app/                      Application tier (Flask)
  Dockerfile, requirements.txt, wsgi.py
  expense_app/            auth, views, services (business logic), db (MySQL/SQLite), S3 storage
  expense_app/templates/  all pages (Jinja2)
  tests/                  27 pytest tests (run in CI)
web/                      Web tier (Nginx)
  Dockerfile, nginx.conf, static/css, static/js
docker-compose.yml        Local / CI stack: web + app + MySQL
docker-compose.prod.yml   What runs on each EC2 instance (images from GHCR, RDS, CloudWatch logs)
.github/workflows/deploy.yml   CI/CD: test -> build -> smoke test -> push to GHCR -> deploy via SSM
infra/                    EC2 user data, deploy script, least-privilege IAM policies
docs/                     Architecture diagram
```

## Pipeline

1. **test**: `pytest` against SQLite.
2. **build**: builds both images, starts the full stack with a real MySQL container, then smoke-tests through Nginx: health check, home page, static CSS, a real sign-up with sample data, the dashboard and the CSV export. The images that passed are pushed to `ghcr.io/<owner>/expense-app` and `expense-web`, tagged `sha-<commit>` and `latest`.
3. **deploy**: assumes an AWS role through OIDC (no stored AWS keys), runs `/opt/expense/deploy.sh sha-<commit>` on every instance in the Auto Scaling Group through SSM, then confirms the load balancer serves the new version.

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs session cookies. Must be the same on every instance |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | MySQL / RDS connection |
| `DB_SSL_CA` | CA bundle to verify the RDS TLS certificate (baked into the image) |
| `S3_BUCKET`, `AWS_REGION` | Receipt storage. Uploads are hidden when unset |
| `SQLITE_PATH` | Local database file when `DB_HOST` is unset |
| `SESSION_COOKIE_SECURE=1` | Set once the site is served over HTTPS |

On AWS these are read from SSM Parameter Store (`/expense-tracker/*`) at deploy time.
