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
        self.assertIn("mountPath: /data", text)
        self.assertIn("TZ_ENV", text)
        self.assertIn("demo", text)
        self.assertIn("healthCheckPath: /healthz", text)
        self.assertNotIn("healthCheckPath: /api/health", text)
        self.assertIn("TZ_PUBLIC_APP_URL", text)
        self.assertIn("https://threezonesport.lovable.app", text)
        self.assertNotRegex(
            text,
            r"key: TZ_PUBLIC_APP_URL\s*\n(?:[^\n]*\n)*?\s*value: https://\S*lovable",
        )

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
            "main/index.html",
            "vercel.json",
        ):
            path = ROOT / rel
            self.assertTrue(path.exists(), f"missing {path}")

    def test_vercel_main_root_is_public_site_not_moten_spec(self):
        """Vercel project Root/Output Directory is `main`. That folder must exist
        and must not ship unfiled Moten spec PDFs."""
        index = (ROOT / "main" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Three-Zone Sports", index)
        self.assertNotIn("Moten_IP_Invention_Control_Plane", index)
        self.assertFalse((ROOT / "main" / "Moten_IP_Invention_Control_Plane_Master_Specification_v1_0.pdf").exists())
        cfg = (ROOT / "vercel.json").read_text(encoding="utf-8")
        self.assertIn('"outputDirectory": "main"', cfg)
        self.assertTrue((ROOT / "main" / "package.json").is_file())

    def test_member_dockerfile_copies_from_its_own_directory(self):
        dockerfile = (MVP / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt", dockerfile)
        self.assertNotIn("COPY three-zone-mvp/", dockerfile)
        entry = (MVP / "docker-entrypoint.sh").read_text(encoding="utf-8")
        self.assertIn('PORT="${PORT:-${TZ_HTTP_PORT:-8000}}"', entry)
        self.assertIn("--http-port \"$PORT\"", entry)


if __name__ == "__main__":
    os.chdir(str(MVP))
    unittest.main()
