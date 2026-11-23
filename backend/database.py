"""DATA TIER - SQLite database (stands in for PostgreSQL / Amazon RDS)."""
import os
import sqlite3
from pathlib import Path

from .auth import hash_password

# On the server the database lives outside the release folder (SMS_DB_PATH), so data survives deployments.
DB_PATH = Path(os.environ.get("SMS_DB_PATH", Path(__file__).resolve().parent.parent / "data" / "sms.db"))


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def init_db():
    conn = get_conn()
    had_enrolments = _has_table(conn, "enrolments")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            program TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS enrolments (
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            PRIMARY KEY (student_id, course_id)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            present INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            marks REAL NOT NULL,
            grade TEXT NOT NULL,
            published INTEGER NOT NULL DEFAULT 0,
            UNIQUE(student_id, course_id)
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # upgrade databases created by the earlier version of the app
    columns = [r["name"] for r in conn.execute("PRAGMA table_info(students)")]
    if "roll_no" not in columns:
        conn.execute("ALTER TABLE students ADD COLUMN roll_no TEXT")
    conn.execute("UPDATE students SET roll_no = printf('NU-%04d', id) WHERE roll_no IS NULL")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_roll_no ON students(roll_no)")

    if conn.execute("SELECT COUNT(*) FROM courses").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO courses (code, title) VALUES (?, ?)",
            [("DS501", "Machine Learning"), ("DS502", "DevOps for Data Science"), ("DS503", "Data Visualisation")],
        )
    if not had_enrolments:  # older data: enrol existing students in every course
        conn.execute("INSERT OR IGNORE INTO enrolments SELECT s.id, c.id FROM students s, courses c")
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (email, name, role, password_hash) VALUES (?, ?, ?, ?)",
            ("admin@northfield.edu", "Admin Office", "Registrar", hash_password("admin123")),
        )
    conn.commit()
    conn.close()
