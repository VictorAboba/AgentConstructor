"""Tests run against a throwaway data directory and the offline mock model; no keys or Docker needed."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Must be set before `app.db` is imported: the database path is fixed at import time.
os.environ["AGENTCONSTRUCTOR_DATA"] = tempfile.mkdtemp(prefix="agentconstructor-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import db  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(scope="session")
def mock_model_id() -> str:
    seed()
    return db.one("SELECT id FROM models WHERE provider = 'mock'")["id"]
