"""RELEASE INFO - shown in the app and checked by the CI/CD pipeline.

✏️  For the CI/CD demo, change these two lines, commit and push.
GitHub Actions tests, builds, uploads to S3 and deploys to EC2 automatically,
and the new version and release note appear on the live site.
"""
import json
from pathlib import Path

APP_VERSION = "1.1"
RELEASE_NOTE = "New: results are published through the queue"

BUILD_INFO_FILE = Path(__file__).resolve().parent.parent / "build_info.json"


def build_info(path=BUILD_INFO_FILE):
    """Version details written by the CI build step, or local defaults when run on a laptop."""
    info = {"version": APP_VERSION, "build_number": "local", "commit": "local", "built_at": "not built by CI"}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            info.update({k: str(v) for k, v in data.items()})
    except (OSError, ValueError):
        pass
    info["release_note"] = RELEASE_NOTE
    return info
