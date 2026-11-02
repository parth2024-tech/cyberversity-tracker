"""
Root pytest configuration.
Guarantees that test environment variables are set before ANY application module is imported.
"""

from __future__ import annotations

import os
from pathlib import Path

# Guarantee test environment isolation in /tmp before any app or test module imports
_TEST_DATA_DIR = Path("/tmp/aetherguard_test_data")
_TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

os.environ["DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["DATABASE__URL"] = f"sqlite+aiosqlite:///{_TEST_DATA_DIR}/monitor.db"
os.environ["DB_URL"] = f"sqlite+aiosqlite:///{_TEST_DATA_DIR}/monitor.db"
