"""CI/CD demo web application.

Change APP_VERSION or BANNER_MESSAGE below, commit, and push:
GitHub Actions will test, build, upload to S3 and deploy it to EC2 automatically.
"""

import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template

# ---------------------------------------------------------------------------
# ✏️  EDIT THESE TWO LINES FOR YOUR DEMO "CODE CHANGE"
# ---------------------------------------------------------------------------
APP_VERSION = "1.0"
BANNER_MESSAGE = "Hello from my automated CI/CD pipeline!"
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
BUILD_INFO_FILE = BASE_DIR / "build_info.json"

app = Flask(__name__)


def load_build_info(path=BUILD_INFO_FILE):
    """Return metadata written by the CI build step, or local defaults."""
    defaults = {
        "version": APP_VERSION,
        "build_number": "local",
        "commit": "local",
        "built_at": "not built by CI",
    }
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return defaults
    if not isinstance(data, dict):
        return defaults
    return {**defaults, **{k: str(v) for k, v in data.items()}}


@app.route("/")
def index():
    info = load_build_info()
    return render_template(
        "index.html",
        message=BANNER_MESSAGE,
        info=info,
        environment=os.environ.get("APP_ENV", "development"),
    )


@app.route("/health")
def health():
    info = load_build_info()
    return jsonify(status="ok", version=info["version"], commit=info["commit"])


if __name__ == "__main__":
    # Local development only; production runs under gunicorn.
    app.run(host="127.0.0.1", port=5000)
