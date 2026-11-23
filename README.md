# Student Management System, with a CI/CD pipeline on GitHub Actions & AWS

**Assignment 1 (Software Architecture Design)** designed a Student Management System: a 3-tier core with an event-driven notification path.
**Assignment 2 (CI/CD)** ships that same application automatically:

**Code change → git push → security scan + unit tests → build → artifact in S3 → deploy to EC2 → verified live**

Live production: `http://<EC2 public IP>` · demo login `admin@northfield.edu` / `admin123`

## 1. The application (from the architecture design)

| Architecture component | In this app | File |
| --- | --- | --- |
| Presentation tier | HTML + JavaScript, 3 screens (Students, Attendance, Results) | `frontend/` |
| Application tier: REST API | FastAPI, JSON, JWT login | `backend/main.py`, `backend/auth.py` |
| Cache (Redis in production) | In-memory cache with expiry; cleared when data changes | `backend/cache.py` |
| Data tier (PostgreSQL / RDS in production) | SQLite | `backend/database.py` |
| Queue (SQS) + notifier (Lambda) | In-process queue + background worker | `backend/events.py` |
| Release info | Version, release note, build number, commit | `backend/version.py` → `/health` |

## 2. The CI/CD pipeline (`.github/workflows/cicd.yml`)

```mermaid
flowchart LR
    Dev[Developer<br/>git push] --> GA{{GitHub Actions}}
    GA --> SEC[🔒 Security scan<br/>Bandit · pip-audit · Gitleaks]
    GA --> TEST[🧪 Unit tests<br/>19 pytest tests]
    SEC --> BUILD[📦 Build<br/>build-vX.Y.N.zip]
    TEST --> BUILD
    BUILD -->|upload| S3[(S3 bucket<br/>builds/latest.zip)]
    BUILD --> DEPLOY[🚀 Deploy<br/>SSM Run Command]
    DEPLOY --> EC2[EC2 · Amazon Linux 2023<br/>uvicorn + FastAPI on :80]
    S3 -. server pulls latest.zip .-> EC2
    EC2 --> VERIFY[✅ Verify production<br/>/health shows new version]
```

| Job | What it does | Stops the pipeline if… |
| --- | --- | --- |
| 🔒 Security Scan | **Bandit** (static code analysis), **pip-audit** (known CVEs in dependencies), **Gitleaks** (secrets in git history) | a medium+ code issue, vulnerable package or leaked secret is found |
| 🧪 Unit Tests | 19 tests: login/JWT, students, roll numbers, caching + invalidation, low-attendance warnings, async result emails, grades | any test fails |
| 📦 Build & Upload to S3 | Writes `build_info.json`, zips the app as `build-v<APP_VERSION>.<run#>.zip`, uploads it to S3 and as `latest.zip` | upload fails |
| 🚀 Deploy | AWS Systems Manager tells the EC2 server to download `latest.zip` from S3 and run `deploy/deploy.sh` | install or health check fails (automatic rollback to the previous release) |
| ✅ Verify Production | Calls `http://<server>/health` and checks it reports the version just built | production isn't serving the new version |

Also on every push: **CodeQL** (`codeql.yml`) and **Dependabot** (`dependabot.yml`).

### What the security scan caught

On the first scan of the original app, the pipeline found and blocked:
- **Bandit B608**: an SQL statement built with an f-string in `delete_student`. Replaced with fixed SQL strings.
- **pip-audit**: 6 known vulnerabilities in `starlette 0.38.6` (pulled in by FastAPI 0.115). Upgraded FastAPI and uvicorn.

### How the server is set up (`deploy/deploy.sh`)

- Releases go to `/opt/cicd-app/releases/<version>`, and `/opt/cicd-app/current` points to the live one (the last 5 are kept for rollback).
- The SQLite database lives in `/opt/cicd-app/data/`, **outside** the releases, so student data survives every deployment.
- The JWT signing key is generated once on the server (`secret.env`, root-only). It's never stored in Git.
- The app runs as an unprivileged `cicdapp` user under systemd, with a single worker, because the cache and queue live in memory.

## 3. AWS resources

| Resource | Purpose |
| --- | --- |
| S3 bucket (private, versioned) | Stores every build artifact |
| EC2 t3.micro, Amazon Linux 2023 | Production server |
| IAM role `EC2-CICD-Role` | Lets the server read S3 and receive SSM commands |
| IAM user `github-actions-deployer` | Least-privilege keys used only by the pipeline |

GitHub **secrets**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` · **variables**: `AWS_REGION`, `S3_BUCKET`, `EC2_INSTANCE_ID`

## 4. Make a change (the demo)

1. Edit `APP_VERSION` and `RELEASE_NOTE` in `backend/version.py`.
2. `git commit -am "Release v1.1" && git push`
3. Watch the **Actions** tab. When it's green, refresh the live site and the login card shows the new version and note.

## 5. Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v                          # 19 tests
uvicorn backend.main:app --reload  # http://127.0.0.1:8000 (API docs at /docs)
```
