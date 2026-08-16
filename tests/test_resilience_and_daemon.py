import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain import db
from rta_brain.mcp_server import McpRequestScheduler, RtaBrainMcpServer
from rta_brain.parsers import ParserRegistry
from rta_brain.watch_daemon import _process_alive, start_watcher, stop_watcher, watcher_paths, watcher_status


class RtaBrainResilienceTests(unittest.TestCase):
    def test_ingest_repo_rolls_back_the_whole_refresh_when_a_parser_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            first = root / "a.py"
            second = root / "b.py"
            first.write_text("VALUE = 1\n", encoding="utf-8")
            second.write_text("VALUE = 2\n", encoding="utf-8")
            conn = db.connect(Path(tmp) / "brain.sqlite")
            try:
                db.ingest_repo(conn, root, project="demo")
                before = {
                    row["title"]: row["hash"]
                    for row in conn.execute(
                        "SELECT title, hash FROM sources ORDER BY title"
                    )
                }
                first.write_text("VALUE = 10\n", encoding="utf-8")
                second.write_text("VALUE = 20\n", encoding="utf-8")

                original = db.build_file_record
                calls = 0

                def fail_second(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise RuntimeError("parser failed")
                    return original(*args, **kwargs)

                with patch("rta_brain.db.build_file_record", side_effect=fail_second):
                    with self.assertRaisesRegex(RuntimeError, "parser failed"):
                        db.ingest_repo(conn, root, project="demo")

                after = {
                    row["title"]: row["hash"]
                    for row in conn.execute(
                        "SELECT title, hash FROM sources ORDER BY title"
                    )
                }
                self.assertEqual(after, before)
                self.assertFalse(conn.in_transaction)
            finally:
                conn.close()

    def test_tree_sitter_extracts_symbols_and_imports_for_five_core_ecosystems(self):
        registry = ParserRegistry(load_entry_points=False)
        if not registry.capabilities()["tree-sitter"]["available"]:
            self.skipTest("optional tree-sitter-language-pack is not installed")
        cases = {
            "main.py": (
                "import os\nclass Worker:\n    pass\ndef ready():\n    return True\n",
                {"Worker", "ready"},
                {"os"},
            ),
            "main.ts": (
                'import value from "pkg";\nexport class Worker {}\nexport function ready() {}\n',
                {"Worker", "ready"},
                {"pkg"},
            ),
            "main.go": (
                'package main\nimport "fmt"\ntype Worker struct {}\nfunc Ready() {}\n',
                {"Worker", "Ready"},
                {"fmt"},
            ),
            "main.rs": (
                "use std::io;\nstruct Worker {}\nfn ready() {}\n",
                {"Worker", "ready"},
                {"std::io"},
            ),
            "Main.java": (
                "import java.util.List;\nclass Worker { void ready() {} }\n",
                {"Worker", "ready"},
                {"java.util.List"},
            ),
        }
        for filename, (source, symbols, imports) in cases.items():
            with self.subTest(filename=filename):
                result = registry.parse(Path(filename), source, "tree-sitter")
                self.assertEqual(result.parser, "tree-sitter")
                self.assertTrue(symbols.issubset(set(result.symbols)), result.symbols)
                self.assertTrue(imports.issubset(set(result.imports)), result.imports)

    def test_control_messages_are_not_blocked_by_a_slow_mutation(self):
        class SlowServer(RtaBrainMcpServer):
            async def handle_async(self, request):
                params = request.get("params") or {}
                if params.get("name") == "brain_remember":
                    await asyncio.sleep(0.25)
                return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}

        async def exercise():
            emitted = []
            first_emit = asyncio.Event()

            async def emit(response):
                emitted.append(response["id"])
                first_emit.set()

            scheduler = McpRequestScheduler(SlowServer(Path("unused.sqlite"), "demo"), emit)
            await scheduler.submit(
                {
                    "jsonrpc": "2.0",
                    "id": "write",
                    "method": "tools/call",
                    "params": {"name": "brain_remember", "arguments": {"text": "x"}},
                }
            )
            await scheduler.submit({"jsonrpc": "2.0", "id": "ping", "method": "ping"})
            await asyncio.wait_for(first_emit.wait(), timeout=0.10)
            first = emitted[0]
            await scheduler.close()
            return first, emitted

        first, emitted = asyncio.run(exercise())
        self.assertEqual(first, "ping")
        self.assertEqual(set(emitted), {"write", "ping"})

    def test_dashboard_checkpoint_conflict_reloads_the_real_project_loader(self):
        source = (Path(__file__).resolve().parents[1] / "dashboard-src" / "src" / "main.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("await loadProjectDetails(selectedProject);", source)
        self.assertNotIn("await loadProject(selectedProject);", source)

    def test_console_exposes_watcher_status_and_lifecycle_controls(self):
        root = Path(__file__).resolve().parents[1]
        console = (root / "rta_brain" / "console.py").read_text(encoding="utf-8")
        dashboard = (root / "dashboard-src" / "src" / "main.jsx").read_text(encoding="utf-8")
        self.assertGreaterEqual(console.count('"/api/watcher"'), 2)
        self.assertIn("Repository sync", dashboard)
        self.assertIn("startWatcher", dashboard)
        self.assertIn("stopWatcher", dashboard)


class RtaBrainWatchDaemonTests(unittest.TestCase):
    def test_process_liveness_probe_is_non_destructive(self):
        self.assertTrue(_process_alive(os.getpid()))

    def test_background_watcher_rejects_a_hard_linked_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            db_path = Path(tmp) / "brain.sqlite"
            conn = db.connect(db_path)
            try:
                db.ingest_repo(conn, root, project="demo")
            finally:
                conn.close()
            paths = watcher_paths(db_path, "demo")
            paths["directory"].mkdir()
            victim = Path(tmp) / "victim.log"
            victim.write_text("do not append\n", encoding="utf-8")
            os.link(victim, paths["log"])

            with self.assertRaisesRegex(ValueError, "linked watcher log"):
                start_watcher(db_path, root, "demo", interval_seconds=0.2)

            self.assertEqual(victim.read_text(encoding="utf-8"), "do not append\n")
            self.assertFalse(paths["lock"].exists())

    def test_background_watcher_start_refresh_and_stop_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            source = root / "main.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            db_path = Path(tmp) / "brain.sqlite"
            conn = db.connect(db_path)
            try:
                db.ingest_repo(conn, root, project="demo")
            finally:
                conn.close()

            started = start_watcher(
                db_path=db_path,
                root=root,
                project="demo",
                interval_seconds=0.20,
                startup_timeout=8.0,
            )
            try:
                self.assertEqual(started["state"], "running")
                self.assertIn(started["backend"], {"watchdog", "polling"})
                source.write_text("VALUE = 2\n", encoding="utf-8")
                deadline = time.time() + 8
                indexed = ""
                while time.time() < deadline:
                    conn = db.connect(db_path)
                    try:
                        row = conn.execute(
                            "SELECT c.text FROM chunks c JOIN sources s ON s.id = c.source_id "
                            "JOIN projects p ON p.id = s.project_id "
                            "WHERE p.name = 'demo' AND s.title = 'main.py' ORDER BY c.ordinal LIMIT 1"
                        ).fetchone()
                        indexed = row["text"] if row else ""
                    finally:
                        conn.close()
                    if "VALUE = 2" in indexed:
                        break
                    time.sleep(0.10)
                self.assertIn("VALUE = 2", indexed)
                status = watcher_status(db_path, "demo")
                self.assertEqual(status["state"], "running")
                self.assertTrue(status["heartbeat_at"])
            finally:
                stopped = stop_watcher(db_path, "demo", timeout=8.0)
            self.assertEqual(stopped["state"], "stopped")

    def test_watchdog_ignores_its_own_control_files_inside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            brain_dir = root / ".rta-smriti"
            brain_dir.mkdir()
            db_path = brain_dir / "brain.sqlite"
            conn = db.connect(db_path)
            try:
                db.ingest_repo(conn, root, project="demo")
            finally:
                conn.close()

            started = start_watcher(db_path, root, "demo", interval_seconds=0.1)
            try:
                if started["backend"] != "watchdog":
                    self.skipTest("watchdog is not installed")
                time.sleep(0.8)
                status = watcher_status(db_path, "demo")
                self.assertLessEqual(status["cycles"], 3, status)
            finally:
                stop_watcher(db_path, "demo", timeout=8.0)


if __name__ == "__main__":
    unittest.main()
