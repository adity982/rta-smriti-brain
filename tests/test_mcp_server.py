import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rta_brain.mcp_server as mcp_server
from rta_brain.db import connect, init_project
from rta_brain.mcp_server import McpRequestScheduler, RtaBrainMcpServer


ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "rta-brain-mcp.py"


def run_mcp(messages, db_path, *extra_args):
    body = "\n".join(json.dumps(message) for message in messages) + "\n"
    return subprocess.run(
        [sys.executable, str(MCP), "--db", str(db_path), "--project", "demo", *extra_args],
        input=body,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


def responses(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


class RtaBrainMcpTests(unittest.TestCase):
    def test_thread_root_accepts_a_trusted_parent_alias(self):
        if os.name == "nt":
            self.skipTest("parent alias coverage uses POSIX symlink support")
        with tempfile.TemporaryDirectory() as tmp:
            real_parent = Path(tmp) / "real"
            real_parent.mkdir()
            root = real_parent / "allowed"
            root.mkdir()
            thread = root / "thread.md"
            thread.write_text("Decision: preserve canonical identity.\n", encoding="utf-8")
            alias_parent = Path(tmp) / "alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)

            server = RtaBrainMcpServer(
                Path(tmp) / "brain.sqlite",
                "demo",
                allow_thread_ingestion=True,
                allowed_thread_roots=(alias_parent / "allowed",),
            )
            with patch("rta_brain.mcp_server.ingest_thread", return_value={"status": "ok"}):
                result = server.call_tool(
                    "brain_ingest_thread",
                    {"path": str(alias_parent / "allowed" / thread.name)},
                )
            self.assertEqual(result["structuredContent"]["status"], "ok")

    def test_initialize_and_list_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            result = run_mcp(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                ],
                db,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(payloads[0]["id"], 1)
            self.assertIn("serverInfo", payloads[0]["result"])
            self.assertEqual(payloads[1]["id"], 2)
            tool_names = {tool["name"] for tool in payloads[1]["result"]["tools"]}
            self.assertIn("brain_search", tool_names)
            self.assertIn("brain_context_pack", tool_names)
            self.assertIn("brain_stale_check", tool_names)
            self.assertIn("brain_continuation_prompt", tool_names)
            self.assertNotIn("brain_remember", tool_names)
            self.assertNotIn("brain_checkpoint", tool_names)
            self.assertNotIn("brain_reflect", tool_names)
            self.assertNotIn("brain_ingest_repo", tool_names)
            self.assertNotIn("brain_ingest_thread", tool_names)
            self.assertNotIn("brain_workspace_search", tool_names)
            self.assertNotIn("brain_workspace_list", tool_names)

    def test_tool_calls_remember_search_and_context_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            result = run_mcp(
                [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "brain_remember",
                            "arguments": {
                                "text": "Codex should ask Rta-Smriti for context before broad repo scans.",
                                "type": "constraint",
                                "pramana": "sabda",
                                "priority": 9,
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "brain_search", "arguments": {"query": "context repo scans"}},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "brain_context_pack", "arguments": {"task": "prepare repo work"}},
                    },
                ],
                db,
                "--allow-memory-writes",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(len(payloads), 4)
            search_text = payloads[2]["result"]["content"][0]["text"]
            self.assertIn("Rta-Smriti", search_text)
            pack_text = payloads[3]["result"]["content"][0]["text"]
            self.assertIn("# Rta-Smriti Context Pack", pack_text)
            self.assertIn("Pramana: anumana", pack_text)

    def test_project_override_is_rejected_even_for_read_only_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            result = run_mcp(
                [{
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "brain_search",
                        "arguments": {"project": "other", "query": "secret"},
                    },
                }],
                db,
            )
            payload = responses(result.stdout)[0]
            self.assertEqual(payload["error"]["code"], -32000)
            self.assertIn("bound to project 'demo'", payload["error"]["message"])

    def test_mutations_require_explicit_startup_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            call = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "brain_remember", "arguments": {"text": "not authorized"}},
            }
            denied = responses(run_mcp([call], db).stdout)[0]
            self.assertEqual(denied["error"]["code"], -32000)
            self.assertIn("not enabled", denied["error"]["message"])

            listed = responses(run_mcp(
                [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}],
                db,
                "--allow-memory-writes",
                "--allow-repo-ingestion",
                "--allow-thread-ingestion",
                "--allow-thread-root",
                str(Path(tmp)),
            ).stdout)[0]
            names = {tool["name"] for tool in listed["result"]["tools"]}
            self.assertTrue({
                "brain_remember", "brain_remember_batch", "brain_checkpoint", "brain_reflect",
                "brain_ingest_repo", "brain_ingest_thread",
            }.issubset(names))
            remember_schema = next(
                tool for tool in listed["result"]["tools"] if tool["name"] == "brain_remember"
            )["inputSchema"]["properties"]
            self.assertEqual(remember_schema["pramana"]["enum"], ["anumana"])
            self.assertEqual(remember_schema["confidence"]["maximum"], 0.75)
            self.assertNotIn("source_path", remember_schema["provenance"]["properties"])
            self.assertNotIn("source_hash", remember_schema["provenance"]["properties"])
            self.assertEqual(
                remember_schema["provenance"]["properties"]["verification_status"]["enum"],
                ["unverified"],
            )
            repo_schema = next(
                tool for tool in listed["result"]["tools"] if tool["name"] == "brain_ingest_repo"
            )["inputSchema"]
            self.assertNotIn("path", repo_schema["properties"])
            self.assertNotIn("path", repo_schema["required"])

    def test_repo_ingestion_is_confined_to_the_bound_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bound"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
            (outside / "secret.py").write_text("SECRET = True\n", encoding="utf-8")
            brain = Path(tmp) / "brain.sqlite"
            conn = connect(brain)
            try:
                init_project(conn, "demo", str(root))
            finally:
                conn.close()
            server = RtaBrainMcpServer(brain, "demo", allow_repo_ingestion=True)

            accepted = server.call_tool("brain_ingest_repo", {})
            self.assertEqual(accepted["structuredContent"]["root"], str(root.resolve()))
            with self.assertRaisesRegex(ValueError, "confined to the canonical project root"):
                server.call_tool("brain_ingest_repo", {"path": str(outside)})

    def test_mcp_memory_writes_are_downgraded_to_unverified_agent_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            messages = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "brain_remember",
                        "arguments": {
                            "text": "agent assertion",
                            "pramana": "pratyaksha",
                            "confidence": 1,
                            "provenance": {
                                "source_path": "C:/secret.txt",
                                "source_hash": "forged",
                                "verification_status": "verified",
                                "command": "pytest",
                            },
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "brain_remember_batch",
                        "arguments": {"items": [{
                            "text": "batch assertion",
                            "pramana": "sabda",
                            "confidence": 0.95,
                            "provenance": {"source_hash": "forged", "verification_status": "verified"},
                        }]},
                    },
                },
            ]
            result = run_mcp(messages, db, "--allow-memory-writes")
            payloads = responses(result.stdout)
            for memory in (
                payloads[0]["result"]["structuredContent"]["memory"],
                payloads[1]["result"]["structuredContent"]["memories"][0],
            ):
                self.assertEqual(memory["pramana"], "anumana")
                self.assertLessEqual(memory["confidence"], 0.75)
                self.assertEqual(memory["provenance"]["verification_status"], "unverified")
                self.assertIsNone(memory["provenance"]["source_path"])
                self.assertIsNone(memory["provenance"]["source_hash"])

    def test_thread_ingestion_is_confined_and_rejects_linked_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            safe = root / "thread.md"
            safe.write_text("Decision: retain the verified boundary.\n", encoding="utf-8")
            outside = Path(tmp) / "outside.md"
            outside.write_text("Decision: disclose private data.\n", encoding="utf-8")
            db = Path(tmp) / "brain.sqlite"
            args = ("--allow-thread-ingestion", "--allow-thread-root", str(root))

            accepted = responses(run_mcp([{
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "brain_ingest_thread", "arguments": {"path": str(safe)}},
            }], db, *args).stdout)[0]
            self.assertEqual(accepted["result"]["structuredContent"]["status"], "ok")

            denied = responses(run_mcp([{
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "brain_ingest_thread", "arguments": {"path": str(outside)}},
            }], db, *args).stdout)[0]
            self.assertIn("outside configured thread roots", denied["error"]["message"])

            hardlink = root / "hardlink.md"
            os.link(safe, hardlink)
            linked = responses(run_mcp([{
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "brain_ingest_thread", "arguments": {"path": str(hardlink)}},
            }], db, *args).stdout)[0]
            self.assertIn("hardlink", linked["error"]["message"])

            symlink = root / "symlink.md"
            try:
                symlink.symlink_to(outside)
            except OSError:
                return
            symlinked = responses(run_mcp([{
                "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                "params": {"name": "brain_ingest_thread", "arguments": {"path": str(symlink)}},
            }], db, *args).stdout)[0]
            self.assertIn("link or reparse", symlinked["error"]["message"])

    def test_thread_ingestion_binds_secure_read_to_the_matched_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            thread = root / "thread.md"
            thread.write_text("Decision: retain the boundary.\n", encoding="utf-8")
            server = RtaBrainMcpServer(
                Path(tmp) / "brain.sqlite",
                "default",
                allow_thread_ingestion=True,
                allowed_thread_roots=(root,),
            )

            with patch("rta_brain.mcp_server.ingest_thread", return_value={"status": "ok"}) as ingest:
                result = server.call_tool("brain_ingest_thread", {"path": str(thread)})

            self.assertEqual(result["structuredContent"]["status"], "ok")
            self.assertEqual(ingest.call_args.kwargs["root"], root.resolve())

    def test_scheduler_applies_request_count_backpressure(self):
        class SlowServer(RtaBrainMcpServer):
            async def handle_async(self, request):
                await asyncio.sleep(0.08)
                return {"jsonrpc": "2.0", "id": request["id"], "result": {}}

        async def exercise():
            emitted = []

            async def emit(response):
                emitted.append(response["id"])

            scheduler = McpRequestScheduler(
                SlowServer(Path("unused.sqlite"), "demo"), emit,
                max_concurrency=1, max_outstanding=1, max_outstanding_bytes=1_000,
            )
            await scheduler.submit({"jsonrpc": "2.0", "id": 1, "method": "ping"}, frame_bytes=60)
            blocked = asyncio.create_task(
                scheduler.submit({"jsonrpc": "2.0", "id": 2, "method": "ping"}, frame_bytes=60)
            )
            await asyncio.sleep(0.02)
            was_blocked = not blocked.done()
            await blocked
            await scheduler.close()
            return was_blocked, emitted, scheduler.peak_outstanding, scheduler.peak_outstanding_bytes

        was_blocked, emitted, peak_count, peak_bytes = asyncio.run(exercise())
        self.assertTrue(was_blocked)
        self.assertEqual(emitted, [1, 2])
        self.assertEqual(peak_count, 1)
        self.assertEqual(peak_bytes, 60)

    def test_scheduler_applies_byte_backpressure(self):
        class SlowServer(RtaBrainMcpServer):
            async def handle_async(self, request):
                await asyncio.sleep(0.08)
                return {"jsonrpc": "2.0", "id": request["id"], "result": {}}

        async def exercise():
            async def emit(_response):
                return None

            scheduler = McpRequestScheduler(
                SlowServer(Path("unused.sqlite"), "demo"), emit,
                max_concurrency=2, max_outstanding=3, max_outstanding_bytes=100,
            )
            await scheduler.submit({"jsonrpc": "2.0", "id": 1, "method": "ping"}, frame_bytes=60)
            blocked = asyncio.create_task(
                scheduler.submit({"jsonrpc": "2.0", "id": 2, "method": "ping"}, frame_bytes=60)
            )
            await asyncio.sleep(0.02)
            was_blocked = not blocked.done()
            await blocked
            await scheduler.close()
            return was_blocked, scheduler.peak_outstanding_bytes

        was_blocked, peak_bytes = asyncio.run(exercise())
        self.assertTrue(was_blocked)
        self.assertEqual(peak_bytes, 60)

    def test_scheduler_preserves_mutation_order_for_following_tool_calls(self):
        class OrderedServer(RtaBrainMcpServer):
            def __init__(self):
                super().__init__(Path("unused.sqlite"), "demo", allow_memory_writes=True)
                self.events = []

            async def handle_async(self, request):
                name = request["params"]["name"]
                self.events.append(f"start:{name}")
                if name == "brain_remember":
                    await asyncio.sleep(0.05)
                self.events.append(f"end:{name}")
                return {"jsonrpc": "2.0", "id": request["id"], "result": {}}

        async def exercise():
            server = OrderedServer()

            async def emit(_response):
                return None

            scheduler = McpRequestScheduler(server, emit, max_concurrency=2)
            await scheduler.submit({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "brain_remember", "arguments": {"text": "first"}},
            })
            await scheduler.submit({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "brain_search", "arguments": {"query": "first"}},
            })
            await scheduler.close()
            return server.events

        self.assertEqual(asyncio.run(exercise()), [
            "start:brain_remember", "end:brain_remember", "start:brain_search", "end:brain_search",
        ])

    def test_excessive_json_nesting_and_recursion_errors_are_contained(self):
        nested = (b"[" * 80) + (b"]" * 80)
        with self.assertRaisesRegex(ValueError, "nesting"):
            mcp_server.parse_request_frame(nested)
        with patch("rta_brain.mcp_server.json.loads", side_effect=RecursionError("too deep")):
            with self.assertRaisesRegex(ValueError, "nesting"):
                mcp_server.parse_request_frame(b'{"jsonrpc":"2.0"}')

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            body = nested.decode("ascii") + "\n" + json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "ping"}
            ) + "\n"
            result = subprocess.run(
                [sys.executable, str(MCP), "--db", str(db), "--project", "demo"],
                input=body, text=True, capture_output=True, cwd=ROOT,
            )
            payloads = responses(result.stdout)
            self.assertEqual(payloads[0]["error"]["code"], -32700)
            self.assertEqual(payloads[1]["id"], 2)

    def test_invalid_tool_returns_json_rpc_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            result = run_mcp(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "brain_unknown", "arguments": {}},
                    }
                ],
                db,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = responses(result.stdout)[0]
            self.assertEqual(payload["error"]["code"], -32601)
            self.assertIn("unknown tool", payload["error"]["message"])

    def test_non_object_json_returns_error_without_stopping_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            result = run_mcp([[], {"jsonrpc": "2.0", "id": 2, "method": "ping"}], db)
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(payloads[0]["error"]["code"], -32600)
            self.assertEqual(payloads[1]["id"], 2)

    def test_oversized_frame_is_rejected_and_next_frame_is_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            oversized = {"jsonrpc": "2.0", "id": 1, "method": "ping", "padding": "x" * 1_100_000}
            result = run_mcp([oversized, {"jsonrpc": "2.0", "id": 2, "method": "ping"}], db)
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(payloads[0]["error"]["code"], -32600)
            self.assertIn("frame exceeds", payloads[0]["error"]["message"])
            self.assertEqual(payloads[1]["id"], 2)

    def test_multibyte_frame_limit_is_enforced_in_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "brain.sqlite"
            oversized = {"jsonrpc": "2.0", "id": 1, "method": "ping", "padding": "\u0915" * 400_000}
            result = run_mcp([oversized, {"jsonrpc": "2.0", "id": 2, "method": "ping"}], db)
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(payloads[0]["error"]["code"], -32600)
            self.assertIn("bytes", payloads[0]["error"]["message"])
            self.assertEqual(payloads[1]["id"], 2)


if __name__ == "__main__":
    unittest.main()
