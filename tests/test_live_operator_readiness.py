import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rta_brain.repository as repository
from rta_brain.console import (
    ConsoleConfig,
    checkpoint_status_snapshot,
    dashboard_bootstrap_snapshot,
    scan_brain_registry,
)
from rta_brain.continuity_daemon import continuity_paths, continuity_status
from rta_brain.db import connect, init_project, remember


ROOT = Path(__file__).resolve().parents[1]


class LiveOperatorReadinessTests(unittest.TestCase):
    def test_dashboard_bootstrap_uses_lightweight_registry_without_repository_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "brains"
            database = brain_dir / "demo.sqlite"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            conn = connect(database)
            try:
                init_project(conn, "demo", str(repo))
                remember(conn, "Fast bootstrap must not wait for Git inspection.", project="demo")
            finally:
                conn.close()

            with patch.object(repository, "run_git_inspection", side_effect=AssertionError("deep inspection invoked")):
                snapshot = dashboard_bootstrap_snapshot(ConsoleConfig(tool_root=ROOT, brain_dir=brain_dir))

            self.assertEqual(snapshot["projects"][0]["project"], "demo")
            self.assertEqual(snapshot["projects"][0]["scan_state"], "checking")
            self.assertIsNone(snapshot["projects"][0]["ready"])
            self.assertIsNone(snapshot["publish"])

    def test_scan_brain_registry_reports_counts_without_claiming_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "brains"
            database = brain_dir / "demo.sqlite"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            conn = connect(database)
            try:
                init_project(conn, "demo", str(repo))
                remember(conn, "Registry discovery is not a readiness verdict.", project="demo")
            finally:
                conn.close()

            projects = scan_brain_registry(brain_dir)

            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["sources"], 0)
            self.assertEqual(projects[0]["memories"], 1)
            self.assertEqual(projects[0]["scan_state"], "checking")
            self.assertIsNone(projects[0]["ready"])

    def test_checkpoint_summary_does_not_run_repository_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "brain.sqlite"
            repo = Path(tmp) / "repo"
            repo.mkdir()
            conn = connect(database)
            try:
                init_project(conn, "demo", str(repo))
                with patch("rta_brain.continuity.integrity_diagnostics", side_effect=AssertionError("deep integrity invoked")):
                    payload = checkpoint_status_snapshot(conn, database, "demo")
            finally:
                conn.close()

        self.assertIsNone(payload["continuation_ready"])
        self.assertIsNone(payload["database_healthy"])
        self.assertEqual(payload["operational_state"], "integrity_not_checked")
        self.assertIn("project_integrity_not_checked", payload["reasons"])

    def test_status_binding_diagnostics_are_explicit_not_polled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            database = base / "brain.sqlite"
            project = base / "project"
            sessions = base / "sessions"
            database.touch()
            project.mkdir()
            sessions.mkdir()
            paths = continuity_paths(database, "demo")
            paths["directory"].mkdir()
            paths["state"].write_text(json.dumps({
                "project": "demo",
                "state": "stopped",
                "root": str(project),
                "sessions_root": str(sessions),
                "lookback_days": 30,
            }), encoding="utf-8")

            with patch("rta_brain.continuity_daemon.continuity_binding_diagnostics") as diagnostics:
                status = continuity_status(database, "demo")
                diagnostics.assert_not_called()
                diagnostics.return_value = {"status": "ok", "recent_sessions": 0}
                deep_status = continuity_status(database, "demo", include_binding_diagnostics=True)
                diagnostics.assert_called_once()

        self.assertNotIn("binding_diagnostics", status)
        self.assertIn("binding_diagnostics", deep_status)


if __name__ == "__main__":
    unittest.main()
