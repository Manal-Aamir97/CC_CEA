# ---------- Application tier: Flask + Gunicorn ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SQLITE_PATH=/tmp/expenses.db

WORKDIR /app

# 1) Dependencies first, so this layer is cached between code changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Amazon RDS CA bundle, used to verify the database's TLS certificate
ADD https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /app/certs/rds-global-bundle.pem

# 3) Application code
COPY wsgi.py .
COPY expense_app ./expense_app

# 4) Run as an unprivileged user (least privilege inside the container)
RUN chmod 644 /app/certs/rds-global-bundle.pem \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", \
     "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "wsgi:app"]
