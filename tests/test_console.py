import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rta_brain.console import is_local_origin, publish_readiness, read_memories, resolve_static_asset, scan_brain_databases
from rta_brain.db import connect, init_project, remember


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "rta-brain.py"


class RtaBrainConsoleTests(unittest.TestCase):
    def test_scan_brain_databases_reports_ready_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "brains"
            db = brain_dir / "demo.sqlite"
            conn = connect(db)
            try:
                init_project(conn, "demo", str(Path(tmp) / "repo"))
                remember(conn, "Use the local dashboard before GitHub publish.", project="demo", memory_type="procedure", pramana="sabda")
            finally:
                conn.close()

            projects = scan_brain_databases(brain_dir)
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["project"], "demo")
            self.assertTrue(projects[0]["ready"])
            self.assertEqual(projects[0]["memories"], 1)
            self.assertEqual(projects[0]["db_file"], "demo.sqlite")

    def test_read_memories_filters_by_pramana_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            conn = connect(db)
            try:
                init_project(conn, "demo", tmp)
                remember(conn, "Generated prose lives in language.mjs.", project="demo", memory_type="procedure", pramana="sabda")
                remember(conn, "Try a visual mockup for dashboards.", project="demo", memory_type="idea", pramana="kalpana")
            finally:
                conn.close()

            payload = read_memories(db, "demo", query="prose", pramana="sabda")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(len(payload["memories"]), 1)
            self.assertIn("language.mjs", payload["memories"][0]["text"])

    def test_publish_readiness_and_dashboard_help(self):
        readiness = publish_readiness(ROOT)
        names = {item["name"]: item["ok"] for item in readiness["checks"]}
        self.assertIn("README.md", names)
        self.assertIn("LICENSE", names)
        self.assertIn("python -m unittest discover -s tests -v", readiness["commands"])

        result = subprocess.run(
            [sys.executable, str(CLI), "dashboard", "--help"],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Run the local operator console", result.stdout)

        readiness_result = subprocess.run(
            [sys.executable, str(CLI), "publish-readiness", "--json"],
            text=True,
            capture_output=True,
            cwd=ROOT,
        )
        self.assertEqual(readiness_result.returncode, 0, readiness_result.stderr)
        self.assertIn("GITHUB_PUBLISH_CHECKLIST.md", readiness_result.stdout)

    def test_static_assets_are_packaged_in_source_tree(self):
        static_dir = ROOT / "rta_brain" / "static"
        assets_dir = static_dir / "assets"
        self.assertTrue((static_dir / "index.html").exists())
        self.assertTrue(any(assets_dir.glob("*.js")))
        self.assertTrue(any(assets_dir.glob("*.css")))
        package_config = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("static/*", package_config)
        self.assertIn("static/assets/*", package_config)

    def test_static_asset_resolution_stays_inside_static_dir(self):
        static_dir = ROOT / "rta_brain" / "static"
        self.assertEqual(resolve_static_asset(static_dir, "/"), static_dir.resolve() / "index.html")
        self.assertIsNone(resolve_static_asset(static_dir, "/../README.md"))
        self.assertIsNone(resolve_static_asset(static_dir, "/assets/../../README.md"))

    def test_local_origin_check_rejects_non_local_origins(self):
        class Headers:
            def __init__(self, values):
                self.values = values

            def get(self, key):
                return self.values.get(key)

        class Handler:
            def __init__(self, values):
                self.headers = Headers(values)

        self.assertTrue(is_local_origin(Handler({})))
        self.assertTrue(is_local_origin(Handler({"Origin": "http://127.0.0.1:8765"})))
        self.assertTrue(is_local_origin(Handler({"Origin": "http://localhost:8765"})))
        self.assertFalse(is_local_origin(Handler({"Origin": "https://example.com"})))


if __name__ == "__main__":
    unittest.main()
