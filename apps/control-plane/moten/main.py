"""ASGI entrypoint. Builds the app and seeds the dev store if empty.

Run: uvicorn moten.main:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

from .app import create_app
from .seed import seed

app = create_app()

with app.state.session_scope() as _s:
    seed(_s)
