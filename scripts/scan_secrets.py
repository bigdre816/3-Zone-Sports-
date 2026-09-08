#!/usr/bin/env python3
"""Fail a local/CI scan when XRPL signing material is committed."""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IGNORE = {".git", "__pycache__", ".venv", "data"}
PATTERNS = [
    re.compile(r"MOTEN_XRPL_SECRET\s*=\s*(?!\s*$|<[^>]+>|\"\"|''|REPLACE)", re.I),
    re.compile(r"\bs[1-9A-HJ-NP-Za-km-z]{28,}\b"),  # common XRPL family seed prefix
    re.compile(r"(?:private[_ -]?key|passphrase)\s*[:=]\s*['\"][^'\"]{12,}", re.I),
]

def main() -> int:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in IGNORE for part in path.parts):
            continue
        if path.name == ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in PATTERNS):
                hits.append(f"{path.relative_to(ROOT)}:{line_number}")
    if hits:
        print("potential signing material found (contents intentionally redacted):")
        print("\n".join(hits))
        return 1
    print("secret scan passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
