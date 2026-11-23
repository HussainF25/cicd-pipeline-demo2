import json

import pytest

import app as webapp


@pytest.fixture
def client():
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        yield c


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200


def test_home_page_shows_banner_message(client):
    response = client.get("/")
    assert webapp.BANNER_MESSAGE.encode() in response.data


def test_home_page_shows_version(client):
    response = client.get("/")
    assert f"v{webapp.APP_VERSION}".encode() in response.data


def test_health_endpoint_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "ok"
    assert "version" in body


def test_unknown_page_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_version_format_is_major_minor():
    major, minor = webapp.APP_VERSION.split(".")
    assert major.isdigit() and minor.isdigit()


def test_build_info_defaults_when_file_missing(tmp_path):
    info = webapp.load_build_info(tmp_path / "missing.json")
    assert info["version"] == webapp.APP_VERSION
    assert info["build_number"] == "local"


def test_build_info_reads_ci_metadata(tmp_path):
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps({"version": "1.0.42", "build_number": 42, "commit": "abc1234"}))
    info = webapp.load_build_info(path)
    assert info["version"] == "1.0.42"
    assert info["build_number"] == "42"
    assert info["commit"] == "abc1234"


def test_build_info_ignores_corrupt_file(tmp_path):
    path = tmp_path / "build_info.json"
    path.write_text("{not valid json")
    assert webapp.load_build_info(path)["build_number"] == "local"
