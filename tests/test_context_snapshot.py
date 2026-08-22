import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain import db
from rta_brain.agent_profiles import agent_profile_digest, validate_agent_profile
from rta_brain.context_authorization import (
    authorize_task_contract,
    register_agent_profile,
)
from rta_brain.continuity import append_event, init_continuity_schema
from rta_brain.task_contracts import task_contract_digest, validate_task_contract


def _synthetic_assigned_api_key() -> str:
    return "api_" + "key = '" + "sk-" + "abcdefghijklmnopqrstuvwxyz123456" + "'"
from rta_brain.temporal import append_claim

PROFILE_DIGEST = "a" * 64
CONTRACT_DIGEST = "b" * 64


class ContextSnapshotTests(unittest.TestCase):
    def _profile(self, *, privacy="internal"):
        return validate_agent_profile({
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": "snapshot-agent",
            "source": "operator_declared",
            "verification_status": "verified",
            "input_modalities": ["text"],
            "artifact_forms": ["inline_text"],
            "max_input_tokens": 8192,
            "reserved_output_tokens": 1024,
            "host_overhead_tokens": 256,
            "tool_overhead_tokens": 128,
            "tokenizer_family": None,
            "supports": {},
            "max_item_bytes": 262144,
            "max_attachment_bytes": 1048576,
            "privacy_ceiling": privacy,
            "project_scopes": ["demo"],
            "rendering_conventions": ["plain_text"],
            "unsupported_features": [],
        })

    def _contract(
        self,
        *,
        privacy="internal",
        valid_at=None,
        recorded_sequence=None,
        comparison_modes=None,
    ):
        payload = {
            "schema_version": "rta-smriti.task-contract/v1",
            "contract_id": "snapshot-contract",
            "project": "demo",
            "objective": "Compile authorized project context.",
            "task_type": "continuation",
            "risk_class": "consequential",
            "acceptance_criteria": ["Only authorized context reaches the builder."],
            "required_evidence": ["latest checkpoint"],
            "stop_conditions": ["Stop if the state fence changes."],
            "escalation_conditions": [],
            "prohibited_repetition": [],
            "prohibited_actions": ["publish"],
            "scope": {
                "projects": ["demo"], "source_types": [],
                "privacy_ceiling": privacy, "valid_at": valid_at,
                "recorded_sequence": recorded_sequence, "path_globs": [],
            },
            "informational_tool_grants": ["read:context"],
            "agent_profile_id": "snapshot-agent",
            "budgets": {
                "max_input_tokens": 8192, "reserved_output_tokens": 1024,
                "host_overhead_tokens": 256, "tool_overhead_tokens": 128,
                "safety_margin_tokens": 128,
            },
            "compiler_mode": "balanced",
            "created_at": "2026-08-22T00:00:00Z",
            "created_by": {"actor_type": "operator", "actor_id": "owner"},
        }
        if comparison_modes is not None:
            payload["comparison_modes"] = comparison_modes
        return validate_task_contract(payload, authority="operator")

    def _run_authorized(self, connection, **kwargs):
        from rta_brain.context_authorization import issue_task_contract_capability
        from rta_brain.context_snapshot import run_under_compilation_snapshot

        profile = kwargs.pop("profile", self._profile())
        contract = kwargs.pop("contract", self._contract())
        kwargs.pop("profile_digest", None)
        kwargs.pop("contract_digest", None)
        profile_record = register_agent_profile(
            connection,
            project=kwargs["project"],
            profile=profile,
            actor_type="operator",
            actor_id="owner",
        )
        contract_record = authorize_task_contract(
            connection,
            project=kwargs["project"],
            agent_profile_version_id=profile_record["agent_profile_version_id"],
            contract=contract,
            actor_type="operator",
            actor_id="owner",
        )
        authority_secret = b"snapshot-authority-secret-32bytes!"
        issued_at = int(time.time() * 1_000) // 60_000 * 60_000
        capability = issue_task_contract_capability(
            connection,
            project=kwargs["project"],
            task_contract_id=contract_record["task_contract_id"],
            authority_secret=authority_secret,
            grant_id=f"snapshot-compile-grant-{contract_record['task_contract_id']}",
            principal_type="agent",
            principal_id="snapshot-agent",
            session_id="snapshot-session",
            scopes=["compile:context"],
            ttl_seconds=3_600,
            issued_by_id="owner",
            now_epoch_ms=issued_at,
        )
        return run_under_compilation_snapshot(
            connection,
            task_contract_id=contract_record["task_contract_id"],
            capability_token=capability["capability_token"],
            authority_secret=authority_secret,
            principal_type="agent",
            principal_id="snapshot-agent",
            session_id="snapshot-session",
            **kwargs,
        )

    def _git(self, root, *args):
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def _fixture(self, directory):
        root = Path(directory) / "repo"
        root.mkdir()
        self._git(root, "init")
        self._git(root, "config", "user.email", "fixture@example.invalid")
        self._git(root, "config", "user.name", "Fixture")
        tracked = root / "state.txt"
        tracked.write_text("clean\n", encoding="utf-8")
        self._git(root, "add", "state.txt")
        self._git(root, "commit", "-m", "fixture")
        database = Path(directory) / "brain.sqlite"
        conn = db.connect(database)
        project_id = db.ensure_project(conn, "demo", str(root))
        timestamp = "2026-08-22T00:00:00+00:00"
        conn.execute(
            """
            INSERT INTO checkpoints(
                project_id, objective, verified_evidence, remaining_gaps,
                next_action, prohibited_repetition, source, trigger,
                version, created_at, updated_at
            ) VALUES (?, 'Compile safely', 'baseline', '', 'continue', '',
                      'operator', 'manual', 1, ?, ?)
            """,
            (project_id, timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO governance_policies(
                project_id, kind, statement, effect, pramana, confidence,
                provenance_json, overrideable, status, created_at
            ) VALUES (?, 'constraint', 'Stay local', 'block', 'sabda', 1.0,
                      '{}', 0, 'active', ?)
            """,
            (project_id, timestamp),
        )
        conn.execute(
            """
            INSERT INTO sources(
                project_id, kind, path, title, hash, metadata_json,
                created_at, updated_at
            ) VALUES (?, 'file', 'state.txt', 'state.txt', 'source-v1', '{}', ?, ?)
            """,
            (project_id, timestamp, timestamp),
        )
        source_id = conn.execute(
            "SELECT id FROM sources WHERE project_id = ? AND path = 'state.txt'",
            (project_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks(source_id, ordinal, text, hash) VALUES (?, 0, 'clean', 'chunk-v1')",
            (source_id,),
        )
        memory_id = conn.execute(
            """
            INSERT INTO memories(
                project_id, type, pramana, text, confidence, priority,
                status, metadata_json, created_at, updated_at
            ) VALUES (?, 'decision', 'pratyaksha', 'remembered', 1.0, 9,
                      'active', '{}', ?, ?)
            """,
            (project_id, timestamp, timestamp),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO memory_provenance(
                memory_id, source_path, source_hash, command, timestamp,
                verification_status, metadata_json
            ) VALUES (?, 'spec.md', 'memory-v1', 'pytest', ?, 'verified', '{}')
            """,
            (memory_id, timestamp),
        )
        first_entity = conn.execute(
            "INSERT INTO entities(project_id, type, name, canonical_key, created_at) VALUES (?, 'file', 'state.txt', 'file:state.txt', ?)",
            (project_id, timestamp),
        ).lastrowid
        second_entity = conn.execute(
            "INSERT INTO entities(project_id, type, name, canonical_key, created_at) VALUES (?, 'symbol', 'state', 'symbol:state', ?)",
            (project_id, timestamp),
        ).lastrowid
        conn.execute(
            "INSERT INTO edges(project_id, from_entity_id, relation, to_entity_id, source_id, confidence, created_at) VALUES (?, ?, 'defines', ?, ?, 1.0, ?)",
            (project_id, first_entity, second_entity, source_id, timestamp),
        )
        conn.commit()
        append_claim(
            conn,
            project="demo",
            active_root=root,
            subject="Snapshot",
            predicate="status",
            value={"state": "ready"},
            idempotency_key="snapshot-fixture",
            expected_stream_version=0,
            claim_id="claim-one",
            valid_from=timestamp,
            epistemic_state="accepted",
            authority_class="operator_decision",
            verification_status="verified",
            actor_type="operator",
            actor_id="owner",
            source="fixture",
        )
        init_continuity_schema(conn)
        append_event(
            conn,
            "demo",
            "session-1",
            "cursor-1",
            "approval",
            {"decision": "continue"},
            verification_status="verified",
            occurred_at=timestamp,
        )
        conn.execute(
            """
            INSERT INTO work_items(
                project_id, item_type, external_id, qa_state, decision,
                attempt_count, fallback, next_action, metadata_json, updated_at
            ) VALUES (?, 'task', 'wp-03', 'verified', 'pending', 1, '',
                      'continue', '{}', ?)
            """,
            (project_id, timestamp),
        )
        conn.commit()
        return conn, database, root, project_id

    def _append_truth_event(self, writer, _root, project_id):
        append_claim(
            writer,
            project="demo",
            active_root=_root,
            subject="Second snapshot",
            predicate="status",
            value={"state": "changed"},
            idempotency_key="snapshot-fixture-2",
            expected_stream_version=0,
            claim_id="claim-two",
            valid_from="2026-08-22T00:00:01+00:00",
            epistemic_state="observed",
            authority_class="operator",
            verification_status="verified",
            actor_type="operator",
            actor_id="owner",
            source="fixture",
        )

    def test_stable_snapshot_is_digestible_and_verifies(self):
        try:
            from rta_brain.context_snapshot import (
                capture_compilation_snapshot,
                verify_compilation_snapshot,
            )
        except ModuleNotFoundError:
            self.fail("rta_brain.context_snapshot is not implemented")

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            verified = verify_compilation_snapshot(
                conn, snapshot, active_root=root,
                expected_compiler_version=snapshot["compiler"]["compiler_version"],
                expected_profile_digest=PROFILE_DIGEST,
                expected_contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(verified["status"], "stable")
        self.assertEqual(verified["changed"], [])
        self.assertRegex(snapshot["snapshot_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(snapshot["schema_version"], db.SCHEMA_VERSION)
        self.assertEqual(snapshot["project"]["name"], "demo")
        self.assertIn("dirty_digest", snapshot["git"])
        self.assertIn("truth", snapshot["fences"])

    def test_concurrent_mutations_return_state_changed_retry_and_emit_no_result(self):

        mutators = {
            "checkpoint": lambda writer, root, project_id: writer.execute(
                "UPDATE checkpoints SET version = version + 1, updated_at = '2026-08-22T00:00:01+00:00' WHERE project_id = ?",
                (project_id,),
            ),
            "policy": lambda writer, root, project_id: writer.execute(
                "UPDATE governance_policies SET status = 'retired', retired_at = '2026-08-22T00:00:01+00:00' WHERE project_id = ?",
                (project_id,),
            ),
            "truth": self._append_truth_event,
            "binding": lambda writer, root, project_id: writer.execute(
                "UPDATE projects SET checkout_identity = 'checkout-drifted' WHERE id = ?",
                (project_id,),
            ),
            "sources": lambda writer, root, project_id: writer.execute(
                "UPDATE sources SET hash = 'source-v2', updated_at = '2026-08-22T00:00:01+00:00' WHERE project_id = ?",
                (project_id,),
            ),
            "chunks": lambda writer, root, project_id: writer.execute(
                "UPDATE chunks SET text = 'changed-without-hash-change' WHERE source_id IN (SELECT id FROM sources WHERE project_id = ?)",
                (project_id,),
            ),
            "memories": lambda writer, root, project_id: writer.execute(
                "UPDATE memories SET text = 'changed-memory' WHERE project_id = ?",
                (project_id,),
            ),
            "graph": lambda writer, root, project_id: writer.execute(
                "UPDATE edges SET confidence = 0.5 WHERE project_id = ?",
                (project_id,),
            ),
            "continuity": lambda writer, root, project_id: writer.execute(
                "UPDATE session_events SET payload_json = '{\"decision\":\"changed\"}' WHERE project_id = ?",
                (project_id,),
            ),
            "work_state": lambda writer, root, project_id: writer.execute(
                "UPDATE work_items SET next_action = 'changed' WHERE project_id = ?",
                (project_id,),
            ),
            "authorization": lambda writer, root, project_id: writer.execute(
                "UPDATE agent_profiles "
                "SET retired_at = '2026-08-22T00:00:01+00:00' "
                "WHERE project_id = ?",
                (project_id,),
            ),
        }
        for expected_fence, mutator in mutators.items():
            with self.subTest(fence=expected_fence), tempfile.TemporaryDirectory() as tmp:
                conn, database, root, project_id = self._fixture(tmp)
                writer = db.connect(database)

                def build(
                    _reader, _snapshot, *, selected=mutator,
                    selected_writer=writer, selected_root=root,
                    selected_project_id=project_id,
                ):
                    selected(selected_writer, selected_root, selected_project_id)
                    selected_writer.commit()
                    return {"must_not_emit": True}

                result = self._run_authorized(
                    conn,
                    project="demo",
                    active_root=root,
                    builder=build,
                    profile_digest=PROFILE_DIGEST,
                    contract_digest=CONTRACT_DIGEST,
                )
                writer.close()
                conn.close()
                self.assertEqual(result["status"], "state_changed_retry")
                self.assertIn(expected_fence, result["changed"])
                self.assertNotIn("result", result)

    def test_authorized_historical_contract_compiles_historical_truth_version(self):
        from rta_brain.temporal import revise_claim

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            revise_claim(
                conn,
                project="demo",
                active_root=root,
                claim_id="claim-one",
                value={"state": "blocked"},
                idempotency_key="snapshot-fixture:revision",
                expected_stream_version=1,
                valid_from="2026-08-22T00:00:00+00:00",
            )
            observed = {}

            def build(view, _snapshot):
                observed.update(view.context_pack())
                return {"rendered": True}

            result = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=build,
                contract=self._contract(
                    valid_at="2026-08-22T00:30:00+00:00",
                    recorded_sequence=1,
                ),
            )
            conn.close()

        self.assertEqual(result["status"], "stable")
        self.assertIn(
            '"ready"',
            observed["context_text"],
            msg=json.dumps(result["operator_audit"], sort_keys=True),
        )
        self.assertNotIn('"blocked"', observed["context_text"])

    def test_public_capture_and_verify_reject_caller_owned_transactions(self):
        from rta_brain.context_snapshot import (
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            conn.execute("BEGIN")
            try:
                with self.assertRaisesRegex(ValueError, "idle database connection"):
                    capture_compilation_snapshot(
                        conn, project="demo", active_root=root,
                        profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                    )
                with self.assertRaisesRegex(ValueError, "idle database connection"):
                    verify_compilation_snapshot(conn, snapshot, active_root=root)
                self.assertTrue(conn.in_transaction)
            finally:
                conn.rollback()
                conn.close()

    def test_git_mutation_after_snapshot_returns_state_changed_retry(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)

            def build(_reader, _snapshot):
                (root / "state.txt").write_text("dirty\n", encoding="utf-8")
                return {"must_not_emit": True}

            result = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=build,
                profile_digest=PROFILE_DIGEST,
                contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(result["status"], "state_changed_retry")
        self.assertIn("git", result["changed"])
        self.assertNotIn("result", result)

    def test_dirty_content_change_is_detected_when_dirty_file_count_is_unchanged(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            tracked = root / "state.txt"
            tracked.write_text("dirty-one\n", encoding="utf-8")

            def build(_reader, _snapshot):
                tracked.write_text("dirty-two\n", encoding="utf-8")
                return {"must_not_emit": True}

            result = self._run_authorized(
                conn, project="demo", active_root=root, builder=build,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(result["status"], "state_changed_retry")
        self.assertIn("git", result["changed"])

    def test_candidate_builder_cannot_write_or_commit_the_snapshot_connection(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)

            def build(reader, _snapshot):
                reader.execute("UPDATE checkpoints SET objective = 'unsafe'")
                reader.commit()
                return {"unsafe": True}

            before = conn.execute(
                "SELECT objective FROM checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            result = self._run_authorized(
                conn, project="demo", active_root=root, builder=build,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            after = conn.execute(
                "SELECT objective FROM checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(result, {"status": "failed", "error": "candidate_builder_failed"})
        self.assertEqual(before, after)

    def test_hostile_builder_cannot_disable_guards_or_change_pragmas(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            before_version = int(conn.execute("PRAGMA user_version").fetchone()[0])

            def disable_authorizer(reader, _snapshot):
                reader.set_authorizer(None)
                reader.execute("UPDATE checkpoints SET objective = 'unsafe'")

            first = self._run_authorized(
                conn, project="demo", active_root=root, builder=disable_authorizer,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )

            def change_pragma(reader, _snapshot):
                reader.execute("PRAGMA user_version = 123")

            second = self._run_authorized(
                conn, project="demo", active_root=root, builder=change_pragma,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            after_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            objective = conn.execute(
                "SELECT objective FROM checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(first["status"], "failed")
        self.assertEqual(second["status"], "failed")
        self.assertEqual(before_version, after_version)
        self.assertEqual(objective, "Compile safely")

    def test_builder_receives_only_detached_candidates_for_the_selected_project(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            other_root = Path(tmp) / "other-repo"
            other_root.mkdir()
            other_project_id = db.ensure_project(conn, "other", str(other_root))
            conn.execute(
                """
                INSERT INTO memories(
                    project_id, type, pramana, text, confidence, priority,
                    status, metadata_json, created_at, updated_at
                ) VALUES (?, 'decision', 'pratyaksha', 'OTHER-PROJECT-PRIVATE', 1.0, 9,
                          'active', '{}', '2026-08-22T00:00:00+00:00',
                          '2026-08-22T00:00:00+00:00')
                """,
                (other_project_id,),
            )
            conn.commit()

            def build(view, builder_snapshot):
                self.assertFalse(hasattr(view, "execute"))
                self.assertFalse(hasattr(view, "executemany"))
                self.assertNotIn("fences", builder_snapshot)
                self.assertNotIn("git", builder_snapshot)
                payload = view.context_candidates()
                payload["project"] = "forged"
                return payload

            result = self._run_authorized(
                conn, project="demo", active_root=root, builder=build,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(result["status"], "stable")
        serialized = json.dumps(result["result"], sort_keys=True)
        self.assertNotIn("OTHER-PROJECT-PRIVATE", serialized)
        self.assertEqual(result["snapshot"]["project"]["name"], "demo")

    def test_builder_receives_only_contract_filtered_selected_project_candidates(self):

        secret = _synthetic_assigned_api_key()
        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, project_id = self._fixture(tmp)
            conn.execute(
                """
                INSERT INTO memories(
                    project_id, type, pramana, text, confidence, priority,
                    status, metadata_json, created_at, updated_at
                ) VALUES (?, 'decision', 'pratyaksha', ?, 1.0, 9, 'active', '{}',
                          '2026-08-22T00:00:00+00:00', '2026-08-22T00:00:00+00:00')
                """,
                (project_id, secret),
            )
            conn.commit()
            profile = self._profile(privacy="internal")
            contract = self._contract(privacy="internal")
            profile_digest = agent_profile_digest(profile)
            contract_digest = task_contract_digest(contract, authority="operator")

            result = self._run_authorized(
                conn, project="demo", active_root=root,
                builder=lambda view, _snapshot: view.context_candidates(),
                profile_digest=profile_digest, contract_digest=contract_digest,
                profile=profile, contract=contract,
            )
            conn.close()

        self.assertEqual(result["status"], "stable")
        serialized = json.dumps(result["result"], sort_keys=True)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("excluded", result["result"])
        self.assertNotIn("counts", result["result"])
        self.assertEqual(
            result["result"]["schema_version"], "rta-smriti.context-pack/v1"
        )
        self.assertIn("context_text", result["result"])
        self.assertNotIn("receipts", result["result"])
        self.assertNotIn("coverage", result["result"])
        self.assertNotIn("score_micros", serialized)
        self.assertEqual(
            result["operator_audit"]["schema_version"],
            "rta-smriti.context-selection/v1",
        )
        self.assertIn("receipts", result["operator_audit"])

    def test_stable_compilation_persists_one_terminal_metadata_only_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            result = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda view, _snapshot: view.context_candidates(),
            )

            compilation = conn.execute(
                "SELECT * FROM context_compilations"
            ).fetchone()
            receipts = conn.execute(
                "SELECT * FROM context_candidate_receipts ORDER BY candidate_id"
            ).fetchall()
            variant = conn.execute(
                "SELECT * FROM context_pack_variants"
            ).fetchone()
            retained = conn.execute(
                "SELECT COUNT(*) FROM context_retained_payloads"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(result["status"], "stable")
        self.assertEqual(result["compilation_receipt"]["status"], "complete")
        self.assertFalse(result["compilation_receipt"]["idempotent_replay"])
        self.assertEqual(compilation["status"], "complete")
        self.assertEqual(
            compilation["compilation_id"],
            result["compilation_receipt"]["compilation_id"],
        )
        self.assertEqual(
            compilation["receipt_digest"],
            result["compilation_receipt"]["receipt_digest"],
        )
        self.assertEqual(len(receipts), len(result["operator_audit"]["receipts"]))
        self.assertEqual(variant["variant_id"], "primary")
        self.assertEqual(
            variant["pack_digest"], result["result"]["context_pack_digest"]
        )
        self.assertIsNone(variant["bounded_preview"])
        self.assertEqual(retained, 0)
        stored = json.dumps(
            {
                "compilation": dict(compilation),
                "receipts": [dict(row) for row in receipts],
                "variant": dict(variant),
            },
            sort_keys=True,
        )
        self.assertNotIn(result["result"]["context_text"], stored)

    def test_identical_compilation_reuses_verified_receipt_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            first = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            second = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "context_compilations",
                    "context_candidate_receipts",
                    "context_pack_variants",
                )
            }
            conn.close()

        self.assertEqual(first["status"], "stable")
        self.assertEqual(second["status"], "stable")
        self.assertEqual(
            first["compilation_receipt"]["compilation_id"],
            second["compilation_receipt"]["compilation_id"],
        )
        self.assertEqual(
            first["compilation_receipt"]["receipt_digest"],
            second["compilation_receipt"]["receipt_digest"],
        )
        self.assertFalse(first["compilation_receipt"]["idempotent_replay"])
        self.assertTrue(second["compilation_receipt"]["idempotent_replay"])
        self.assertEqual(counts["context_compilations"], 1)
        self.assertEqual(counts["context_pack_variants"], 1)
        self.assertEqual(
            counts["context_candidate_receipts"],
            len(first["operator_audit"]["receipts"]),
        )

    def test_authorized_variants_share_one_snapshot_and_replay_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            builder_calls = 0

            def builder(view, _snapshot):
                nonlocal builder_calls
                builder_calls += 1
                return view.context_candidates()

            contract = self._contract(
                comparison_modes=["minimal", "investigative"]
            )
            first = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=contract,
                builder=builder,
            )
            second = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=contract,
                builder=builder,
            )
            variants = conn.execute(
                """
                SELECT variant_id, mode, pack_digest
                FROM context_pack_variants ORDER BY variant_id
                """
            ).fetchall()
            alternative_receipts = conn.execute(
                "SELECT COUNT(*) FROM context_variant_candidate_receipts"
            ).fetchone()[0]
            receipts_by_variant = {
                row["variant_id"]: row["receipt_count"]
                for row in conn.execute(
                    """
                    SELECT v.variant_id, COUNT(r.id) AS receipt_count
                    FROM context_pack_variants v
                    LEFT JOIN context_variant_candidate_receipts r
                      ON r.pack_variant_id = v.id
                    WHERE v.variant_id != 'primary'
                    GROUP BY v.variant_id
                    """
                )
            }
            conn.close()

        self.assertEqual(builder_calls, 2)
        self.assertEqual(
            set(first["context_variants"]),
            {"primary", "mode:minimal", "mode:investigative"},
        )
        self.assertEqual(
            {row["mode"] for row in variants},
            {"balanced", "minimal", "investigative"},
        )
        self.assertEqual(len({row["pack_digest"] for row in variants}), 3)
        self.assertGreater(alternative_receipts, 0)
        self.assertEqual(
            receipts_by_variant,
            {
                variant_id: len(audit["receipts"])
                for variant_id, audit in first["variant_audits"].items()
            },
        )
        self.assertEqual(
            first["compilation_receipt"]["receipt_digest"],
            second["compilation_receipt"]["receipt_digest"],
        )
        self.assertTrue(second["compilation_receipt"]["idempotent_replay"])

    def test_variant_receipt_boundary_rejects_omitted_tampered_or_unauthorized_packs(self):
        from rta_brain.context_receipts import persist_compilation_receipt
        from rta_brain.context_selection import _digest, build_consumer_context_pack

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            contract = self._contract(comparison_modes=["minimal", "investigative"])
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=contract,
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            compilation = conn.execute(
                """
                SELECT c.task_contract_id, g.id AS authority_grant_id,
                       g.capability_digest
                FROM context_compilations c
                JOIN context_authority_grants g ON g.id = c.authority_grant_id
                WHERE c.compilation_id = ?
                """,
                (compiled["compilation_receipt"]["compilation_id"],),
            ).fetchone()
            authority_grant = {
                "authority_grant_id": int(compilation["authority_grant_id"]),
                "capability_digest": compilation["capability_digest"],
            }
            alternatives = [
                {
                    "variant_id": variant_id,
                    "selection": compiled["variant_audits"][variant_id],
                    "consumer_pack": compiled["context_variants"][variant_id],
                }
                for variant_id in sorted(compiled["variant_audits"])
            ]
            common = {
                "project": "demo",
                "task_contract_id": int(compilation["task_contract_id"]),
                "selection": compiled["operator_audit"],
                "consumer_pack": compiled["context_variants"]["primary"],
                "authority_grant": authority_grant,
            }

            with self.assertRaisesRegex(PermissionError, "do not match their contract"):
                persist_compilation_receipt(
                    conn,
                    **common,
                    alternative_variants=alternatives[:1],
                )

            tampered_pack = json.loads(json.dumps(compiled["context_variants"]["primary"]))
            tampered_pack["context_text"] += "forged"
            with self.assertRaisesRegex(ValueError, "does not match its selection"):
                persist_compilation_receipt(
                    conn,
                    **{**common, "consumer_pack": tampered_pack},
                    alternative_variants=alternatives,
                )

            forged_selection = json.loads(
                json.dumps(compiled["variant_audits"]["mode:minimal"])
            )
            forged_selection["compiler_mode"] = "handoff"
            forged_selection.pop("selection_digest")
            forged_selection["selection_digest"] = _digest(forged_selection)
            forged_pack = build_consumer_context_pack(forged_selection)
            with self.assertRaisesRegex(PermissionError, "do not match their contract"):
                persist_compilation_receipt(
                    conn,
                    **common,
                    alternative_variants=[{
                        "variant_id": "mode:handoff",
                        "selection": forged_selection,
                        "consumer_pack": forged_pack,
                    }],
                )
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "context_compilations",
                    "context_pack_variants",
                    "context_variant_candidate_receipts",
                )
            }
            conn.close()

        self.assertEqual(counts["context_compilations"], 1)
        self.assertEqual(counts["context_pack_variants"], 3)
        self.assertGreater(counts["context_variant_candidate_receipts"], 0)

    def test_outcome_is_idempotent_and_attributes_only_included_receipts(self):
        from rta_brain.context_receipts import record_context_outcome

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=self._contract(comparison_modes=["minimal", "investigative"]),
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            included = next(
                receipt
                for receipt in compiled["operator_audit"]["receipts"]
                if receipt["disposition"] in {"included_mandatory", "included_ranked"}
            )
            kwargs = {
                "project": "demo",
                "compilation_id": compiled["compilation_receipt"]["compilation_id"],
                "outcome_id": "operator-test-outcome",
                "task_status": "success",
                "attribution_level": "correlated",
                "evidence": {"test": "browser acceptance passed"},
                "acceptance_results": {"operator_flow": "passed"},
                "actor_type": "agent",
                "actor_id": "test-agent",
                "attributions": [
                    {
                        "candidate_id": included["candidate_id"],
                        "assessment": "helpful",
                        "attribution_level": "correlated",
                        "evidence": {"reason": "used in the accepted decision"},
                    }
                ],
            }
            first = record_context_outcome(conn, **kwargs)
            second = record_context_outcome(conn, **kwargs)
            counts = {
                "outcomes": conn.execute("SELECT COUNT(*) FROM context_outcomes").fetchone()[0],
                "edges": conn.execute("SELECT COUNT(*) FROM context_attribution_edges").fetchone()[0],
            }
            with self.assertRaisesRegex(ValueError, "different content"):
                record_context_outcome(
                    conn,
                    **{**kwargs, "task_status": "failure"},
                )
            conn.close()

        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["outcome_digest"], second["outcome_digest"])
        self.assertEqual(counts, {"outcomes": 1, "edges": 1})

    def test_outcome_refuses_excluded_receipts_and_self_asserted_operator_authority(self):
        from rta_brain.context_receipts import record_context_outcome

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, project_id = self._fixture(tmp)
            conn.execute(
                """
                INSERT INTO memories(
                    project_id, type, pramana, text, confidence, priority,
                    status, metadata_json, created_at, updated_at
                ) VALUES (?, 'decision', 'pratyaksha', 'restricted fixture', 1.0, 9,
                          'active', '{"privacy_class":"restricted"}',
                          '2026-08-22T00:00:00+00:00',
                          '2026-08-22T00:00:00+00:00')
                """,
                (project_id,),
            )
            conn.commit()
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=self._contract(comparison_modes=["minimal", "investigative"]),
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            excluded = next(
                receipt
                for receipt in compiled["operator_audit"]["receipts"]
                if not receipt["disposition"].startswith("included_")
            )
            common = {
                "project": "demo",
                "compilation_id": compiled["compilation_receipt"]["compilation_id"],
                "task_status": "success",
                "evidence": {"test": "passed"},
                "acceptance_results": {"operator_flow": "passed"},
                "actor_id": "test-agent",
            }
            with self.assertRaisesRegex(PermissionError, "included context"):
                record_context_outcome(
                    conn,
                    **common,
                    outcome_id="excluded-attribution",
                    attribution_level="observed",
                    actor_type="agent",
                    attributions=[
                        {
                            "candidate_id": excluded.get("candidate_id")
                            or f"__pre_score__:{excluded['disposition']}",
                            "assessment": "helpful",
                            "attribution_level": "observed",
                            "evidence": {},
                        }
                    ],
                )
            with self.assertRaisesRegex(PermissionError, "authenticated operator"):
                record_context_outcome(
                    conn,
                    **common,
                    outcome_id="forged-operator-outcome",
                    attribution_level="operator_confirmed",
                    actor_type="operator",
                    attributions=[],
                )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM context_outcomes").fetchone()[0], 0
            )
            conn.close()

    def test_operator_confirmed_outcome_requires_and_records_operator_capability(self):
        from rta_brain.context_authorization import issue_task_contract_capability
        from rta_brain.context_receipts import record_context_outcome

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            compilation = conn.execute(
                """
                SELECT id, task_contract_id
                FROM context_compilations WHERE compilation_id = ?
                """,
                (compiled["compilation_receipt"]["compilation_id"],),
            ).fetchone()
            secret = b"snapshot-authority-secret-32bytes!"
            now_ms = int(time.time() * 1_000)
            confirmation = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=int(compilation["task_contract_id"]),
                authority_secret=secret,
                grant_id="operator-outcome-confirmation",
                principal_type="operator",
                principal_id="owner",
                session_id="operator-session",
                scopes=["confirm:outcome"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=now_ms,
            )
            outcome = record_context_outcome(
                conn,
                project="demo",
                compilation_id=compiled["compilation_receipt"]["compilation_id"],
                outcome_id="confirmed-outcome",
                task_status="success",
                attribution_level="operator_confirmed",
                evidence={"operator_check": "passed"},
                acceptance_results={"operator_flow": "passed"},
                actor_type="operator",
                actor_id="owner",
                attributions=[],
                capability_token=confirmation["capability_token"],
                authority_secret=secret,
                principal_type="operator",
                principal_id="owner",
                session_id="operator-session",
                now_epoch_ms=now_ms + 1,
            )
            stored = conn.execute(
                """
                SELECT authority_grant_id
                FROM context_outcomes WHERE outcome_id = 'confirmed-outcome'
                """
            ).fetchone()
            conn.close()

        self.assertEqual(outcome["authority_grant_id"], confirmation["authority_grant_id"])
        self.assertEqual(int(stored["authority_grant_id"]), confirmation["authority_grant_id"])

    def test_agent_explanation_is_capability_bound_and_hides_excluded_evidence(self):
        from rta_brain.context_authorization import issue_task_contract_capability
        from rta_brain.context_receipts import (
            explain_context_compilation,
            record_context_outcome,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, project_id = self._fixture(tmp)
            conn.execute(
                """
                INSERT INTO memories(
                    project_id, type, pramana, text, confidence, priority,
                    status, metadata_json, created_at, updated_at
                ) VALUES (?, 'decision', 'pratyaksha', 'never reveal this restricted body',
                          1.0, 9, 'active', '{"privacy_class":"restricted"}',
                          '2026-08-22T00:00:00+00:00',
                          '2026-08-22T00:00:00+00:00')
                """,
                (project_id,),
            )
            conn.commit()
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=self._contract(comparison_modes=["minimal", "investigative"]),
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            included = next(
                receipt
                for receipt in compiled["operator_audit"]["receipts"]
                if receipt["disposition"] in {"included_mandatory", "included_ranked"}
            )
            record_context_outcome(
                conn,
                project="demo",
                compilation_id=compiled["compilation_receipt"]["compilation_id"],
                outcome_id="agent-visible-outcome",
                task_status="success",
                attribution_level="correlated",
                evidence={"test": "private operator evidence"},
                acceptance_results={"operator_flow": "passed"},
                actor_type="agent",
                actor_id="snapshot-agent",
                attributions=[{
                    "candidate_id": included["candidate_id"],
                    "assessment": "helpful",
                    "attribution_level": "correlated",
                    "evidence": {"reason": "private attribution evidence"},
                }],
            )
            compilation = conn.execute(
                """
                SELECT task_contract_id FROM context_compilations WHERE compilation_id = ?
                """,
                (compiled["compilation_receipt"]["compilation_id"],),
            ).fetchone()
            secret = b"snapshot-authority-secret-32bytes!"
            now_ms = int(time.time() * 1_000)
            capability = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=int(compilation["task_contract_id"]),
                authority_secret=secret,
                grant_id="agent-explanation",
                principal_type="agent",
                principal_id="snapshot-agent",
                session_id="snapshot-session",
                scopes=["compile:context"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=now_ms,
            )
            explanation = explain_context_compilation(
                conn,
                project="demo",
                compilation_id=compiled["compilation_receipt"]["compilation_id"],
                capability_token=capability["capability_token"],
                authority_secret=secret,
                principal_type="agent",
                principal_id="snapshot-agent",
                session_id="snapshot-session",
                now_epoch_ms=now_ms + 1,
            )
            other_capability = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=int(compilation["task_contract_id"]),
                authority_secret=secret,
                grant_id="other-agent-explanation",
                principal_type="agent",
                principal_id="other-agent",
                session_id="other-session",
                scopes=["compile:context"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=now_ms,
            )
            with self.assertRaisesRegex(PermissionError, "compilation principal"):
                explain_context_compilation(
                    conn,
                    project="demo",
                    compilation_id=compiled["compilation_receipt"]["compilation_id"],
                    capability_token=other_capability["capability_token"],
                    authority_secret=secret,
                    principal_type="agent",
                    principal_id="other-agent",
                    session_id="other-session",
                    now_epoch_ms=now_ms + 1,
                )
            conn.close()

        serialized = json.dumps(explanation, sort_keys=True)
        self.assertEqual(explanation["schema_version"], "rta-smriti.context-explanation/v1")
        self.assertTrue(explanation["receipt_integrity_verified"])
        self.assertTrue(explanation["selection"]["included"])
        self.assertGreater(explanation["selection"]["excluded_count"], 0)
        self.assertEqual(len(explanation["pack_variants"]), 3)
        self.assertTrue(
            all("selection_summary" in variant for variant in explanation["pack_variants"])
        )
        self.assertNotIn("never reveal this restricted body", serialized)
        self.assertNotIn("private operator evidence", serialized)
        self.assertNotIn("private attribution evidence", serialized)
        self.assertNotIn("capability_token", serialized)
        self.assertNotIn("actor_id", serialized)
        self.assertNotIn("variant_candidate_receipts", serialized)

    def test_operator_audit_requires_operator_scope_and_keeps_payloads_out(self):
        from rta_brain.context_authorization import issue_task_contract_capability
        from rta_brain.context_receipts import (
            audit_context_compilation,
            record_context_outcome,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            compiled = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                contract=self._contract(comparison_modes=["minimal", "investigative"]),
                builder=lambda view, _snapshot: view.context_candidates(),
            )
            record_context_outcome(
                conn,
                project="demo",
                compilation_id=compiled["compilation_receipt"]["compilation_id"],
                outcome_id="operator-audit-outcome",
                task_status="partial_success",
                attribution_level="correlated",
                evidence={"operator_note": "full audit evidence"},
                acceptance_results={"browser_flow": "passed"},
                actor_type="agent",
                actor_id="snapshot-agent",
                attributions=[],
            )
            compilation = conn.execute(
                """
                SELECT task_contract_id FROM context_compilations WHERE compilation_id = ?
                """,
                (compiled["compilation_receipt"]["compilation_id"],),
            ).fetchone()
            secret = b"snapshot-authority-secret-32bytes!"
            now_ms = int(time.time() * 1_000)
            audit_capability = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=int(compilation["task_contract_id"]),
                authority_secret=secret,
                grant_id="operator-audit",
                principal_type="operator",
                principal_id="owner",
                session_id="operator-session",
                scopes=["audit:context"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=now_ms,
            )
            audit = audit_context_compilation(
                conn,
                project="demo",
                compilation_id=compiled["compilation_receipt"]["compilation_id"],
                capability_token=audit_capability["capability_token"],
                authority_secret=secret,
                principal_type="operator",
                principal_id="owner",
                session_id="operator-session",
                now_epoch_ms=now_ms + 1,
            )
            conn.close()

        serialized = json.dumps(audit, sort_keys=True)
        self.assertTrue(audit["receipt_integrity_verified"])
        self.assertEqual(audit["outcomes"][0]["evidence"]["operator_note"], "full audit evidence")
        self.assertTrue(audit["candidate_receipts"])
        self.assertEqual(
            {item["variant_id"] for item in audit["variant_candidate_receipts"]},
            {"mode:minimal", "mode:investigative"},
        )
        self.assertTrue(
            all(item["receipts"] for item in audit["variant_candidate_receipts"])
        )
        self.assertNotIn("capability_token", serialized)
        self.assertNotIn("payload_text", serialized)
        self.assertNotIn("bounded_preview", serialized)

    def test_snapshot_fences_staged_index_content(self):
        from rta_brain.context_snapshot import capture_compilation_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            tracked = root / "state.txt"
            tracked.write_text("stage-one\n", encoding="utf-8")
            self._git(root, "add", "state.txt")
            tracked.write_text("work-tree\n", encoding="utf-8")
            before_stat = tracked.stat()
            first = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )

            tracked.write_text("stage-two\n", encoding="utf-8")
            self._git(root, "add", "state.txt")
            tracked.write_text("work-tree\n", encoding="utf-8")
            os.utime(
                tracked,
                ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns),
            )
            second = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertNotEqual(first["git"]["index_digest"], second["git"]["index_digest"])
        self.assertNotEqual(first["snapshot_digest"], second["snapshot_digest"])

    def test_builder_failure_rolls_back_reader_and_surfaces_bounded_error(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)

            def build(_reader, _snapshot):
                raise ValueError("private payload must not be reflected")

            result = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=build,
                profile_digest=PROFILE_DIGEST,
                contract_digest=CONTRACT_DIGEST,
            )
            self.assertFalse(conn.in_transaction)
            conn.close()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "candidate_builder_failed")
        self.assertNotIn("private payload", str(result))

    def test_builder_runs_after_the_snapshot_reader_is_closed(self):
        from rta_brain.context_snapshot import _open_read_only_compilation_connection

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            reader = _open_read_only_compilation_connection(conn)

            class ObservedReader:
                closed = False

                def close(self):
                    self.closed = True
                    return reader.close()

                def __getattr__(self, name):
                    return getattr(reader, name)

            observed = ObservedReader()

            def build(_view, _snapshot):
                self.assertTrue(observed.closed)
                return {"compiled": True}

            with patch(
                "rta_brain.context_snapshot._open_read_only_compilation_connection",
                return_value=observed,
            ):
                result = self._run_authorized(
                    conn,
                    project="demo",
                    active_root=root,
                    builder=build,
                )
            conn.close()

        self.assertEqual(result["status"], "stable")

    def test_builder_result_must_be_bounded_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            unserializable = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda _view, _snapshot: object(),
            )
            oversized = self._run_authorized(
                conn,
                project="demo",
                active_root=root,
                builder=lambda _view, _snapshot: {"payload": "x" * (8 * 1024 * 1024)},
            )
            receipt_count = conn.execute(
                "SELECT COUNT(*) FROM context_compilations"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(
            unserializable, {"status": "failed", "error": "candidate_builder_failed"}
        )
        self.assertEqual(
            oversized, {"status": "failed", "error": "candidate_builder_failed"}
        )
        self.assertEqual(receipt_count, 0)

    def test_snapshot_binds_compiler_profile_contract_and_binding_revision(self):
        from rta_brain.context_snapshot import (
            _snapshot_digest,
            capture_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, database, root, project_id = self._fixture(tmp)
            first = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                compiler_version="compiler-v1", profile_digest=PROFILE_DIGEST,
                contract_digest=CONTRACT_DIGEST,
            )
            second = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                compiler_version="compiler-v2", profile_digest="a" * 64,
                contract_digest="b" * 64,
            )
            self.assertNotEqual(first["snapshot_digest"], second["snapshot_digest"])
            self.assertEqual(first["compiler"]["profile_digest"], "a" * 64)

            writer = db.connect(database)

            def build(_reader, _snapshot):
                writer.execute(
                    """
                    INSERT INTO project_root_migrations(
                        project_id, previous_root_fingerprint, new_root_fingerprint,
                        previous_checkout_fingerprint, new_checkout_fingerprint,
                        status, created_at
                    ) VALUES (?, 'a', 'b', 'c', 'd', 'completed',
                              '2026-08-22T00:00:01+00:00')
                    """,
                    (project_id,),
                )
                writer.commit()
                return {"must_not_emit": True}

            changed = self._run_authorized(
                conn, project="demo", active_root=root, builder=build,
                compiler_version="compiler-v1", profile_digest="a" * 64,
                contract_digest="b" * 64,
            )
            changed_receipts = conn.execute(
                "SELECT COUNT(*) FROM context_compilations"
            ).fetchone()[0]
            writer.close()

            def forge_builder_snapshot(_reader, exposed_snapshot):
                exposed_snapshot["compiler"]["profile_digest"] = "f" * 64
                exposed_snapshot["snapshot_digest"] = _snapshot_digest(exposed_snapshot)
                return {"attempted": "forge"}

            forged = self._run_authorized(
                conn, project="demo", active_root=root, builder=forge_builder_snapshot,
                compiler_version="compiler-v1", profile_digest=PROFILE_DIGEST,
                contract_digest=CONTRACT_DIGEST,
            )
            normalized_compiler = self._run_authorized(
                conn, project="demo", active_root=root,
                builder=lambda _reader, _snapshot: {"compiled": True},
                compiler_version=" compiler-v1 ", profile_digest=PROFILE_DIGEST,
                contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(changed["status"], "state_changed_retry")
        self.assertIn("binding", changed["changed"])
        self.assertEqual(changed_receipts, 0)
        self.assertEqual(forged["status"], "stable")
        self.assertEqual(
            forged["snapshot"]["compiler"]["profile_digest"],
            agent_profile_digest(self._profile()),
        )
        self.assertEqual(normalized_compiler["status"], "stable")
        self.assertEqual(
            normalized_compiler["snapshot"]["compiler"]["compiler_version"],
            "compiler-v1",
        )

    def test_compilation_run_requires_persisted_task_contract(self):
        from rta_brain.context_snapshot import (
            capture_compilation_snapshot,
            run_under_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            with self.assertRaisesRegex(ValueError, "task_contract_id"):
                run_under_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    builder=lambda _reader, _snapshot: {},
                )
            with self.assertRaisesRegex(ValueError, "profile_digest and contract_digest"):
                capture_compilation_snapshot(conn, project="demo", active_root=root)
            conn.close()

    def test_compilation_rejects_unknown_authorization_without_invoking_builder(self):
        from rta_brain.context_snapshot import run_under_compilation_snapshot

        called = False

        def builder(_view, _snapshot):
            nonlocal called
            called = True
            return {"claimed_compiled": True}

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            result = run_under_compilation_snapshot(
                conn, project="demo", active_root=root, builder=builder,
                task_contract_id=9_999_999,
            )
            conn.close()

        self.assertEqual(result["status"], "authorization_required")
        self.assertFalse(called)
        self.assertNotIn("result", result)

    def test_forged_snapshot_digest_is_rejected(self):
        from rta_brain.context_snapshot import (
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            forged = dict(snapshot)
            forged["snapshot_digest"] = "0" * 64
            result = verify_compilation_snapshot(conn, forged, active_root=root)
            conn.close()

        self.assertEqual(result["status"], "state_changed_retry")
        self.assertIn("snapshot_integrity", result["changed"])

    def test_hash_valid_malformed_snapshot_shape_is_bounded(self):
        from rta_brain.context_snapshot import (
            _snapshot_digest,
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            malformed = json.loads(json.dumps(snapshot))
            malformed["compiler"] = "not-an-object"
            malformed["snapshot_digest"] = _snapshot_digest(malformed)
            result = verify_compilation_snapshot(
                conn, malformed, active_root=root,
                expected_compiler_version=snapshot["compiler"]["compiler_version"],
                expected_profile_digest=PROFILE_DIGEST,
                expected_contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertEqual(result["status"], "state_changed_retry")
        self.assertIn("snapshot_integrity", result["changed"])

    def test_hash_valid_snapshot_rejects_unknown_top_level_or_nested_fields(self):
        from rta_brain.context_snapshot import (
            _snapshot_digest,
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            for location in ("top", "project"):
                with self.subTest(location=location):
                    malformed = json.loads(json.dumps(snapshot))
                    target = malformed if location == "top" else malformed["project"]
                    target["private_payload"] = "must-not-be-accepted"
                    malformed["snapshot_digest"] = _snapshot_digest(malformed)
                    result = verify_compilation_snapshot(
                        conn, malformed, active_root=root,
                        expected_compiler_version=snapshot["compiler"]["compiler_version"],
                        expected_profile_digest=PROFILE_DIGEST,
                        expected_contract_digest=CONTRACT_DIGEST,
                    )
                    self.assertEqual(result["status"], "state_changed_retry")
                    self.assertIn("snapshot_integrity", result["changed"])
            conn.close()

    def test_hash_valid_snapshot_rejects_scalar_type_substitutions(self):
        from rta_brain.context_snapshot import (
            _snapshot_digest,
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            mutations = (
                ("project.id", lambda value: value["project"].__setitem__("id", 1.0)),
                (
                    "project.binding_valid",
                    lambda value: value["project"].__setitem__("binding_valid", 1),
                ),
                (
                    "git.is_git_repo",
                    lambda value: value["git"].__setitem__("is_git_repo", 1),
                ),
                (
                    "fence.count",
                    lambda value: value["fences"]["sources"].__setitem__("count", True),
                ),
            )
            for label, mutate in mutations:
                with self.subTest(field=label):
                    malformed = json.loads(json.dumps(snapshot))
                    mutate(malformed)
                    malformed["snapshot_digest"] = _snapshot_digest(malformed)
                    result = verify_compilation_snapshot(
                        conn, malformed, active_root=root,
                        expected_compiler_version=snapshot["compiler"]["compiler_version"],
                        expected_profile_digest=PROFILE_DIGEST,
                        expected_contract_digest=CONTRACT_DIGEST,
                    )
                    self.assertEqual(result["status"], "state_changed_retry")
                    self.assertIn("snapshot_integrity", result["changed"])
            conn.close()

    def test_bound_snapshot_requires_trusted_expected_bindings_and_normalizes_digests(self):
        from rta_brain.context_snapshot import (
            _snapshot_digest,
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root, compiler_version="compiler-v1",
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            forged = json.loads(json.dumps(snapshot))
            forged["compiler"]["profile_digest"] = "f" * 64
            forged["snapshot_digest"] = _snapshot_digest(forged)
            unbound = verify_compilation_snapshot(conn, forged, active_root=root)
            null_bound = json.loads(json.dumps(snapshot))
            null_bound["compiler"]["profile_digest"] = None
            null_bound["compiler"]["contract_digest"] = None
            null_bound["snapshot_digest"] = _snapshot_digest(null_bound)
            null_downgrade = verify_compilation_snapshot(
                conn, null_bound, active_root=root,
            )
            verified = verify_compilation_snapshot(
                conn, snapshot, active_root=root,
                expected_compiler_version="compiler-v1",
                expected_profile_digest=PROFILE_DIGEST.upper(),
                expected_contract_digest=CONTRACT_DIGEST.upper(),
            )
            conn.close()

        self.assertEqual(unbound["status"], "state_changed_retry")
        self.assertIn("compiler_binding", unbound["changed"])
        self.assertEqual(null_downgrade["status"], "state_changed_retry")
        self.assertIn("snapshot_integrity", null_downgrade["changed"])
        self.assertEqual(verified["status"], "stable")

    def test_base_exception_rolls_back_snapshot_transaction_before_propagating(self):

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)

            def interrupted(_reader, _snapshot):
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                self._run_authorized(
                    conn, project="demo", active_root=root, builder=interrupted,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            self.assertFalse(conn.in_transaction)
            conn.close()

    def test_verifier_base_exception_rolls_back_transaction_before_propagating(self):
        from rta_brain.context_snapshot import (
            capture_compilation_snapshot,
            verify_compilation_snapshot,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            snapshot = capture_compilation_snapshot(
                conn, project="demo", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            with (
                patch(
                    "rta_brain.context_snapshot._capture_compilation_snapshot",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                verify_compilation_snapshot(
                    conn, snapshot, active_root=root,
                    expected_compiler_version=snapshot["compiler"]["compiler_version"],
                    expected_profile_digest=PROFILE_DIGEST,
                    expected_contract_digest=CONTRACT_DIGEST,
                )
            self.assertFalse(conn.in_transaction)
            conn.close()

    def test_non_git_project_has_a_deterministic_explicit_fence(self):
        from rta_brain.context_snapshot import capture_compilation_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "plain-project"
            root.mkdir()
            conn = db.connect(Path(tmp) / "plain.sqlite")
            db.init_project(conn, "plain", str(root))
            first = capture_compilation_snapshot(
                conn, project="plain", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            second = capture_compilation_snapshot(
                conn, project="plain", active_root=root,
                profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
            )
            conn.close()

        self.assertFalse(first["git"]["is_git_repo"])
        self.assertEqual(first["git"], second["git"])

    def test_mixed_schema_workspace_members_are_read_only_and_isolated(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            before = {}
            for version in (8, db.SCHEMA_VERSION + 10):
                path = Path(tmp) / f"member-{version}.sqlite"
                conn = sqlite3.connect(path)
                conn.execute("CREATE TABLE sentinel(value TEXT)")
                conn.execute("INSERT INTO sentinel(value) VALUES ('unchanged')")
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
                conn.close()
                paths.append({"project": f"member-{version}", "db_path": str(path)})
                before[str(path)] = path.read_bytes()

            result = inspect_workspace_members_read_only(paths)

            for item in paths:
                self.assertEqual(Path(item["db_path"]).read_bytes(), before[item["db_path"]])

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(len(result["members"]), 2)
        for member in result["members"]:
            self.assertEqual(member["status"], "isolated_schema_mismatch")
            self.assertTrue(member["read_only"])
            self.assertFalse(member["eligible"])

    def test_workspace_member_limit_stops_consuming_the_iterable_at_cap_plus_one(self):
        from rta_brain.context_snapshot import (
            MAX_WORKSPACE_MEMBERS,
            inspect_workspace_members_read_only,
        )

        consumed = 0

        def members():
            nonlocal consumed
            while True:
                consumed += 1
                yield {"project": f"member-{consumed}", "db_path": "unused.sqlite"}

        with self.assertRaisesRegex(ValueError, "workspace exceeds"):
            inspect_workspace_members_read_only(members())

        self.assertEqual(consumed, MAX_WORKSPACE_MEMBERS + 1)

    def test_attached_or_shadowed_schema_is_rejected_without_mutation(self):
        from rta_brain.context_snapshot import capture_compilation_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            attached = Path(tmp) / "attached.sqlite"
            sqlite3.connect(attached).close()
            conn.execute("ATTACH DATABASE ? AS foreign_brain", (str(attached),))
            with self.assertRaisesRegex(ValueError, "attached databases"):
                capture_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            conn.execute("DETACH DATABASE foreign_brain")

            conn.execute("CREATE TEMP TABLE sources(id INTEGER)")
            with self.assertRaisesRegex(ValueError, "shadow"):
                capture_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            conn.close()

    def test_oversized_dirty_files_fail_closed_instead_of_metadata_only_fencing(self):
        from rta_brain.context_snapshot import capture_compilation_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            (root / "state.txt").write_text("x" * 128, encoding="utf-8")
            with (
                patch("rta_brain.context_snapshot.MAX_DIRTY_FILE_BYTES", 64),
                self.assertRaisesRegex(ValueError, "dirty file exceeds"),
            ):
                capture_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            conn.close()

    def test_snapshot_fence_fails_closed_at_aggregate_byte_limit(self):
        from rta_brain.context_snapshot import capture_compilation_snapshot

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            with (
                patch("rta_brain.context_snapshot.MAX_FENCE_BYTES", 1),
                self.assertRaisesRegex(ValueError, "snapshot byte limit"),
            ):
                capture_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            conn.close()

    def test_git_status_and_index_entries_share_snapshot_resource_budget(self):
        from rta_brain.context_snapshot import (
            _AggregateBudget,
            _git_fence,
            capture_compilation_snapshot,
        )

        def fake_git(_root, *args, **_kwargs):
            if args[0] == "status":
                stdout = "?? first.txt\0?? second.txt\0"
            elif args[0] == "rev-parse":
                stdout = "a" * 40
            else:
                stdout = "100644 a first.txt\0" "100644 b second.txt\0"
            return subprocess.CompletedProcess(args, 0, stdout, "")

        state = {
            "is_git_repo": True,
            "repository_root": "repo",
            "branch": "main",
            "dirty_files": 2,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first.txt").write_text("", encoding="utf-8")
            (root / "second.txt").write_text("", encoding="utf-8")
            with (
                patch(
                    "rta_brain.context_snapshot.repository_state", return_value=state,
                ) as state_mock,
                patch("rta_brain.context_snapshot.run_git_inspection", side_effect=fake_git),
                patch("rta_brain.context_snapshot.MAX_FENCE_ROWS", 2),
                self.assertRaisesRegex(ValueError, "aggregate row limit"),
            ):
                _git_fence(root, _AggregateBudget())
            state_mock.assert_called_once_with(root, include_worktree=False)

        with tempfile.TemporaryDirectory() as tmp:
            conn, _database, root, _project_id = self._fixture(tmp)
            with (
                patch("rta_brain.context_snapshot.MAX_FENCE_ROWS", 1),
                self.assertRaisesRegex(ValueError, "aggregate row limit"),
            ):
                capture_compilation_snapshot(
                    conn, project="demo", active_root=root,
                    profile_digest=PROFILE_DIGEST, contract_digest=CONTRACT_DIGEST,
                )
            conn.close()

    def test_git_dirty_fence_rejects_paths_outside_repository_root(self):
        from rta_brain.context_snapshot import _AggregateBudget, _git_fence

        def fake_git(_root, *args, **_kwargs):
            if args[0] == "status":
                stdout = "?? ../outside.txt\0"
            elif args[0] == "rev-parse":
                stdout = "a" * 40
            else:
                stdout = ""
            return subprocess.CompletedProcess(args, 0, stdout, "")

        state = {
            "is_git_repo": True,
            "repository_root": "repo",
            "branch": "main",
            "dirty_files": 1,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (Path(tmp) / "outside.txt").write_text("private", encoding="utf-8")
            with (
                patch("rta_brain.context_snapshot.repository_state", return_value=state),
                patch("rta_brain.context_snapshot.run_git_inspection", side_effect=fake_git),
                self.assertRaisesRegex(ValueError, "outside repository root"),
            ):
                _git_fence(root, _AggregateBudget())

    def test_fabricated_current_schema_workspace_member_is_isolated(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fabricated.sqlite"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE projects(name TEXT)")
            conn.execute("INSERT INTO projects(name) VALUES ('demo')")
            conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
            conn.commit()
            conn.close()
            before = path.read_bytes()

            result = inspect_workspace_members_read_only([
                {"project": "demo", "db_path": str(path)},
            ])

            self.assertEqual(path.read_bytes(), before)

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["members"][0]["status"], "isolated_schema_mismatch")
        self.assertFalse(result["members"][0]["eligible"])

    def test_workspace_member_missing_compiler_dependency_is_isolated(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            path = Path(tmp) / "member.sqlite"
            conn = db.connect(path)
            db.init_project(conn, "demo", str(root))
            conn.execute("DROP TABLE memory_provenance")
            conn.commit()
            conn.close()

            result = inspect_workspace_members_read_only([
                {"project": "demo", "db_path": str(path)},
            ])

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["members"][0]["status"], "isolated_schema_mismatch")

    def test_workspace_member_missing_truth_or_binding_dependency_is_isolated(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        for missing_table in ("truth_projection_state", "project_root_migrations"):
            with self.subTest(table=missing_table), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                root.mkdir()
                path = Path(tmp) / "member.sqlite"
                conn = db.connect(path)
                db.init_project(conn, "demo", str(root))
                conn.execute(f"DROP TABLE {missing_table}")
                conn.commit()
                conn.close()

                result = inspect_workspace_members_read_only([
                    {"project": "demo", "db_path": str(path)},
                ])

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(
                result["members"][0]["status"], "isolated_schema_mismatch",
            )

    def test_workspace_member_missing_compiler_column_is_isolated(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        for missing_column in ("subject_display", "provenance_json"):
            with self.subTest(column=missing_column), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                root.mkdir()
                path = Path(tmp) / "member.sqlite"
                conn = db.connect(path)
                db.init_project(conn, "demo", str(root))
                conn.execute(
                    f"ALTER TABLE truth_claim_versions DROP COLUMN {missing_column}"
                )
                conn.commit()
                conn.close()

                result = inspect_workspace_members_read_only([
                    {"project": "demo", "db_path": str(path)},
                ])

            self.assertEqual(result["status"], "degraded")
            self.assertEqual(
                result["members"][0]["status"], "isolated_schema_mismatch",
            )

    def test_workspace_schema_and_binding_reads_share_one_snapshot_transaction(self):
        from rta_brain.context_snapshot import (
            _validate_read_schema,
            inspect_workspace_members_read_only,
        )

        observed_transactions = []

        def validate_inside_snapshot(connection):
            observed_transactions.append(connection.in_transaction)
            return _validate_read_schema(connection)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            path = Path(tmp) / "member.sqlite"
            conn = db.connect(path)
            db.init_project(conn, "demo", str(root))
            conn.close()
            with patch(
                "rta_brain.context_snapshot._validate_read_schema",
                side_effect=validate_inside_snapshot,
            ):
                result = inspect_workspace_members_read_only([
                    {"project": "demo", "db_path": str(path)},
                ])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(observed_transactions, [True])

    def test_malformed_workspace_descriptor_is_isolated_without_aborting_batch(self):
        from rta_brain.context_snapshot import inspect_workspace_members_read_only

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            path = Path(tmp) / "member.sqlite"
            conn = db.connect(path)
            db.init_project(conn, "demo", str(root))
            conn.close()

            result = inspect_workspace_members_read_only([
                {"project": "demo", "db_path": str(path)},
                None,
            ])

        self.assertEqual(result["status"], "degraded")
        self.assertTrue(result["members"][0]["eligible"])
        self.assertEqual(result["members"][1]["status"], "isolated_unavailable")
        self.assertFalse(result["members"][1]["eligible"])


if __name__ == "__main__":
    unittest.main()
