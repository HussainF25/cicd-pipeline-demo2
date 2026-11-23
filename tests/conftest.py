import sys
from pathlib import Path

# Make app.py importable from the tests folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
