import asyncio
import concurrent.futures
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain import db, project, repository
from rta_brain.console import read_file_preview
from rta_brain.context import build_context_pack, estimate_tokens
from rta_brain.mcp_server import RtaBrainMcpServer
from rta_brain.parsers import ParserRegistry


class RtaBrainBlueprintHardeningTests(unittest.TestCase):
    def test_connections_use_wal_normal_sync_and_bounded_busy_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(conn.execute("PRAGMA synchronous").fetchone()[0], 1)
                self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
            finally:
                conn.close()

    def test_repository_identity_survives_a_git_checkout_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "before"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)

            identity = repository.repository_identity(root)
            moved = Path(tmp) / "after"
            shutil.move(str(root), moved)
            self.assertEqual(repository.repository_identity(moved), identity)

    def test_unborn_git_repository_identity_survives_the_first_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unborn"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            identity = repository.repository_identity(root)
            self.assertTrue(identity.startswith("git-local:"))
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            self.assertEqual(repository.repository_identity(root), identity)
            self.assertFalse((root / repository.IDENTITY_DIR).exists())

    def test_project_auto_relocates_only_when_identity_matches_and_old_root_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "before"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.init_project(conn, "demo", str(root))
                identity = conn.execute("SELECT repository_identity FROM projects WHERE name = 'demo'").fetchone()[0]
                moved = Path(tmp) / "after"
                shutil.move(str(root), moved)
                payload = db.init_project(conn, "demo", str(moved))
                self.assertEqual(payload["project"]["repository_identity"], identity)

                other = Path(tmp) / "other"
                other.mkdir()
                (other / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "repository identity mismatch"):
                    db.init_project(conn, "demo", str(other), allow_root_rebind=True)
            finally:
                conn.close()

    def test_routine_git_state_reads_head_without_spawning_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "initial"], check=True)
            with patch("rta_brain.repository._git", side_effect=AssertionError("git subprocess used")):
                state = repository.repository_state(root, include_worktree=False)
            self.assertTrue(state["is_git_repo"])
            self.assertTrue(state["head"])
            self.assertNotEqual(state["branch"], "detached")
            self.assertIsNone(state["dirty_files"])

    def test_checkpoint_optimistic_lock_rejects_a_stale_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                first = db.save_checkpoint(conn, "demo", "Initial")
                self.assertEqual(first["checkpoint"]["version"], 1)
                second = db.save_checkpoint(conn, "demo", "Updated", expected_version=1)
                self.assertEqual(second["checkpoint"]["version"], 2)
                with self.assertRaisesRegex(ValueError, "checkpoint version conflict"):
                    db.save_checkpoint(conn, "demo", "Stale overwrite", expected_version=1)
            finally:
                conn.close()

    def test_memory_batch_is_atomic_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                payload = db.remember_many(
                    conn,
                    [
                        {"text": "Build passed", "pramana": "pratyaksha", "provenance": {"verification_status": "verified"}},
                        {"text": "Use bounded contexts", "pramana": "sabda"},
                    ],
                    project="demo",
                )
                self.assertEqual(payload["stored"], 2)
                found = db.search(conn, "Build passed", project="demo")
                self.assertEqual(found["memories"][0]["provenance"]["verification_status"], "verified")
                with self.assertRaisesRegex(ValueError, "memory text must not be empty"):
                    db.remember_many(conn, [{"text": "rolled back"}, {"text": ""}], project="demo")
                count = conn.execute("SELECT COUNT(*) FROM memories WHERE text = 'rolled back'").fetchone()[0]
                self.assertEqual(count, 0)
            finally:
                conn.close()

    def test_concurrent_checkpoint_writers_cannot_create_the_same_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "brain.sqlite"
            conn = db.connect(db_path)
            try:
                db.save_checkpoint(conn, "demo", "Initial")
            finally:
                conn.close()

            def write(label):
                worker = db.connect(db_path)
                try:
                    return db.save_checkpoint(worker, "demo", label, expected_version=1)
                finally:
                    worker.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(write, label) for label in ("Agent A", "Agent B")]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except ValueError as exc:
                        outcomes.append(str(exc))
            self.assertEqual(sum(isinstance(item, dict) for item in outcomes), 1)
            self.assertEqual(sum("checkpoint version conflict" in item for item in outcomes if isinstance(item, str)), 1)

    def test_context_pack_honors_token_budget_and_prioritizes_direct_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "main.py").write_text("READY = True\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.ingest_repo(conn, root, project="demo")
                db.remember(conn, "DIRECT_EVIDENCE release tests passed", project="demo", pramana="pratyaksha", priority=10)
                for index in range(20):
                    db.remember(conn, f"OLD_MEMORY_{index} " + ("historical detail " * 80), project="demo", pramana="smriti")
                pack = build_context_pack(conn, "release", project="demo", limit=50, max_tokens=900)
                self.assertLessEqual(estimate_tokens(pack), 900)
                self.assertIn("DIRECT_EVIDENCE", pack)
                self.assertIn("Content pruned to honor token budget", pack)
            finally:
                conn.close()

    def test_mcp_heavy_calls_can_run_concurrently(self):
        class SlowServer(RtaBrainMcpServer):
            def call_tool(self, name, arguments):
                time.sleep(0.20)
                return {"name": name}

        with tempfile.TemporaryDirectory() as tmp:
            server = SlowServer(Path(tmp) / "brain.sqlite", "demo")
            requests = [
                {"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": "brain_doctor", "arguments": {}}}
                for index in range(2)
            ]

            async def run_calls():
                started = time.perf_counter()
                responses = await asyncio.gather(*(server.handle_async(request) for request in requests))
                return responses, time.perf_counter() - started

            responses, elapsed = asyncio.run(run_calls())
            self.assertEqual(len(responses), 2)
            self.assertLess(elapsed, 0.35)

    def test_auto_parser_is_available_and_preview_rejects_traversal(self):
        registry = ParserRegistry(load_entry_points=False)
        parsed = registry.parse(Path("main.py"), "def ready():\n    return True\n", "auto")
        self.assertIn("ready", parsed.symbols)
        self.assertIn("auto", registry.capabilities())
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "brain.sqlite")
            conn.close()
            with self.assertRaisesRegex(ValueError, "relative path"):
                read_file_preview(Path(tmp) / "brain.sqlite", "demo", "../../secret.txt")

    def test_single_binary_build_contract_is_versioned(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "rta-smriti.spec").is_file())
        self.assertTrue((root / "scripts" / "build_binary.py").is_file())
        metadata = (root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('binary = ["pyinstaller', metadata.lower())

    def test_frozen_distribution_generates_native_cli_and_mcp_commands(self):
        with patch.object(project.sys, "frozen", True, create=True), patch.object(
            project.sys, "executable", "C:/Rta/rta-brain.exe"
        ):
            self.assertNotIn(" -m ", project.shell_cli_command(Path("C:/missing")))
            command, args = project._mcp_launch(Path("C:/missing"))
            self.assertEqual(command, str(Path("C:/Rta/rta-brain.exe")))
            self.assertEqual(args, ["mcp-server"])


if __name__ == "__main__":
    unittest.main()
