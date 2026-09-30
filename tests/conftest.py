"""Keep all tests independent of student credentials and saved orders."""
import tempfile
from pathlib import Path

import config

_runtime = tempfile.TemporaryDirectory(prefix="voltcart-tests-")
config.DB_FILE = Path(_runtime.name) / "voltcart.db"
config.ORDERS_FILE = config.DB_FILE
config.LANGSMITH_ENABLED = False
config.OPENAI_API_KEY = "PASTE_TEST_KEY"


def pytest_sessionfinish(session, exitstatus):
    _runtime.cleanup()
