import json
import os
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from unittest import mock

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "capture"
SYNTHETIC_POSIX_USER_PATH = PurePosixPath(
    "C:/", "Users", "alice", "private.txt"
).as_posix()


class CaptureAdapterTests(unittest.TestCase):
    def test_catalog_has_versioned_deterministic_schema_fingerprints(self):
        from rta_brain.capture_adapters import adapter_catalog

        first = adapter_catalog()
        second = adapter_catalog()
        self.assertEqual(
            set(first),
            {
                "generic",
                "codex-jsonl",
                "claude-code",
                "cursor",
                "github-copilot",
                "gemini-cli",
            },
        )
        for name, adapter in first.items():
            self.assertRegex(adapter.schema_fingerprint, r"^[0-9a-f]{64}$")
            self.assertEqual(
                adapter.schema_fingerprint, second[name].schema_fingerprint
            )
            self.assertTrue(adapter.version)

    def test_neutral_vendor_fixtures_normalize_without_private_extras(self):
        from rta_brain.capture_adapters import normalize_capture_event

        for fixture_path in sorted(FIXTURE_ROOT.glob("*.json")):
            with self.subTest(fixture=fixture_path.name):
                fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
                event = normalize_capture_event(
                    fixture["adapter"],
                    fixture["payload"],
                    vendor_event=fixture["vendor_event"],
                    trusted_workspace_roots=tuple(
                        fixture.get("trusted_workspace_roots", ())
                    ),
                    adapter_version=fixture["adapter_version"],
                    source_cursor=fixture["cursor"],
                    observed_at=fixture["observed_at"],
                    session_id=fixture["session_id"],
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.event_name, fixture["expected_event"])
                serialized = json.dumps(event.attributes, sort_keys=True)
                self.assertNotIn("unknown_private_field", serialized)
                self.assertNotIn("synthetic-secret", serialized)
                self.assertNotIn("C:/private", serialized)
                if fixture["adapter"] == "cursor":
                    self.assertEqual(event.attributes["path"], "src/example.py")

    def test_adapter_version_and_normalized_digest_are_deterministic(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import canonical_json

        arguments = {
            "adapter_name": "generic",
            "adapter_version": "1",
            "payload": {"type": "command_complete", "command": "test", "exit_code": 0},
            "source_cursor": "digest-1",
            "observed_at": "2026-08-22T12:00:00Z",
            "session_id": "session-digest-001",
        }
        first = normalize_capture_event(**arguments)
        second = normalize_capture_event(**arguments)
        self.assertEqual(first, second)
        self.assertEqual(
            canonical_json(dict(first.attributes)),
            canonical_json(dict(second.attributes)),
        )
        with self.assertRaisesRegex(ValueError, "version"):
            normalize_capture_event(**{**arguments, "adapter_version": "future-v2"})

    def test_generic_taxonomy_covers_continuity_events(self):
        from rta_brain.capture_adapters import normalize_capture_event

        expected = {
            "session_start": "session.started.v1",
            "session_resume": "session.resumed.v1",
            "session_stop": "session.ended.v1",
            "turn_start": "turn.started.v1",
            "turn_complete": "turn.completed.v1",
            "turn_interrupt": "turn.interrupted.v1",
            "turn_compact": "turn.compacted.v1",
            "prompt": "prompt.submitted.v1",
            "decision": "user.decision.v1",
            "approval": "user.approval.v1",
            "tool_request": "tool.requested.v1",
            "tool_start": "tool.started.v1",
            "tool_complete": "tool.completed.v1",
            "tool_error": "tool.failed.v1",
            "command_start": "command.started.v1",
            "command_complete": "command.completed.v1",
            "file_read": "file.read.v1",
            "file_edit": "file.edited.v1",
            "mcp_request": "mcp.requested.v1",
            "mcp_complete": "mcp.completed.v1",
            "error": "adapter.error.v1",
        }
        for index, (vendor_event, event_name) in enumerate(expected.items()):
            with self.subTest(vendor_event=vendor_event):
                event = normalize_capture_event(
                    "generic",
                    {"type": vendor_event, "status": "ok"},
                    source_cursor=str(index),
                    observed_at="2026-08-22T12:00:00Z",
                    session_id="session-taxonomy-001",
                )
                self.assertEqual(event.event_name, event_name)

    def test_unknown_fields_are_dropped_before_recursive_secret_redaction(self):
        from rta_brain.capture_adapters import normalize_capture_event

        event = normalize_capture_event(
            "generic",
            {
                "type": "tool_complete",
                "tool": "local.search",
                "status": "ok",
                "summary": (
                    "token sk-syntheticabcdefghijklmnopqrstuvwxyz; "
                    "authToken: opaque-synthetic-credential-1234567890"
                ),
                "metadata": {
                    "authorization": "Bearer synthetic-secret",
                    "authToken": "opaque-synthetic-credential-1234567890",
                },
                "private_blob": "must not survive",
            },
            source_cursor="7",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-redaction-001",
        )
        serialized = json.dumps(event.attributes, sort_keys=True)
        self.assertNotIn("private_blob", serialized)
        self.assertNotIn("must not survive", serialized)
        self.assertNotIn("sk-synthetic", serialized)
        self.assertNotIn("Bearer synthetic-secret", serialized)
        self.assertNotIn("opaque-synthetic-credential", serialized)

    def test_nested_keys_and_pre_truncation_values_are_sanitized(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        sensitive_key = "Authorization: Bearer synthetic-key-secret-1234567890"
        delayed_secret = "x" * 252 + " sk-" + "a" * 64
        policy = CapturePolicy(
            profile="continuity",
            field_allowlist={"tool.completed.v1": ("summary", "metadata")},
            max_field_chars=256,
        )

        event = normalize_capture_event(
            "generic",
            {
                "type": "tool_complete",
                "summary": delayed_secret,
                "metadata": {sensitive_key: "safe"},
            },
            source_cursor="redaction-boundary",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-redaction-boundary",
            policy=policy,
        )

        serialized = json.dumps(event.attributes, sort_keys=True)
        self.assertNotIn("synthetic-key-secret", serialized)
        self.assertNotIn("sk-", serialized)
        self.assertEqual(event.attributes["metadata"], {"[REDACTED]": "safe"})

    def test_unknown_event_is_ignored_unless_vendor_event_policy_is_explicit(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        arguments = {
            "adapter_name": "generic",
            "payload": {"type": "future_event", "private": "drop"},
            "source_cursor": "8",
            "observed_at": "2026-08-22T12:00:00Z",
            "session_id": "session-gap-001",
        }
        self.assertIsNone(normalize_capture_event(**arguments))
        policy = CapturePolicy(
            profile="continuity",
            enabled_event_names=("vendor.event.v1",),
            field_allowlist={"vendor.event.v1": ("vendor_event",)},
        )
        vendor = normalize_capture_event(**arguments, policy=policy)
        self.assertEqual(vendor.event_name, "vendor.event.v1")
        self.assertEqual(vendor.attributes, {"vendor_event": "futureevent"})
        self.assertNotIn("private", vendor.attributes)

    def test_trace_identifiers_are_opaque_and_strictly_validated(self):
        from rta_brain.capture_adapters import normalize_capture_event

        valid = normalize_capture_event(
            "generic",
            {
                "type": "session_start",
                "trace_id": "1" * 32,
                "span_id": "2" * 16,
                "parent_span_id": "3" * 16,
            },
            source_cursor="9",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-trace-001",
        )
        self.assertEqual(valid.trace_id, "1" * 32)
        with self.assertRaisesRegex(ValueError, "trace_id"):
            normalize_capture_event(
                "generic",
                {"type": "session_start", "trace_id": "not-a-trace"},
                source_cursor="10",
                observed_at="2026-08-22T12:00:00Z",
                session_id="session-trace-001",
            )

    def test_policy_empty_allowlist_and_event_budget_fail_closed(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        empty = CapturePolicy(
            profile="continuity",
            field_allowlist={"agent.message.v1": ()},
        )
        event = normalize_capture_event(
            "generic",
            {"type": "agent_message", "content": "must be omitted"},
            source_cursor="11",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-policy-001",
            policy=empty,
        )
        self.assertEqual(event.attributes, {})

        bounded = CapturePolicy(
            profile="continuity",
            field_allowlist={"agent.message.v1": ("text",)},
            max_event_bytes=1_024,
            max_field_chars=16_000,
        )
        with self.assertRaisesRegex(ValueError, "byte budget"):
            normalize_capture_event(
                "generic",
                {"type": "agent_message", "content": "x" * 2_000},
                source_cursor="12",
                observed_at="2026-08-22T12:00:00Z",
                session_id="session-policy-001",
                policy=bounded,
            )

    def test_deep_attributes_are_rejected_and_external_ids_are_opaque(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        nested = {}
        cursor = nested
        for _ in range(20):
            cursor["child"] = {}
            cursor = cursor["child"]
        policy = CapturePolicy(
            profile="continuity",
            field_allowlist={"tool.completed.v1": ("metadata",)},
        )
        with self.assertRaisesRegex(ValueError, "depth"):
            normalize_capture_event(
                "generic",
                {"type": "tool_complete", "metadata": nested},
                source_cursor="13",
                observed_at="2026-08-22T12:00:00Z",
                session_id="session-depth-001",
                policy=policy,
            )

        event = normalize_capture_event(
            "generic",
            {
                "type": "session_start",
                "event_id": "private-vendor-id",
                "correlation_id": "private-correlation-id",
            },
            source_cursor="14",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-id-001",
        )
        self.assertRegex(event.external_event_id, r"^[0-9a-f]{64}$")
        self.assertRegex(event.correlation_id, r"^[0-9a-f]{64}$")
        self.assertNotIn("private", event.external_event_id)

    def test_metadata_only_omits_content_and_hashes_private_references(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        prompt = normalize_capture_event(
            "generic",
            {"type": "prompt", "text": "PRIVATE PROMPT"},
            source_cursor="15",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-metadata-001",
            policy=CapturePolicy.metadata_only(),
        )
        tool = normalize_capture_event(
            "generic",
            {
                "type": "tool_complete",
                "tool": "local.search",
                "status": "ok",
                "summary": "PRIVATE OUTPUT",
                "call_id": "private/reference/path",
                "metadata": {"credentials": {"passcode": "synthetic-secret"}},
                "duration_ms": 7,
            },
            source_cursor="16",
            observed_at="2026-08-22T12:00:01Z",
            session_id="session-metadata-001",
            policy=CapturePolicy.metadata_only(),
        )
        self.assertEqual(prompt.attributes, {})
        self.assertEqual(
            set(tool.attributes), {"tool", "status", "duration_ms", "call_id"}
        )
        self.assertRegex(tool.attributes["call_id"], r"^[0-9a-f]{64}$")
        self.assertNotIn("private", json.dumps(tool.attributes))

    def test_official_vendor_lifecycle_names_remain_distinct(self):
        from rta_brain.capture_adapters import normalize_capture_event

        cases = (
            ("claude-code", "Stop", "turn.completed.v1"),
            ("claude-code", "SessionEnd", "session.ended.v1"),
            ("cursor", "stop", "turn.completed.v1"),
            ("cursor", "sessionEnd", "session.ended.v1"),
            ("cursor", "preCompact", "turn.compacted.v1"),
            ("github-copilot", "UserPromptSubmit", "prompt.submitted.v1"),
        )
        for index, (adapter, vendor_event, expected) in enumerate(cases):
            with self.subTest(adapter=adapter, vendor_event=vendor_event):
                event = normalize_capture_event(
                    adapter,
                    {"hook_event_name": vendor_event, "prompt": "synthetic"},
                    source_cursor=f"lifecycle-{index}",
                    observed_at="2026-08-22T12:00:00Z",
                    session_id="session-lifecycle-001",
                )
                self.assertEqual(event.event_name, expected)

    def test_copilot_camel_case_payload_uses_configured_hook_name(self):
        from rta_brain.capture_adapters import normalize_capture_event

        event = normalize_capture_event(
            "github-copilot",
            {
                "sessionId": "synthetic-session",
                "timestamp": 1_787_000_000_000,
                "cwd": "/synthetic/workspace",
                "prompt": "Synthetic prompt",
            },
            vendor_event="userPromptSubmitted",
            source_cursor="copilot-camel-1",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-copilot-camel-001",
        )
        self.assertEqual(event.event_name, "prompt.submitted.v1")
        self.assertEqual(event.attributes, {"text": "Synthetic prompt"})

    def test_absolute_file_paths_require_an_explicit_containing_workspace(self):
        from rta_brain.capture_adapters import normalize_capture_event

        event = normalize_capture_event(
            "cursor",
            {
                "hook_event_name": "afterFileEdit",
                "workspace_roots": ["C:/synthetic/workspace"],
                "file_path": "C:/outside/private.py",
            },
            source_cursor="path-1",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-path-001",
            trusted_workspace_roots=("C:/synthetic/workspace",),
        )
        self.assertEqual(event.attributes, {})

        untrusted_cwd = normalize_capture_event(
            "cursor",
            {
                "hook_event_name": "afterFileEdit",
                "cwd": "C:/",
                "file_path": SYNTHETIC_POSIX_USER_PATH,
            },
            source_cursor="path-2",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-path-001",
        )
        self.assertEqual(untrusted_cwd.attributes, {})

        spoofed_root = normalize_capture_event(
            "cursor",
            {
                "hook_event_name": "afterFileEdit",
                "workspace_roots": ["C:/"],
                "file_path": SYNTHETIC_POSIX_USER_PATH,
            },
            source_cursor="path-3",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-path-001",
        )
        self.assertEqual(spoofed_root.attributes, {})

        for unsafe_path in (
            SYNTHETIC_POSIX_USER_PATH.replace("C:/", "C:", 1),
            "src/example.py:private-stream",
        ):
            with self.subTest(unsafe_path=unsafe_path):
                unsafe = normalize_capture_event(
                    "cursor",
                    {"hook_event_name": "afterFileEdit", "file_path": unsafe_path},
                    source_cursor="path-unsafe",
                    observed_at="2026-08-22T12:00:00Z",
                    session_id="session-path-001",
                    trusted_workspace_roots=("C:/synthetic/workspace",),
                )
                self.assertEqual(unsafe.attributes, {})

    def test_session_start_resume_source_maps_to_resumed_event(self):
        from rta_brain.capture_adapters import normalize_capture_event

        for adapter in ("claude-code", "github-copilot", "gemini-cli"):
            with self.subTest(adapter=adapter):
                event = normalize_capture_event(
                    adapter,
                    {"hook_event_name": "SessionStart", "source": "resume"},
                    source_cursor=f"resume-{adapter}",
                    observed_at="2026-08-22T12:00:00Z",
                    session_id="session-resume-001",
                )
                self.assertEqual(event.event_name, "session.resumed.v1")

    def test_gemini_after_tool_error_and_after_agent_are_classified_correctly(self):
        from rta_brain.capture_adapters import normalize_capture_event

        failed = normalize_capture_event(
            "gemini-cli",
            {
                "hook_event_name": "AfterTool",
                "tool_name": "read_file",
                "tool_response": {"error": {"message": "synthetic failure"}},
            },
            source_cursor="gemini-tool-1",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-gemini-tool-001",
        )
        completed = normalize_capture_event(
            "gemini-cli",
            {"hook_event_name": "AfterAgent", "prompt_response": "synthetic response"},
            source_cursor="gemini-agent-1",
            observed_at="2026-08-22T12:00:01Z",
            session_id="session-gemini-tool-001",
        )
        self.assertEqual(failed.event_name, "tool.failed.v1")
        self.assertEqual(failed.attributes["summary"], "synthetic failure")
        self.assertEqual(completed.event_name, "turn.completed.v1")

    def test_sanitizer_uses_one_aggregate_item_budget_without_materializing(self):
        from rta_brain.capture_adapters import normalize_capture_event
        from rta_brain.capture_types import CapturePolicy

        class CountingMapping(Mapping):
            def __init__(self):
                self.requested = 0

            def __len__(self):
                return 1_000_000

            def __iter__(self):
                for index in range(1_000_000):
                    self.requested += 1
                    if self.requested > 4:
                        raise AssertionError("sanitizer over-consumed the mapping")
                    yield f"field-{index}"

            def __getitem__(self, key):
                return "synthetic"

        metadata = CountingMapping()
        policy = CapturePolicy(
            profile="continuity",
            field_allowlist={"tool.completed.v1": ("metadata",)},
            max_collection_items=4,
        )
        event = normalize_capture_event(
            "generic",
            {"type": "tool_complete", "metadata": metadata},
            source_cursor="17",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-budget-001",
            policy=policy,
        )
        self.assertLessEqual(metadata.requested, 4)
        self.assertLessEqual(len(event.attributes["metadata"]), 4)

        aggregate_policy = CapturePolicy(
            profile="continuity",
            field_allowlist={"tool.completed.v1": ("summary", "metadata")},
            max_collection_items=3,
        )
        aggregate = normalize_capture_event(
            "generic",
            {
                "type": "tool_complete",
                "summary": {f"summary-{index}": index for index in range(10)},
                "metadata": {f"metadata-{index}": index for index in range(10)},
            },
            source_cursor="18",
            observed_at="2026-08-22T12:00:00Z",
            session_id="session-budget-001",
            policy=aggregate_policy,
        )
        retained = len(aggregate.attributes["summary"]) + len(
            aggregate.attributes["metadata"]
        )
        self.assertLessEqual(retained, 3)

    def test_codex_legacy_mapper_routes_through_normalized_adapter(self):
        from rta_brain import continuity
        from rta_brain.capture_types import NormalizedEvent

        normalized = NormalizedEvent(
            event_name="agent.message.v1",
            session_id="session-codex-001",
            source_cursor="0",
            observed_at="2026-08-22T12:00:00Z",
            attributes={"role": "assistant", "content": "synthetic"},
        )
        with mock.patch(
            "rta_brain.continuity.normalize_capture_event",
            return_value=normalized,
        ) as mapper:
            event_type, payload = continuity._codex_event(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": "synthetic",
                    },
                }
            )
        mapper.assert_called_once()
        self.assertEqual(event_type, "message")
        self.assertEqual(payload, {"role": "assistant", "content": "synthetic"})

    def test_codex_legacy_mapper_never_restores_raw_tool_fields(self):
        from rta_brain import continuity
        from rta_brain.capture_types import NormalizedEvent

        normalized = NormalizedEvent(
            event_name="tool.completed.v1",
            session_id="session-safe",
            source_cursor="0",
            observed_at="2026-08-22T12:00:00Z",
            attributes={"tool": "local.search", "status": "ok", "summary": "safe"},
        )
        raw_secret = "synthetic-private-tool-output-1234567890"
        with mock.patch(
            "rta_brain.continuity.normalize_capture_event",
            return_value=normalized,
        ):
            event_type, payload = continuity._codex_event(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "private-call-id",
                        "output": raw_secret,
                        "cwd": SYNTHETIC_POSIX_USER_PATH,
                    },
                }
            )

        serialized = json.dumps(payload, sort_keys=True)
        self.assertEqual(event_type, "tool_event")
        self.assertEqual(payload, dict(normalized.attributes))
        self.assertNotIn(raw_secret, serialized)
        self.assertNotIn("private-call-id", serialized)
        self.assertNotIn(SYNTHETIC_POSIX_USER_PATH, serialized)


class AdapterInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.project = self.base / "project"
        self.brain = self.base / "brain.sqlite"
        self.tool = self.base / "trusted" / "rta-brain"
        self.home.mkdir()
        self.project.mkdir()
        self.tool.parent.mkdir()
        self.tool.write_text("synthetic executable", encoding="utf-8")
        self.brain.touch()

    def tearDown(self):
        self.temp.cleanup()

    def plan(self, adapter="cursor", scope="project"):
        from rta_brain.capture_adapters import plan_adapter_installation

        return plan_adapter_installation(
            adapter,
            scope=scope,
            project_root=self.project,
            home=self.home,
            brain_path=self.brain,
            command_parts=(str(self.tool), "capture", "emit", "--adapter", adapter),
            platform_name="win32",
        )

    def test_plan_is_preview_only_and_uses_vendor_scope_paths(self):
        expected = {
            ("claude-code", "project"): self.project
            / ".claude"
            / "settings.local.json",
            ("cursor", "project"): self.project / ".cursor" / "hooks.json",
            ("github-copilot", "project"): self.project
            / ".github"
            / "copilot"
            / "settings.local.json",
            ("gemini-cli", "project"): self.project / ".gemini" / "settings.json",
            ("claude-code", "user"): self.home / ".claude" / "settings.json",
            ("cursor", "user"): self.home / ".cursor" / "hooks.json",
            ("github-copilot", "user"): self.home
            / ".copilot"
            / "hooks"
            / "rta-smriti.json",
            ("gemini-cli", "user"): self.home / ".gemini" / "settings.json",
        }
        for (adapter, scope), path in expected.items():
            with self.subTest(adapter=adapter, scope=scope):
                plan = self.plan(adapter, scope)
                self.assertEqual(plan.config_path, path)
                self.assertEqual(plan.action, "create")
                self.assertFalse(path.exists())
                self.assertTrue(plan.preview)
                self.assertTrue(plan.managed_fragment)
                self.assertFalse((self.base / ".rta-smriti-capture").exists())

    def test_install_is_structured_idempotent_and_preserves_unrelated_order(self):
        from rta_brain.capture_adapters import install_adapter
        from rta_brain.capture_spool import CaptureSpool

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "unrelated": {"keep": True},
                    "hooks": {"afterFileEdit": [{"command": "existing-tool"}]},
                }
            ),
            encoding="utf-8",
        )
        first = install_adapter(self.plan())
        installed = json.loads(config.read_text(encoding="utf-8"))
        self.assertTrue(first["installed"])
        self.assertEqual(installed["unrelated"], {"keep": True})
        self.assertEqual(
            installed["hooks"]["afterFileEdit"][0]["command"], "existing-tool"
        )
        self.assertGreater(len(installed["hooks"]["afterFileEdit"]), 1)

        second = install_adapter(self.plan())
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(json.loads(config.read_text(encoding="utf-8")), installed)
        self.assertEqual(CaptureSpool(self.brain).usage_summary()["total_records"], 0)

    def test_remove_deletes_only_exact_managed_fragments_and_preserves_backup(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        original = {"version": 1, "hooks": {"stop": [{"command": "keep-me"}]}}
        config.write_text(json.dumps(original), encoding="utf-8")
        receipt = install_adapter(self.plan())
        removed = remove_adapter(
            brain_path=self.brain,
            installation_id=receipt["installation_id"],
        )
        self.assertTrue(removed["removed"])
        current = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(current["hooks"]["stop"], [{"command": "keep-me"}])
        self.assertTrue(Path(receipt["backup_path"]).is_file())

    def test_remove_refuses_drifted_managed_fragment(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        receipt = install_adapter(self.plan())
        config = Path(receipt["config_path"])
        payload = json.loads(config.read_text(encoding="utf-8"))
        event = next(iter(payload["hooks"]))
        payload["hooks"][event][0]["command"] = "changed-by-someone-else"
        config.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "managed fragment drifted"):
            remove_adapter(
                brain_path=self.brain,
                installation_id=receipt["installation_id"],
            )

    def test_linked_ambiguous_and_enterprise_managed_configs_are_refused(self):
        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"version": 1, "hooks": []}), encoding="utf-8")
        with self.assertRaisesRegex((TypeError, ValueError), "hooks object"):
            self.plan()

        config.write_text(
            json.dumps({"version": 1, "allowManagedHooksOnly": True, "hooks": {}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "enterprise-managed"):
            self.plan()

        config.unlink()
        target = self.base / "target.json"
        target.write_text("{}", encoding="utf-8")
        try:
            config.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are unavailable")
        with self.assertRaisesRegex(ValueError, "linked"):
            self.plan()

    def test_unreceipted_managed_fragment_is_ambiguous_and_refused(self):
        plan = self.plan()
        plan.config_path.parent.mkdir(parents=True)
        plan.config_path.write_text(json.dumps(plan.target_document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ambiguous unmanaged fragment"):
            self.plan()

    def test_changed_after_preview_is_refused_without_backup_or_receipt(self):
        from rta_brain.capture_adapters import install_adapter

        plan = self.plan()
        plan.config_path.parent.mkdir(parents=True)
        plan.config_path.write_text('{"unrelated":true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed after preview"):
            install_adapter(plan)
        self.assertFalse(plan.backup_path.exists())
        self.assertFalse(plan.receipt_path.exists())

    def test_install_rejects_a_concurrent_edit_at_the_commit_boundary(self):
        from rta_brain import capture_adapters
        from rta_brain.capture_adapters import install_adapter

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"version":1,"unrelated":true}', encoding="utf-8")
        plan = self.plan()
        real_overwrite = capture_adapters._overwrite_open_config

        def edit_then_overwrite(path, **kwargs):
            path.write_text('{"version":1,"concurrent":true}', encoding="utf-8")
            return real_overwrite(path, **kwargs)

        with (
            mock.patch(
                "rta_brain.capture_adapters._overwrite_open_config",
                side_effect=edit_then_overwrite,
            ),
            self.assertRaisesRegex(ValueError, "changed during installation"),
        ):
            install_adapter(plan)

        self.assertEqual(
            json.loads(config.read_text(encoding="utf-8")),
            {"version": 1, "concurrent": True},
        )

    def test_install_rejects_a_final_component_symlink_swap(self):
        from rta_brain import capture_adapters
        from rta_brain.capture_adapters import install_adapter

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"version":1,"unrelated":true}', encoding="utf-8")
        plan = self.plan()
        victim = self.base / "victim.json"
        victim.write_bytes(config.read_bytes())
        real_overwrite = capture_adapters._overwrite_open_config

        def swap_then_overwrite(path, **kwargs):
            path.unlink()
            try:
                path.symlink_to(victim)
            except OSError as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")
            return real_overwrite(path, **kwargs)

        with (
            mock.patch(
                "rta_brain.capture_adapters._overwrite_open_config",
                side_effect=swap_then_overwrite,
            ),
            self.assertRaisesRegex((OSError, ValueError), "linked|unsafe|symlink"),
        ):
            install_adapter(plan)

        self.assertEqual(victim.read_bytes(), b'{"version":1,"unrelated":true}')

    def test_interrupted_install_leaves_a_recoverable_prepared_receipt(self):
        from rta_brain import capture_adapters
        from rta_brain.capture_adapters import install_adapter

        plan = self.plan()
        real_write = capture_adapters.write_json
        writes = 0

        def fail_final_receipt(path, payload, **kwargs):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("synthetic receipt finalization failure")
            return real_write(path, payload, **kwargs)

        with (
            mock.patch(
                "rta_brain.capture_adapters.write_json",
                side_effect=fail_final_receipt,
            ),
            self.assertRaisesRegex(OSError, "finalization failure"),
        ):
            install_adapter(plan)

        prepared = json.loads(plan.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(prepared["state"], "prepared")
        self.assertFalse(prepared["installed"])
        self.assertEqual(
            json.loads(plan.config_path.read_text(encoding="utf-8")),
            plan.target_document,
        )

        recovery_plan = self.plan()
        self.assertEqual(recovery_plan.action, "recover")
        recovered = install_adapter(recovery_plan)
        self.assertEqual(recovered["state"], "installed")
        self.assertTrue(recovered["installed"])

    def test_install_refuses_replaced_allowed_root_after_preview(self):
        from rta_brain.capture_adapters import install_adapter

        plan = self.plan()
        original_root = self.base / "project-before-swap"
        self.project.rename(original_root)
        self.project.mkdir()

        with self.assertRaisesRegex(ValueError, "ancestor changed after preview"):
            install_adapter(plan)

        self.assertFalse(plan.config_path.exists())
        self.assertFalse(plan.receipt_path.exists())

    def test_install_never_replaces_a_config_in_a_swapped_parent(self):
        from unittest.mock import patch

        from rta_brain import capture_adapters
        from rta_brain.capture_adapters import install_adapter

        plan = self.plan()
        parent = plan.config_path.parent
        displaced = self.project / ".cursor-displaced"
        real_replace = os.replace
        swapped = False

        def swap_parent():
            nonlocal swapped
            if not swapped:
                try:
                    parent.rename(displaced)
                    parent.mkdir()
                except OSError:
                    return False
                plan.config_path.write_text('{"victim":true}', encoding="utf-8")
                swapped = True
            return True

        def swap_then_replace(source, target, *args, **kwargs):
            if swap_parent():
                source_name = Path(source).name
                (parent / source_name).write_text('{"attacker":true}', encoding="utf-8")
            return real_replace(source, target, *args, **kwargs)

        real_windows_replace = capture_adapters._windows_replace_open_file

        def swap_then_windows_replace(handle, parent_handle, target_name):
            swap_parent()
            return real_windows_replace(handle, parent_handle, target_name)

        installed = None
        error = None
        patch_target = (
            patch(
                "rta_brain.capture_adapters._windows_replace_open_file",
                side_effect=swap_then_windows_replace,
            )
            if os.name == "nt"
            else patch("rta_brain.capture_adapters.os.replace", side_effect=swap_then_replace)
        )
        with patch_target:
            try:
                installed = install_adapter(plan)
            except ValueError as exc:
                error = exc

        if swapped:
            self.assertIsNotNone(error)
            self.assertRegex(str(error), "ancestor changed after preview")
            self.assertEqual(plan.config_path.read_text(encoding="utf-8"), '{"victim":true}')
        else:
            self.assertIsNone(error)
            self.assertTrue(installed["installed"])

    def test_remove_refuses_replaced_allowed_root_without_touching_replacement(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        installed = install_adapter(self.plan())
        installed_config = Path(installed["config_path"])
        replacement_bytes = installed_config.read_bytes()
        original_root = self.base / "project-before-remove-swap"
        self.project.rename(original_root)
        installed_config.parent.mkdir(parents=True)
        installed_config.write_bytes(replacement_bytes)

        with self.assertRaisesRegex(ValueError, "ancestor changed after preview"):
            remove_adapter(
                brain_path=self.brain,
                installation_id=installed["installation_id"],
            )

        self.assertEqual(installed_config.read_bytes(), replacement_bytes)

    def test_update_replaces_only_managed_fragment_and_keeps_first_backup(self):
        from rta_brain.capture_adapters import install_adapter

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        original_raw = b'{"version":1,"unrelated":"keep","hooks":{}}'
        config.write_bytes(original_raw)
        first = install_adapter(self.plan())
        first_backup = Path(first["backup_path"])
        self.assertEqual(first_backup.read_bytes(), original_raw)

        replacement = self.base / "trusted" / "rta-brain-v2"
        replacement.write_text("synthetic executable v2", encoding="utf-8")
        from rta_brain.capture_adapters import plan_adapter_installation

        update = plan_adapter_installation(
            "cursor",
            scope="project",
            project_root=self.project,
            home=self.home,
            brain_path=self.brain,
            command_parts=(str(replacement), "capture", "emit", "--adapter", "cursor"),
            platform_name="win32",
        )
        self.assertEqual(update.action, "update")
        install_adapter(update)
        installed = config.read_text(encoding="utf-8")
        self.assertIn("rta-brain-v2", installed)
        self.assertNotIn('rta-brain\\" capture', installed)
        self.assertEqual(first_backup.read_bytes(), original_raw)

    def test_remove_restores_original_bytes_or_empties_created_config(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        config = self.project / ".cursor" / "hooks.json"
        config.parent.mkdir(parents=True)
        original_raw = b'{ "version": 1, "hooks": {}, "format": "preserve" }\n'
        config.write_bytes(original_raw)
        installed = install_adapter(self.plan())
        remove_adapter(
            brain_path=self.brain, installation_id=installed["installation_id"]
        )
        self.assertEqual(config.read_bytes(), original_raw)

        other_project = self.base / "other-project"
        other_project.mkdir()
        from rta_brain.capture_adapters import plan_adapter_installation

        created_plan = plan_adapter_installation(
            "cursor",
            scope="project",
            project_root=other_project,
            home=self.home,
            brain_path=self.brain,
            command_parts=(str(self.tool), "capture", "emit", "--adapter", "cursor"),
            platform_name="win32",
        )
        created = install_adapter(created_plan)
        created_path = Path(created["config_path"])
        self.assertTrue(created_path.exists())
        remove_adapter(
            brain_path=self.brain, installation_id=created["installation_id"]
        )
        self.assertEqual(json.loads(created_path.read_text(encoding="utf-8")), {})

    def test_remove_mutates_the_opened_config_not_a_swapped_path(self):
        from unittest.mock import patch

        from rta_brain.capture_adapters import install_adapter, remove_adapter

        installed = install_adapter(self.plan())
        config = Path(installed["config_path"])
        original_parent = config.parent
        displaced_parent = self.project / ".cursor-reviewed"
        real_write = os.write
        swapped = False

        def swap_then_write(descriptor, payload):
            nonlocal swapped
            if not swapped:
                try:
                    original_parent.rename(displaced_parent)
                    original_parent.mkdir()
                except OSError:
                    self.skipTest("the platform does not allow an ancestor swap while the file is open")
                config.write_text('{"victim":true}', encoding="utf-8")
                swapped = True
            return real_write(descriptor, payload)

        with (
            patch("rta_brain.capture_adapters.os.write", side_effect=swap_then_write),
            self.assertRaisesRegex(ValueError, "ancestor changed after preview"),
        ):
            remove_adapter(
                brain_path=self.brain,
                installation_id=installed["installation_id"],
            )

        self.assertTrue(swapped)
        self.assertEqual(config.read_text(encoding="utf-8"), '{"victim":true}')
        reviewed = displaced_parent / "hooks.json"
        self.assertEqual(json.loads(reviewed.read_text(encoding="utf-8")), {})

    def test_reinstall_after_removal_is_supported(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        installed = install_adapter(self.plan())
        remove_adapter(
            brain_path=self.brain, installation_id=installed["installation_id"]
        )
        reinstall_plan = self.plan()
        self.assertEqual(reinstall_plan.action, "reinstall")
        reinstalled = install_adapter(reinstall_plan)
        self.assertTrue(reinstalled["installed"])

    def test_remove_rejects_tampered_receipt_target(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        installed = install_adapter(self.plan())
        receipt_path = Path(installed["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        victim = self.base / "victim.json"
        victim.write_text('{"hooks":{}}', encoding="utf-8")
        receipt["config_path"] = str(victim)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "receipt target"):
            remove_adapter(
                brain_path=self.brain, installation_id=installed["installation_id"]
            )
        self.assertEqual(victim.read_text(encoding="utf-8"), '{"hooks":{}}')

    def test_windows_command_rejects_shell_metacharacters(self):
        from rta_brain.capture_adapters import plan_adapter_installation

        unsafe = self.base / "trusted&run-owned" / "rta-brain"
        unsafe.parent.mkdir()
        unsafe.write_text("synthetic executable", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported characters"):
            plan_adapter_installation(
                "cursor",
                scope="project",
                project_root=self.project,
                home=self.home,
                brain_path=self.brain,
                command_parts=(str(unsafe), "capture", "emit", "--adapter", "cursor"),
                platform_name="win32",
            )

    def test_remove_is_idempotent_after_receipted_success(self):
        from rta_brain.capture_adapters import install_adapter, remove_adapter

        installed = install_adapter(self.plan())
        first = remove_adapter(
            brain_path=self.brain,
            installation_id=installed["installation_id"],
        )
        second = remove_adapter(
            brain_path=self.brain,
            installation_id=installed["installation_id"],
        )
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])


if __name__ == "__main__":
    unittest.main()
