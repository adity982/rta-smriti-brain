import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from rta_brain import db
from rta_brain.context_host import (
    authorize_context_contract,
    build_task_contract,
    ensure_context_agent_profile,
)
from rta_brain.mcp_server import RtaBrainMcpServer


class ContextMcpTests(unittest.TestCase):
    def test_mcp_exposes_only_agent_safe_context_compilation_and_explanation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Fixture"],
                check=True,
            )
            (root / "state.txt").write_text("ready\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "state.txt"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "fixture"],
                check=True,
                capture_output=True,
            )
            database = Path(tmp) / "brain.sqlite"
            conn = db.connect(database)
            db.init_project(conn, "demo", str(root))
            profile = ensure_context_agent_profile(
                conn,
                project="demo",
                profile_id="codex",
                actor_id="owner",
                max_input_tokens=8_192,
            )
            contract = authorize_context_contract(
                conn,
                project="demo",
                agent_profile_version_id=profile["agent_profile_version_id"],
                contract=build_task_contract(
                    project="demo",
                    agent_profile_id="codex",
                    objective="Resume the authorized task.",
                    actor_id="owner",
                    comparison_modes=["minimal"],
                ),
                actor_id="owner",
            )
            conn.close()

            denied_server = RtaBrainMcpServer(database, "demo")
            denied_tools = {tool["name"] for tool in denied_server.agent_tools}
            self.assertNotIn("brain_context_compile", denied_tools)
            self.assertNotIn("brain_context_explain", denied_tools)
            with self.assertRaisesRegex(ValueError, "not enabled"):
                denied_server.call_tool(
                    "brain_context_compile",
                    {"task_contract_id": contract["task_contract_id"]},
                )

            server = RtaBrainMcpServer(
                database,
                "demo",
                context_contract_delegations={
                    contract["task_contract_id"]: contract["digest"]
                },
            )
            exposed = {tool["name"] for tool in server.agent_tools}
            compiled = server.call_tool(
                "brain_context_compile",
                {"task_contract_id": contract["task_contract_id"], "variant": "primary"},
            )["structuredContent"]
            explained = server.call_tool(
                "brain_context_explain",
                {"compilation_id": compiled["compilation_receipt"]["compilation_id"]},
            )["structuredContent"]

        serialized = json.dumps(
            {"compiled": compiled, "explained": explained}, sort_keys=True
        )
        self.assertIn("brain_context_compile", exposed)
        self.assertIn("brain_context_explain", exposed)
        self.assertNotIn("brain_context_audit", exposed)
        self.assertEqual(compiled["status"], "stable")
        self.assertTrue(explained["receipt_integrity_verified"])
        self.assertNotIn("capability_token", serialized)
        self.assertNotIn("authority_secret", serialized)
        self.assertNotIn("operator_audit", serialized)

    def test_mcp_rejects_invalid_context_contract_delegations(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "brain.sqlite"
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
            conn = db.connect(database)
            db.init_project(conn, "demo", str(root))
            conn.close()

            with self.assertRaisesRegex(ValueError, "64-character SHA-256"):
                RtaBrainMcpServer(
                    database,
                    "demo",
                    context_contract_delegations={1: "not-a-digest"},
                )


if __name__ == "__main__":
    unittest.main()
