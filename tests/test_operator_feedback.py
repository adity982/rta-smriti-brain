import subprocess
import tempfile
import unittest
from pathlib import Path

from rta_brain import db
from rta_brain.context import build_context_pack, build_continuation_prompt
from rta_brain.console import scan_brain_databases
from rta_brain.ingest import walk_repo
from rta_brain.project import bootstrap_project
from rta_brain.repository import repository_state


ROOT = Path(__file__).resolve().parents[1]


class RtaBrainOperatorFeedbackTests(unittest.TestCase):
    def test_project_root_is_bound_and_cannot_silently_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "canonical"
            second = Path(tmp) / "wrong-copy"
            first.mkdir()
            second.mkdir()
            (first / "main.py").write_text("VALUE = 'canonical'\n", encoding="utf-8")
            (second / "main.py").write_text("VALUE = 'wrong'\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.ingest_repo(conn, first, project="demo")
                with self.assertRaisesRegex(ValueError, "canonical root mismatch"):
                    db.ingest_repo(conn, second, project="demo")
                stored = conn.execute("SELECT root_path FROM projects WHERE name = 'demo'").fetchone()["root_path"]
                self.assertEqual(Path(stored), first.resolve())
            finally:
                conn.close()

    def test_deep_freshness_omits_fresh_file_details_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "one.py").write_text("ONE = 1\n", encoding="utf-8")
            (root / "two.py").write_text("TWO = 2\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.ingest_repo(conn, root, project="demo")
                fresh = db.stale_check(conn, project="demo", deep=True)
                self.assertEqual(fresh["fresh"], 2)
                self.assertEqual(fresh["details"], [])
                self.assertEqual(fresh["fresh_details_omitted"], 2)

                (root / "two.py").write_text("TWO = 3\n", encoding="utf-8")
                changed = db.stale_check(conn, project="demo", deep=True)
                self.assertEqual([item["title"] for item in changed["details"]], ["two.py"])
                self.assertEqual(changed["details"][0]["status"], "changed")
            finally:
                conn.close()

    def test_structured_checkpoint_leads_context_and_continuation_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "service.py").write_text("READY = True\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.ingest_repo(conn, root, project="demo")
                checkpoint = db.save_checkpoint(
                    conn,
                    project="demo",
                    objective="Ship canonical-root protection",
                    verified_evidence="Wrong-root regression reproduced",
                    remaining_gaps="Dashboard warning",
                    next_action="Implement the operator banner",
                    prohibited_repetition="Do not rescan unrelated folders",
                )
                self.assertEqual(checkpoint["checkpoint"]["next_action"], "Implement the operator banner")
                latest = db.latest_checkpoint(conn, "demo")
                self.assertEqual(latest["objective"], "Ship canonical-root protection")

                pack = build_context_pack(conn, "continue", project="demo")
                prompt = build_continuation_prompt(conn, project="demo")
                self.assertIn("## Active Checkpoint", pack)
                self.assertIn("Remaining gaps: Dashboard warning", pack)
                self.assertIn("Do not repeat: Do not rescan unrelated folders", prompt)
                self.assertIn("Next action: Implement the operator banner", prompt)
            finally:
                conn.close()

    def test_memory_claim_retains_structured_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                remembered = db.remember(
                    conn,
                    "Checkout verification fails closed.",
                    project="demo",
                    pramana="pratyaksha",
                    provenance={
                        "source_path": "tests/test_checkout.py",
                        "source_hash": "abc123",
                        "command": "python -m unittest tests.test_checkout",
                        "verification_status": "verified",
                    },
                )
                self.assertEqual(remembered["memory"]["provenance"]["verification_status"], "verified")
                found = db.search(conn, "checkout verification", project="demo")
                self.assertEqual(found["memories"][0]["provenance"]["source_path"], "tests/test_checkout.py")
                self.assertTrue(found["memories"][0]["provenance"]["timestamp"])
            finally:
                conn.close()

    def test_default_exclusions_skip_worktrees_browsers_and_test_scratch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "src").mkdir()
            (root / "src" / "keep.py").write_text("KEEP = True\n", encoding="utf-8")
            for directory in (".worktrees", "ms-playwright", "test-scratch", ".ruff_cache", "playwright-report"):
                target = root / directory
                target.mkdir()
                (target / "noise.py").write_text("NOISE = True\n", encoding="utf-8")
            indexed = [path.relative_to(root).as_posix() for path in walk_repo(root)]
            self.assertEqual(indexed, ["src/keep.py"])

    def test_repository_state_reports_git_identity_and_dirty_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            clean = repository_state(root)
            self.assertTrue(clean["is_git_repo"])
            self.assertEqual(clean["dirty_files"], 0)
            self.assertTrue(clean["branch"])
            self.assertTrue(clean["head"])

            (root / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
            dirty = repository_state(root)
            self.assertEqual(dirty["dirty_files"], 1)

    def test_dashboard_marks_duplicate_project_names_bound_to_different_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "brains"
            brain_dir.mkdir()
            for index in (1, 2):
                root = Path(tmp) / f"repo-{index}"
                root.mkdir()
                (root / "main.py").write_text(f"VALUE = {index}\n", encoding="utf-8")
                conn = db.connect(brain_dir / f"demo-{index}.sqlite")
                try:
                    db.ingest_repo(conn, root, project="demo")
                finally:
                    conn.close()
            projects = scan_brain_databases(brain_dir)
            self.assertEqual(len(projects), 2)
            self.assertTrue(all(project["root_conflict"] for project in projects))
            self.assertTrue(all(len(project["root_conflict_roots"]) == 2 for project in projects))

    def test_bootstrap_can_enable_dependency_free_hybrid_retrieval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "queue.md").write_text("Queue latency and backpressure.\n", encoding="utf-8")
            brain_dir = Path(tmp) / "brains"
            control = db.connect(Path(tmp) / "control.sqlite")
            try:
                payload = bootstrap_project(
                    control,
                    root,
                    "demo",
                    brain_dir,
                    False,
                    ROOT,
                    embedding_provider="hash",
                )
            finally:
                control.close()
            conn = db.connect(Path(payload["db_path"]))
            try:
                self.assertEqual(db.get_project_settings(conn, "demo")["embedding_provider"], "hash")
                found = db.search(conn, "queue latency", project="demo")
                self.assertEqual(found["retrieval"]["mode"], "hybrid")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
