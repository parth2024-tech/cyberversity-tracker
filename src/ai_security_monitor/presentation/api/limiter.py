"""
Rate limiter configuration for API endpoints protection.
"""

from __future__ import annotations

import os
import sys

from slowapi import Limiter
from slowapi.util import get_remote_address

_is_testing = "pytest" in sys.modules or os.getenv("TESTING", "").lower() in (
    "1",
    "true",
    "yes",
)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    enabled=not _is_testing,
)
