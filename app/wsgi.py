"""Entry point.

Production (inside the container):  gunicorn wsgi:app
Local, without Docker:              python wsgi.py   ->  http://127.0.0.1:5000
"""
import os

if __name__ == "__main__":
    os.environ.setdefault("SERVE_STATIC", "1")  # no Nginx locally, so Flask serves CSS/JS

from expense_app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
