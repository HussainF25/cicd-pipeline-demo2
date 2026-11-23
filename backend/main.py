"""APPLICATION TIER - FastAPI backend (REST API, JSON).

Every response is {"data": ..., "trace": [...]}. The trace lists which architecture
components handled the request (shown in the app at http://127.0.0.1:8000/?system).
All /api routes except /api/login require a valid login token (JWT).
/health is open so the CI/CD pipeline can check which version is live.
"""
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import sqlite3

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import create_token, verify_password, verify_token
from .cache import cache
from .database import get_conn, init_db
from .events import publish_event, start_worker
from .version import build_info


@asynccontextmanager
async def lifespan(app):
    init_db()
    start_worker()
    yield


app = FastAPI(title="Student Management System API", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def require_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    user = verify_token(creds.credentials) if creds else None
    if not user:
        raise HTTPException(401, "Your session has ended. Sign in again.")
    return user


api = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def reply(data, *trace):
    return {"data": data, "trace": ["api", *trace]}


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def grade_for(marks):
    for limit, grade in ((85, "A"), (70, "B"), (55, "C"), (45, "D")):
        if marks >= limit:
            return grade
    return "F"


# ---------- request bodies ----------
class LoginIn(BaseModel):
    email: str
    password: str


class StudentIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200)
    program: str = Field(min_length=1, max_length=120)
    course_ids: list[int] = []


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=12)
    title: str = Field(min_length=2, max_length=120)


class AttendanceRecord(BaseModel):
    student_id: int
    present: bool


class AttendanceBulkIn(BaseModel):
    course_id: int
    date: str
    records: list[AttendanceRecord]


class MarkIn(BaseModel):
    student_id: int
    marks: float = Field(ge=0, le=100)


class ResultsBulkIn(BaseModel):
    course_id: int
    marks: list[MarkIn]


class PublishIn(BaseModel):
    course_id: int


# ---------- health check (open) - used by the deploy script and the CI/CD pipeline ----------
@app.get("/health")
def health():
    info = build_info()
    return {"status": "ok", "version": info["version"], "build_number": info["build_number"],
            "commit": info["commit"], "built_at": info["built_at"], "release_note": info["release_note"]}


# ---------- login (the other open route) ----------
@app.post("/api/login")
def login(body: LoginIn):
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
    conn.close()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "That email and password don't match. Check them and try again.")
    return reply({"token": create_token(user), "name": user["name"], "role": user["role"]}, "db")


@api.get("/me")
def me(user=Depends(require_user)):
    return reply({"name": user["name"], "role": user["role"], "email": user["sub"]})


# ---------- students ----------
def _set_enrolments(conn, student_id, course_ids):
    conn.execute("DELETE FROM enrolments WHERE student_id = ?", (student_id,))
    conn.executemany("INSERT OR IGNORE INTO enrolments (student_id, course_id) VALUES (?, ?)",
                     [(student_id, c) for c in set(course_ids)])


@api.get("/students")
def list_students():
    conn = get_conn()
    students = rows(conn.execute("SELECT * FROM students ORDER BY id DESC"))
    enrol = conn.execute("SELECT student_id, course_id FROM enrolments").fetchall()
    conn.close()
    by_student = {}
    for e in enrol:
        by_student.setdefault(e["student_id"], []).append(e["course_id"])
    for s in students:
        s["course_ids"] = sorted(by_student.get(s["id"], []))
    return reply(students, "db")


@api.get("/students/{student_id}")
def student_profile(student_id: int):
    conn = get_conn()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        raise HTTPException(404, "This student no longer exists.")
    courses = rows(conn.execute(
        """SELECT c.id, c.code, c.title,
                  (SELECT COUNT(*) FROM attendance a WHERE a.student_id = e.student_id AND a.course_id = c.id) AS total,
                  (SELECT COALESCE(SUM(present), 0) FROM attendance a WHERE a.student_id = e.student_id AND a.course_id = c.id) AS attended,
                  r.marks, r.grade, r.published
           FROM enrolments e JOIN courses c ON c.id = e.course_id
           LEFT JOIN results r ON r.student_id = e.student_id AND r.course_id = c.id
           WHERE e.student_id = ? ORDER BY c.code""", (student_id,)))
    conn.close()
    return reply({**dict(student), "courses": courses}, "db")


@api.post("/students")
def create_student(body: StudentIn):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO students (name, email, program) VALUES (?, ?, ?)",
                           (body.name.strip(), body.email.strip().lower(), body.program.strip()))
        sid = cur.lastrowid
        roll = f"NU-{sid:04d}"
        conn.execute("UPDATE students SET roll_no = ? WHERE id = ?", (roll, sid))
        _set_enrolments(conn, sid, body.course_ids)
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "A student with this email is already registered.")
    finally:
        conn.close()
    publish_event("WELCOME", body.email.strip().lower(),
                  f"Welcome to Northfield University, {body.name.strip()}! Your roll number is {roll}.")
    return reply({"id": sid, "roll_no": roll}, "db", "queue")


@api.put("/students/{student_id}")
def update_student(student_id: int, body: StudentIn):
    conn = get_conn()
    try:
        cur = conn.execute("UPDATE students SET name = ?, email = ?, program = ? WHERE id = ?",
                           (body.name.strip(), body.email.strip().lower(), body.program.strip(), student_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "This student no longer exists.")
        _set_enrolments(conn, student_id, body.course_ids)
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Another student already uses this email.")
    finally:
        conn.close()
    cache.delete("results")
    return reply({"id": student_id}, "db", "cache-cleared")


@api.delete("/students/{student_id}")
def delete_student(student_id: int):
    conn = get_conn()
    # remove related records first (fixed SQL strings - flagged as B608 by the Bandit security scan before)
    conn.execute("DELETE FROM attendance WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM results WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM enrolments WHERE student_id = ?", (student_id,))
    cur = conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "This student no longer exists.")
    cache.delete("results")
    return reply({"deleted": student_id}, "db", "cache-cleared")


# ---------- courses (cached) ----------
@api.get("/courses")
def list_courses():
    cached = cache.get("courses")
    if cached is not None:
        return reply(cached, "cache")
    conn = get_conn()
    data = rows(conn.execute("SELECT * FROM courses ORDER BY code"))
    conn.close()
    cache.set("courses", data)
    return reply(data, "cache-miss", "db")


@api.post("/courses")
def create_course(body: CourseIn):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO courses (code, title) VALUES (?, ?)",
                           (body.code.strip().upper(), body.title.strip()))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(400, "A course with this code already exists.")
    finally:
        conn.close()
    cache.delete("courses")
    return reply({"id": cur.lastrowid}, "db", "cache-cleared")


# ---------- attendance ----------
@api.get("/attendance")
def get_attendance(course_id: int, date: str):
    conn = get_conn()
    data = rows(conn.execute(
        "SELECT student_id, present FROM attendance WHERE course_id = ? AND date = ?", (course_id, date)))
    conn.close()
    return reply(data, "db")


@api.post("/attendance/bulk")
def save_class_attendance(body: AttendanceBulkIn):
    """Save a whole class register for one course and date (re-saving replaces it)."""
    conn = get_conn()
    conn.execute("DELETE FROM attendance WHERE course_id = ? AND date = ?", (body.course_id, body.date))
    conn.executemany(
        "INSERT INTO attendance (student_id, course_id, date, present) VALUES (?, ?, ?, ?)",
        [(r.student_id, body.course_id, body.date, int(r.present)) for r in body.records],
    )
    conn.commit()
    at_risk = rows(conn.execute(
        """SELECT s.email, s.name, c.code, ROUND(100.0 * SUM(a.present) / COUNT(*)) AS pct
           FROM attendance a JOIN students s ON s.id = a.student_id JOIN courses c ON c.id = a.course_id
           WHERE a.course_id = ? AND a.student_id IN (SELECT student_id FROM attendance WHERE course_id = ? AND date = ?)
           GROUP BY a.student_id HAVING pct < 75""", (body.course_id, body.course_id, body.date)))
    conn.close()
    for r in at_risk:
        publish_event("LOW_ATTENDANCE", r["email"],
                      f"{r['name']}, your attendance in {r['code']} is {int(r['pct'])}%, below the required 75%.")
    trace = ["db", "queue"] if at_risk else ["db"]
    return reply({"saved": len(body.records), "at_risk": len(at_risk)}, *trace)


@api.get("/attendance/summary")
def attendance_summary():
    conn = get_conn()
    data = rows(conn.execute(
        """SELECT a.student_id, a.course_id, s.name, c.code, COUNT(*) AS total, SUM(a.present) AS attended,
                  CAST(ROUND(100.0 * SUM(a.present) / COUNT(*)) AS INTEGER) AS percentage
           FROM attendance a JOIN students s ON s.id = a.student_id JOIN courses c ON c.id = a.course_id
           GROUP BY a.student_id, a.course_id ORDER BY s.name, c.code"""))
    conn.close()
    return reply(data, "db")


# ---------- results (cached, published asynchronously) ----------
@api.get("/results")
def list_results():
    cached = cache.get("results")
    if cached is not None:
        return reply(cached, "cache")
    conn = get_conn()
    data = rows(conn.execute(
        """SELECT r.id, r.student_id, r.course_id, s.name, c.code, r.marks, r.grade, r.published
           FROM results r JOIN students s ON s.id = r.student_id JOIN courses c ON c.id = r.course_id
           ORDER BY c.code, s.name"""))
    conn.close()
    cache.set("results", data)
    return reply(data, "cache-miss", "db")


@api.post("/results/bulk")
def save_class_results(body: ResultsBulkIn):
    """Save marks for a whole course at once (the gradebook screen)."""
    conn = get_conn()
    conn.executemany(
        """INSERT INTO results (student_id, course_id, marks, grade, published) VALUES (?, ?, ?, ?, 0)
           ON CONFLICT(student_id, course_id) DO UPDATE SET marks = excluded.marks, grade = excluded.grade,
           published = CASE WHEN results.marks = excluded.marks THEN results.published ELSE 0 END""",
        [(m.student_id, body.course_id, m.marks, grade_for(m.marks)) for m in body.marks],
    )
    conn.commit()
    conn.close()
    cache.delete("results")  # cache invalidation
    return reply({"saved": len(body.marks)}, "db", "cache-cleared")


@api.post("/results/publish")
def publish_results(body: PublishIn):
    conn = get_conn()
    pending = rows(conn.execute(
        """SELECT s.email, s.name, c.code, r.grade FROM results r
           JOIN students s ON s.id = r.student_id JOIN courses c ON c.id = r.course_id
           WHERE r.course_id = ? AND r.published = 0""", (body.course_id,)))
    conn.execute("UPDATE results SET published = 1 WHERE course_id = ?", (body.course_id,))
    conn.commit()
    conn.close()
    cache.delete("results")
    for r in pending:  # one message per student - the API does NOT wait for sending
        publish_event("RESULTS_PUBLISHED", r["email"],
                      f"{r['name']}, your {r['code']} result has been published: grade {r['grade']}.")
    return reply({"published": len(pending)}, "db", "cache-cleared", "queue")


# ---------- notifications (written by the background worker) ----------
@api.get("/notifications")
def list_notifications():
    conn = get_conn()
    data = rows(conn.execute("SELECT * FROM notifications ORDER BY id DESC LIMIT 30"))
    conn.close()
    return reply(data, "db")


app.include_router(api)

# ---------- PRESENTATION TIER: serve the frontend files ----------
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
