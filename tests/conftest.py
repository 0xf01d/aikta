import os
import sys
from pathlib import Path

# Run the tests against the in-repo sources without requiring an install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# aikta/__init__.py imports the app, whose settings module requires these at
# import time; the tests never touch IRC, so default them to throwaways.
os.environ.setdefault("AIKTA_LASTFM_API_KEY", "test-key")
os.environ.setdefault("AIKTA_CHANNELS", "#test")
