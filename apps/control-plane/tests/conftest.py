from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from moten.app import create_app
from moten.database import make_engine
from moten.seed import seed


@pytest.fixture()
def app(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'test.db'}")
    return create_app(engine=engine)


@pytest.fixture()
def seeded_app(app):
    with app.state.session_scope() as s:
        seed(s)
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def seeded_client(seeded_app):
    return TestClient(seeded_app)
