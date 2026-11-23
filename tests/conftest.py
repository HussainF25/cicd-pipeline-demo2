import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make the "backend" package importable from the tests folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import database  # noqa: E402
from backend.cache import cache  # noqa: E402
from backend.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh app with its own empty database file and an empty cache for every test."""
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    cache._store.clear()
    with TestClient(app) as c:  # runs startup: creates tables, seeds courses + admin, starts worker
        yield c


@pytest.fixture
def auth(client):
    """Signs in as the demo admin and returns the Authorization header."""
    res = client.post("/api/login", json={"email": "admin@northfield.edu", "password": "admin123"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['data']['token']}"}
