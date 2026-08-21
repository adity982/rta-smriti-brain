import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rta_brain import benchmark, portability, project, workspaces
from rta_brain.continuity import ingest_codex_session, list_events
from rta_brain.continuity_daemon import discover_codex_sessions
from rta_brain.db import connect, init_project, remember
from rta_brain.parsers import TreeSitterParser


class V06CandidateTests(unittest.TestCase):
    def test_transcript_rebinding_starts_at_matching_turn_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            foreign = root / "foreign"
            sessions = root / "sessions"
            canonical.mkdir()
            foreign.mkdir()
            sessions.mkdir()
            transcript = sessions / "thread.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": "thread-1", "cwd": str(foreign)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "PRIVATE FOREIGN MESSAGE"}},
                {"type": "turn_context", "payload": {"cwd": str(canonical)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "Continue the canonical release"}},
            ]
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            found = discover_codex_sessions(sessions, canonical)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["binding_mode"], "turn_context")
            self.assertGreater(found[0]["binding_offset"], 0)

            conn = connect(root / "brain.sqlite")
            try:
                init_project(conn, "demo", str(canonical))
                ingest_codex_session(
                    conn,
                    transcript,
                    "demo",
                    session_id="thread-1",
                    expected_project_root=canonical,
                    expected_sessions_root=sessions,
                    binding_start_offset=found[0]["binding_offset"],
                )
                events = list_events(conn, "demo", "thread-1", limit=50)
            finally:
                conn.close()
            rendered = json.dumps(events)
            self.assertIn("Continue the canonical release", rendered)
            self.assertNotIn("PRIVATE FOREIGN MESSAGE", rendered)

    def test_transcript_rebinding_stops_outside_root_and_resumes_on_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            foreign = root / "foreign"
            sessions = root / "sessions"
            canonical.mkdir()
            foreign.mkdir()
            sessions.mkdir()
            transcript = sessions / "thread.jsonl"
            rows = [
                {"type": "session_meta", "payload": {"id": "thread-2", "cwd": str(canonical)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "CANONICAL ONE"}},
                {"type": "turn_context", "payload": {"cwd": str(foreign)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "PRIVATE FOREIGN TWO"}},
                {"type": "turn_context", "payload": {"cwd": str(canonical)}},
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "CANONICAL THREE"}},
            ]
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

            conn = connect(root / "brain.sqlite")
            try:
                init_project(conn, "demo", str(canonical))
                ingest_codex_session(
                    conn,
                    transcript,
                    "demo",
                    session_id="thread-2",
                    expected_project_root=canonical,
                    expected_sessions_root=sessions,
                )
                events = list_events(conn, "demo", "thread-2", limit=50)
            finally:
                conn.close()
            rendered = json.dumps(events)
            self.assertIn("CANONICAL ONE", rendered)
            self.assertIn("CANONICAL THREE", rendered)
            self.assertNotIn("PRIVATE FOREIGN TWO", rendered)

    def test_tree_sitter_calls_exclude_comments_and_strings(self):
        parser = TreeSitterParser()
        result = parser.parse(
            Path("service.py"),
            "# fake_comment()\ntext = 'fake_string()'\ndef run():\n    return helper()\n",
        )
        self.assertIn("helper", result.calls)
        self.assertNotIn("fake_comment", result.calls)
        self.assertNotIn("fake_string", result.calls)

    def test_encrypted_snapshot_round_trip_and_wrong_passphrase(self):
        self.assertTrue(hasattr(portability, "snapshot_create_encrypted"))
        self.assertTrue(hasattr(portability, "snapshot_verify_encrypted"))
        self.assertTrue(hasattr(portability, "snapshot_restore_encrypted"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "brain.sqlite"
            conn = connect(database)
            try:
                init_project(conn, "demo", str(root / "repo"))
                remember(conn, "secret marker for encrypted snapshot", project="demo")
            finally:
                conn.close()
            passphrase = root / "snapshot.passphrase"
            passphrase.write_text("correct horse battery staple", encoding="utf-8")
            wrong = root / "wrong.passphrase"
            wrong.write_text("wrong passphrase", encoding="utf-8")
            snapshot = root / "brain.rtae"
            restored = root / "restored.sqlite"

            created = portability.snapshot_create_encrypted(database, snapshot, passphrase_path=passphrase)
            self.assertEqual(created["encryption"], "AES-256-GCM")
            self.assertNotIn(b"SQLite format 3", snapshot.read_bytes())
            self.assertNotIn(b"secret marker", snapshot.read_bytes())
            self.assertTrue(portability.snapshot_verify_encrypted(snapshot, passphrase_path=passphrase)["valid"])
            self.assertFalse(portability.snapshot_verify_encrypted(snapshot, passphrase_path=wrong)["valid"])
            result = portability.snapshot_restore_encrypted(
                snapshot, restored, passphrase_path=passphrase,
            )
            self.assertEqual(result["status"], "ok")
            check = sqlite3.connect(restored)
            try:
                self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(check.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 1)
            finally:
                check.close()

            tampered = root / "tampered.rtae"
            tampered_bytes = bytearray(snapshot.read_bytes())
            tampered_bytes[-1] ^= 1
            tampered.write_bytes(tampered_bytes)
            tampered_result = portability.snapshot_verify_encrypted(tampered, passphrase_path=passphrase)
            self.assertFalse(tampered_result["valid"])

            with self.assertRaisesRegex(ValueError, "at least 12 bytes"):
                short = root / "short.passphrase"
                short.write_text("too-short", encoding="utf-8")
                portability.snapshot_verify_encrypted(snapshot, passphrase_path=short)

            with self.assertRaisesRegex(ValueError, "existing database"):
                portability.snapshot_restore_encrypted(
                    snapshot, restored, passphrase_path=passphrase,
                )

    def test_snapshot_passphrase_keygen_is_private_and_no_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "snapshot.passphrase"
            generated = portability.snapshot_passphrase_keygen(key_path)
            self.assertEqual(generated["status"], "ok")
            self.assertEqual(generated["entropy_bits"], 256)
            self.assertEqual(len(key_path.read_bytes()), 32)
            original = key_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                portability.snapshot_passphrase_keygen(key_path)
            self.assertEqual(key_path.read_bytes(), original)

    def test_benchmark_history_compares_latest_run_without_local_paths(self):
        self.assertTrue(hasattr(benchmark, "append_benchmark_history"))
        self.assertTrue(hasattr(benchmark, "benchmark_history"))
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.jsonl"
            first = benchmark.run_public_benchmark(benchmark.default_public_benchmark_path())
            second = json.loads(json.dumps(first))
            second["modes"]["hash_hybrid"]["recall_at_k"] += 0.1
            benchmark.append_benchmark_history(first, history_path, label="before")
            benchmark.append_benchmark_history(second, history_path, label="after")
            history = benchmark.benchmark_history(history_path)
            report = benchmark.benchmark_report_markdown(second, history=history)
        self.assertEqual(history["run_count"], 2)
        self.assertAlmostEqual(history["comparison"]["hash_hybrid"]["recall_at_k"], 0.1)
        self.assertIn("Historical Comparison", report)
        self.assertNotIn(str(Path.home()), report)

    def test_benchmark_redacts_private_dataset_label_before_reporting(self):
        source = benchmark.default_public_benchmark_path()
        payload = json.loads(source.read_text(encoding="utf-8"))
        private_label = str(Path.home() / "private" / "benchmark")
        payload["name"] = private_label
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "dataset.json"
            dataset.write_text(json.dumps(payload), encoding="utf-8")
            result = benchmark.run_public_benchmark(dataset)
            report = benchmark.benchmark_report_markdown(result)
        self.assertNotIn(private_label, result["dataset"])
        self.assertNotIn(str(Path.home()), report)

    def test_benchmark_history_fails_before_exceeding_the_run_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.jsonl"
            result = benchmark.run_public_benchmark(benchmark.default_public_benchmark_path())
            for index in range(benchmark.MAX_BENCHMARK_HISTORY_RUNS):
                benchmark.append_benchmark_history(result, history_path, label=f"run-{index}")
            before = history_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "run limit"):
                benchmark.append_benchmark_history(result, history_path, label="overflow")
            self.assertEqual(history_path.read_bytes(), before)

    def test_benchmark_history_rejects_malformed_and_non_finite_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.jsonl"
            history_path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid schema"):
                benchmark.benchmark_history(history_path)

            history_path.write_text(
                json.dumps({"modes": {"hash_hybrid": {"recall_at_k": "not-a-number"}}}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "invalid metric data"):
                benchmark.benchmark_history(history_path)

    def test_workspace_health_degraded_search_and_member_lifecycle(self):
        self.assertTrue(hasattr(workspaces, "workspace_health"))
        self.assertTrue(hasattr(workspaces, "remove_project_from_workspace"))
        self.assertTrue(hasattr(workspaces, "delete_workspace"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_path = root / "owner.sqlite"
            member_path = root / "member.sqlite"
            owner = connect(owner_path)
            member = connect(member_path)
            try:
                init_project(owner, "api", str(root / "api"))
                init_project(member, "web", str(root / "web"))
                remember(owner, "shared release contract", project="api")
                remember(member, "shared release interface", project="web")
                workspaces.create_workspace(owner, "product")
                workspaces.add_project_to_workspace(owner, workspace="product", project="api")
                workspaces.add_project_to_workspace(
                    owner, workspace="product", project="web", db_path=member_path,
                )
                member.close()
                member = None
                member_path.unlink()

                health = workspaces.workspace_health(owner, "product")
                result = workspaces.search_workspace(owner, workspace="product", query="release")
                self.assertEqual(health["status"], "degraded")
                self.assertEqual(result["status"], "degraded")
                self.assertEqual([item["project"] for item in result["results"]], ["api"])
                self.assertEqual(result["errors"][0]["project"], "web")

                removed = workspaces.remove_project_from_workspace(
                    owner, workspace="product", project="web", db_path=member_path,
                )
                self.assertEqual(len(removed["projects"]), 1)
                deleted = workspaces.delete_workspace(owner, "product")
                self.assertEqual(deleted["status"], "deleted")
            finally:
                if member is not None:
                    member.close()
                owner.close()

    def test_mcp_doctor_probes_generated_server(self):
        self.assertTrue(hasattr(project, "mcp_doctor"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "brain.sqlite"
            conn = connect(database)
            try:
                init_project(conn, "demo", str(root / "repo"))
            finally:
                conn.close()
            result = project.mcp_doctor(database, "demo", Path(__file__).resolve().parents[1], timeout=10)
        self.assertEqual(result["status"], "ready")
        self.assertGreater(result["tool_count"], 0)
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertTrue(result["fresh_task_required"])


if __name__ == "__main__":
    unittest.main()
