"""Vercel entrypoint. The FastAPI app lives in the package; this file only exposes it.

The function serves the built day_1 files and runs the Live tab with hosted embeddings and a
trimmed model cache. Defaults below apply only when the environment does not already set
them; the secrets (OPENROUTER_API_KEY, TYPESAFE_API_KEY) and the model IDs (JEV_MODEL,
ANALYSIS_MODEL, NOTES_MODEL) are set in the Vercel project, never here.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

os.environ.setdefault("TRIAGE_DATA_DIR", "data/out/day_1")
os.environ.setdefault("TRIAGE_CACHE_DIR", "data/cache_web")   # the entries the presets and day_1 need (read-only here)
# The hosted embedding model and the bundled cache go together, so these two are set, not defaulted:
# a leftover local model ID in the project settings would otherwise be sent to OpenRouter.
os.environ["EMBEDDING_BACKEND"] = "openrouter"                  # no room for a local embedding model
os.environ["EMBEDDING_MODEL"] = "baai/bge-base-en-v1.5"

from triage_app.web.main import app

__all__ = ["app"]
