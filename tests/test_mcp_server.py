import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP = ROOT / "rta-brain-mcp.py"


def run_mcp(messages, db_path):
    body = "\n".join(json.dumps(message) for message in messages) + "\n"
    return subprocess.run(
        [sys.executable, str(MCP), "--db", str(db_path), "--project", "demo"],
        input=body,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )


def responses(stdout):
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


class RtaBrainMcpTests(unittest.TestCase):
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
            self.assertIn("brain_remember", tool_names)
            self.assertIn("brain_stale_check", tool_names)
            self.assertIn("brain_checkpoint", tool_names)
            self.assertIn("brain_continuation_prompt", tool_names)

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
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payloads = responses(result.stdout)
            self.assertEqual(len(payloads), 4)
            search_text = payloads[2]["result"]["content"][0]["text"]
            self.assertIn("Rta-Smriti", search_text)
            pack_text = payloads[3]["result"]["content"][0]["text"]
            self.assertIn("# Rta-Smriti Context Pack", pack_text)
            self.assertIn("Pramana: sabda", pack_text)

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
