#!/usr/bin/env python3
"""
AETHERGUARD CLI Entrypoint.
Enables running commands directly from repository root via:
    python3 cli.py <command>
"""

import sys
from pathlib import Path

# Ensure src directory is in python path
src_dir = Path(__file__).resolve().parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from ai_security_monitor.presentation.cli.main import main

if __name__ == "__main__":
    main()
