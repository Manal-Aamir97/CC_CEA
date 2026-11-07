import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from expense_app import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SQLITE_PATH": str(tmp_path / "test.db"),
        "DB_HOST": "",
        "CSRF_ENABLED": False,
        "S3_BUCKET": "",
        "SECRET_KEY": "test",
    })


@pytest.fixture
def client(app):
    return app.test_client()


def signup(client, email="sara@example.com", password="correct-horse", name="Sara Khan", sample=False):
    data = {"name": name, "email": email, "password": password, "confirm": password, "currency": "Rs"}
    if sample:
        data["sample"] = "1"
    return client.post("/signup", data=data, follow_redirects=True)


@pytest.fixture
def user(client):
    signup(client)
    return client
