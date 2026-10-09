"""Vercel entrypoint. The FastAPI app lives in the package; this file only exposes it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from triage_app.web.main import app

__all__ = ["app"]
