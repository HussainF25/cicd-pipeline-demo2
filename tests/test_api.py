"""Unit tests for the Student Management System API.

The CI/CD pipeline runs these on every push and stops (no build, no deploy) if any fail.
"""
import time


def wait_for_notification(client, auth, text, timeout=5.0):
    """The worker sends notifications asynchronously, so poll the outbox briefly."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = client.get("/api/notifications", headers=auth).json()["data"]
        if any(text in n["message"] for n in items):
            return True
        time.sleep(0.2)
    return False


def add_student(client, auth, name="Ayesha Khan", email="ayesha@example.com", course_ids=(1,)):
    res = client.post("/api/students", headers=auth,
                      json={"name": name, "email": email, "program": "MS Data Science", "course_ids": list(course_ids)})
    assert res.status_code == 200, res.text
    return res.json()


# ---------- health + frontend ----------
def test_health_is_open_and_reports_version(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["release_note"]


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Northfield University" in res.text


# ---------- authentication ----------
def test_api_rejects_requests_without_login(client):
    assert client.get("/api/students").status_code == 401


def test_login_with_wrong_password_fails(client):
    res = client.post("/api/login", json={"email": "admin@northfield.edu", "password": "wrong"})
    assert res.status_code == 401


def test_login_returns_token_that_unlocks_api(client, auth):
    res = client.get("/api/me", headers=auth)
    assert res.status_code == 200
    assert res.json()["data"]["role"] == "Registrar"


def test_tampered_token_is_rejected(client, auth):
    bad = {"Authorization": auth["Authorization"][:-2] + "xx"}
    assert client.get("/api/students", headers=bad).status_code == 401


# ---------- students ----------
def test_register_student_gets_roll_number_and_welcome_email(client, auth):
    out = add_student(client, auth)
    assert out["data"]["roll_no"] == "NU-0001"
    assert out["trace"] == ["api", "db", "queue"]  # saved, then handed to the queue
    assert wait_for_notification(client, auth, "Welcome to Northfield University, Ayesha Khan")


def test_duplicate_email_is_rejected(client, auth):
    add_student(client, auth)
    res = client.post("/api/students", headers=auth,
                      json={"name": "Copy", "email": "ayesha@example.com", "program": "MS DS", "course_ids": []})
    assert res.status_code == 400


def test_delete_student_removes_their_records(client, auth):
    sid = add_student(client, auth)["data"]["id"]
    client.post("/api/results/bulk", headers=auth, json={"course_id": 1, "marks": [{"student_id": sid, "marks": 80}]})
    assert client.delete(f"/api/students/{sid}", headers=auth).status_code == 200
    assert client.get(f"/api/students/{sid}", headers=auth).status_code == 404
    assert client.get("/api/results", headers=auth).json()["data"] == []


# ---------- caching ----------
def test_courses_are_cached_and_cache_is_cleared_on_change(client, auth):
    first = client.get("/api/courses", headers=auth).json()
    second = client.get("/api/courses", headers=auth).json()
    assert first["trace"] == ["api", "cache-miss", "db"]
    assert second["trace"] == ["api", "cache"]
    assert len(second["data"]) == 3  # seeded courses

    client.post("/api/courses", headers=auth, json={"code": "ds504", "title": "Cloud Computing"})
    third = client.get("/api/courses", headers=auth).json()
    assert third["trace"] == ["api", "cache-miss", "db"]  # cache was invalidated
    assert "DS504" in [c["code"] for c in third["data"]]


# ---------- attendance ----------
def test_low_attendance_queues_a_warning(client, auth):
    sid = add_student(client, auth)["data"]["id"]
    res = client.post("/api/attendance/bulk", headers=auth, json={
        "course_id": 1, "date": "2026-11-20", "records": [{"student_id": sid, "present": False}]})
    body = res.json()
    assert body["data"]["at_risk"] == 1
    assert "queue" in body["trace"]
    assert wait_for_notification(client, auth, "below the required 75%")


# ---------- results ----------
def test_publish_results_returns_immediately_and_emails_later(client, auth):
    sid = add_student(client, auth)["data"]["id"]
    client.post("/api/results/bulk", headers=auth, json={"course_id": 1, "marks": [{"student_id": sid, "marks": 91}]})

    started = time.time()
    res = client.post("/api/results/publish", headers=auth, json={"course_id": 1})
    assert time.time() - started < 0.9  # the worker takes ~1s per email, so the API did not wait
    assert res.json()["data"]["published"] == 1
    assert wait_for_notification(client, auth, "grade A")


def test_marks_outside_0_to_100_are_rejected(client, auth):
    res = client.post("/api/results/bulk", headers=auth, json={"course_id": 1, "marks": [{"student_id": 1, "marks": 120}]})
    assert res.status_code == 422
