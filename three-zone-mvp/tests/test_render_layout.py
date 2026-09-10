"""Keep the member app at three-zone-mvp/ and Render paths relative to it."""

from __future__ import annotations

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MVP = Path(__file__).resolve().parents[1]
RENDER_YAML = ROOT / "render.yaml"

REQUIRED = (
    "Dockerfile",
    "docker-entrypoint.sh",
    "requirements.txt",
    "run.py",
    "THREE_ZONE_MASTERY.md",
    "backend",
    "scripts",
    "tests",
    "README.md",
    "CONNECT-3ZONESPORTS.md",
)


class WorkspaceLayoutTests(unittest.TestCase):
    def test_blueprint_paths_are_relative_to_root_dir(self):
        text = RENDER_YAML.read_text(encoding="utf-8")
        self.assertIn("rootDir: three-zone-mvp", text)
        self.assertIn("dockerfilePath: ./Dockerfile", text)
        self.assertIn("dockerContext: .", text)
        self.assertNotIn("dockerfilePath: three-zone-mvp/", text)
        self.assertNotIn("dockerContext: three-zone-mvp", text)

    def test_member_app_is_not_nested_under_itself(self):
        self.assertFalse(
            (MVP / "three-zone-mvp").exists(),
            "three-zone-mvp/three-zone-mvp hides the real app",
        )
        for name in REQUIRED:
            path = MVP / name
            self.assertTrue(path.exists(), f"missing {path}")

    def test_built_surfaces_are_at_repo_root(self):
        for rel in (
            "System",
            "index.html",
            "docs/index.html",
            "apps/control-plane/manage.py",
            "moten_audit/server.py",
            "three-zone-mvp/run.py",
            "three-zone-mvp/backend/http_server.py",
        ):
            path = ROOT / rel
            self.assertTrue(path.exists(), f"missing {path}")

    def test_member_dockerfile_copies_from_its_own_directory(self):
        dockerfile = (MVP / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt", dockerfile)
        self.assertNotIn("COPY three-zone-mvp/", dockerfile)


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
