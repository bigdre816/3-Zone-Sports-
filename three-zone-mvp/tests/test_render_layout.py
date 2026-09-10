"""Render Docker context paths used by 3-Zone-Sports-.

Render joins Root Directory with dockerfilePath / dockerContext. A leftover
rootDir of three-zone-mvp plus a context of three-zone-mvp makes it lstat
three-zone-mvp/three-zone-mvp and fail the build before Docker starts.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MVP = Path(__file__).resolve().parents[1]
NESTED = MVP / "three-zone-mvp"
RENDER_YAML = ROOT / "render.yaml"

REQUIRED = (
    "Dockerfile",
    "docker-entrypoint.sh",
    "requirements.txt",
    "run.py",
    "THREE_ZONE_MASTERY.md",
    "backend",
    "scripts",
)


class RenderLayoutTests(unittest.TestCase):
    def test_blueprint_paths_are_relative_to_root_dir(self):
        text = RENDER_YAML.read_text(encoding="utf-8")
        self.assertIn("rootDir: three-zone-mvp", text)
        self.assertIn("dockerfilePath: ./Dockerfile", text)
        self.assertIn("dockerContext: .", text)
        self.assertNotIn("dockerfilePath: three-zone-mvp/", text)
        self.assertNotIn("dockerContext: three-zone-mvp", text)

    def test_nested_context_has_the_files_docker_copies(self):
        self.assertTrue(NESTED.is_dir(), f"missing {NESTED}")
        for name in REQUIRED:
            path = NESTED / name
            self.assertTrue(path.exists(), f"missing {path}")
            if name != "backend" and name != "scripts":
                self.assertTrue(path.is_file() or path.is_symlink(), path)
                self.assertGreater(path.stat().st_size, 0, path)
            else:
                self.assertTrue(path.is_dir() or path.is_symlink(), path)
                self.assertTrue(any(path.iterdir()), path)

    def test_nested_dockerfile_copies_from_its_own_directory(self):
        dockerfile = (NESTED / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt", dockerfile)
        self.assertNotIn("COPY three-zone-mvp/", dockerfile)
        self.assertIn("https://three-zone-sports.onrender.com", dockerfile)


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
