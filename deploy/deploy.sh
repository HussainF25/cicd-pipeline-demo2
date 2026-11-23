#!/bin/bash
# Runs ON THE EC2 SERVER (as root, via AWS Systems Manager Run Command).
# Deploys the Student Management System (FastAPI + SQLite + frontend).
# Usage: bash deploy/deploy.sh   (from inside the unzipped build package)
#
# Installs the build into /opt/cicd-app/releases/<version>, points
# /opt/cicd-app/current at it, restarts the service, health-checks it,
# and rolls back to the previous release if the health check fails.
set -euo pipefail
export HOME="${HOME:-/root}" # SSM runs without a login shell

APP_ROOT=/opt/cicd-app
RELEASES="$APP_ROOT/releases"
VENV="$APP_ROOT/venv"
SERVICE=cicd-app
APP_USER=cicdapp
PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { echo "[deploy] $(date -u +%H:%M:%S) $*"; }

# --- 1. One-time server setup (skipped on later deploys) -------------------
find_python() {
  for py in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$py" >/dev/null 2>&1; then echo "$py"; return 0; fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  log "Installing Python 3.12 (first deploy only)..."
  dnf install -y -q python3.12 python3.12-pip >/dev/null || dnf install -y -q python3.11 python3.11-pip >/dev/null
  PYTHON="$(find_python)"
fi
log "Using $($PYTHON --version)"

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /sbin/nologin "$APP_USER"
mkdir -p "$RELEASES" "$APP_ROOT/data"
chown "$APP_USER" "$APP_ROOT/data"   # the SQLite database lives here, outside releases, so data survives deploys
[ -x "$VENV/bin/python" ] || "$PYTHON" -m venv "$VENV"

# Login-token signing key: generated once on the server, never stored in Git
SECRET_FILE="$APP_ROOT/secret.env"
if [ ! -f "$SECRET_FILE" ]; then
  log "Generating SMS_SECRET (first deploy only)"
  (umask 077; echo "SMS_SECRET=$("$PYTHON" -c 'import secrets; print(secrets.token_hex(32))')" > "$SECRET_FILE")
fi

# --- 2. Install this release ------------------------------------------------
VERSION="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PKG_DIR/build_info.json")"
TARGET="$RELEASES/$VERSION"
log "Installing release v$VERSION into $TARGET"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$PKG_DIR"/. "$TARGET"/
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$TARGET/requirements.txt"

PREVIOUS="$(readlink -f "$APP_ROOT/current" 2>/dev/null || true)"
ln -sfn "$TARGET" "$APP_ROOT/current"

# --- 3. systemd service (idempotent) ----------------------------------------
cat > /etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=Student Management System (deployed by GitHub Actions)
After=network.target

[Service]
User=$APP_USER
Environment=APP_ENV=production
Environment=SMS_DB_PATH=$APP_ROOT/data/sms.db
Environment=PYTHONDONTWRITEBYTECODE=1
EnvironmentFile=$SECRET_FILE
WorkingDirectory=$APP_ROOT/current
# One worker on purpose: the cache and the notification queue live in memory
ExecStart=$VENV/bin/uvicorn backend.main:app --host 0.0.0.0 --port 80 --workers 1 --app-dir $APP_ROOT/current
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=always
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --quiet "$SERVICE"
log "Restarting service"
systemctl restart "$SERVICE"

# --- 4. Health check + automatic rollback ----------------------------------
for _ in $(seq 1 15); do
  if curl -fsS http://127.0.0.1/health 2>/dev/null \
      | "$PYTHON" -c 'import json,sys; sys.exit(json.load(sys.stdin).get("version") != sys.argv[1])' "$VERSION"; then
    log "Health check passed: v$VERSION is live"
    # Keep only the 5 newest releases
    ls -1dt "$RELEASES"/* | tail -n +6 | xargs -r rm -rf
    exit 0
  fi
  sleep 2
done

log "Health check FAILED for v$VERSION"
journalctl -u "$SERVICE" -n 30 --no-pager || true
if [ -n "$PREVIOUS" ] && [ -d "$PREVIOUS" ] && [ "$PREVIOUS" != "$TARGET" ]; then
  log "Rolling back to $PREVIOUS"
  ln -sfn "$PREVIOUS" "$APP_ROOT/current"
  systemctl restart "$SERVICE"
fi
exit 1
