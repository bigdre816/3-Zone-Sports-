#!/usr/bin/env python3
"""CLI wrapper for backend.live_readiness."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.live_readiness import main

if __name__ == "__main__":
    raise SystemExit(main())
