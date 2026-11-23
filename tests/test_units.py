"""Small unit tests for helper functions (no web server needed)."""
import json

from backend.auth import create_token, hash_password, verify_password, verify_token
from backend.cache import SimpleCache
from backend.main import grade_for
from backend.version import APP_VERSION, build_info


def test_grade_boundaries():
    assert [grade_for(m) for m in (100, 85, 84.9, 70, 55, 45, 44.9, 0)] == ["A", "A", "B", "B", "C", "D", "F", "F"]


def test_password_hashing():
    stored = hash_password("s3cret")
    assert "s3cret" not in stored
    assert verify_password("s3cret", stored)
    assert not verify_password("wrong", stored)


def test_token_round_trip():
    token = create_token({"email": "a@b.edu", "name": "A", "role": "Registrar"})
    assert verify_token(token)["sub"] == "a@b.edu"
    assert verify_token("not.a.token") is None


def test_cache_expiry_and_delete():
    c = SimpleCache(ttl_seconds=0)
    c.set("k", 1)
    assert c.get("k") is None  # expired straight away
    c = SimpleCache(ttl_seconds=60)
    c.set("k", 1)
    assert c.get("k") == 1
    c.delete("k")
    assert c.get("k") is None


def test_version_is_major_minor():
    major, minor = APP_VERSION.split(".")
    assert major.isdigit() and minor.isdigit()


def test_build_info_defaults_and_ci_file(tmp_path):
    assert build_info(tmp_path / "missing.json")["build_number"] == "local"
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps({"version": "1.0.7", "build_number": 7, "commit": "abc1234"}))
    info = build_info(path)
    assert info["version"] == "1.0.7" and info["build_number"] == "7"
    assert info["release_note"]
