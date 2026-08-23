import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rta_brain import db
from rta_brain.agent_profiles import validate_agent_profile
from rta_brain.task_contracts import validate_task_contract


class ContextAuthorizationTests(unittest.TestCase):
    def _profile(self):
        return validate_agent_profile({
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": "authorized-agent",
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
            "privacy_ceiling": "internal",
            "project_scopes": ["demo"],
            "rendering_conventions": ["plain_text"],
            "unsupported_features": [],
        })

    def _contract(self):
        return validate_task_contract({
            "schema_version": "rta-smriti.task-contract/v1",
            "contract_id": "authorized-contract",
            "project": "demo",
            "objective": "Compile only persisted authorized context.",
            "task_type": "continuation",
            "risk_class": "consequential",
            "acceptance_criteria": ["Use only authorized context."],
            "required_evidence": ["latest checkpoint"],
            "stop_conditions": ["Stop if the state fence changes."],
            "escalation_conditions": [],
            "prohibited_repetition": [],
            "prohibited_actions": ["publish"],
            "scope": {
                "projects": ["demo"],
                "source_types": [],
                "privacy_ceiling": "internal",
                "valid_at": None,
                "recorded_sequence": None,
                "path_globs": [],
            },
            "informational_tool_grants": ["read:context"],
            "agent_profile_id": "authorized-agent",
            "budgets": {
                "max_input_tokens": 8192,
                "reserved_output_tokens": 1024,
                "host_overhead_tokens": 256,
                "tool_overhead_tokens": 128,
                "safety_margin_tokens": 128,
            },
            "compiler_mode": "balanced",
            "created_at": "2026-08-22T00:00:00Z",
            "created_by": {"actor_type": "operator", "actor_id": "owner"},
        }, authority="operator")

    def _fixture(self, directory):
        root = Path(directory) / "repo"
        root.mkdir()
        conn = db.connect(Path(directory) / "brain.sqlite")
        db.ensure_project(conn, "demo", str(root))
        return conn

    def _authorized_contract(self, conn):
        from rta_brain.context_authorization import (
            authorize_task_contract,
            register_agent_profile,
        )

        profile = register_agent_profile(
            conn,
            project="demo",
            profile=self._profile(),
            actor_type="operator",
            actor_id="owner",
        )
        return authorize_task_contract(
            conn,
            project="demo",
            agent_profile_version_id=profile["agent_profile_version_id"],
            contract=self._contract(),
            actor_type="operator",
            actor_id="owner",
        )

    def test_host_capability_is_project_contract_principal_session_and_scope_bound(self):
        from rta_brain.context_authorization import (
            issue_task_contract_capability,
            load_authorized_context,
        )

        secret = b"authority-secret-for-tests-32bytes!"
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            db.ensure_project(conn, "other", str(Path(tmp) / "other"))
            contract = self._authorized_contract(conn)
            issued = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=contract["task_contract_id"],
                authority_secret=secret,
                grant_id="grant-session-a",
                principal_type="agent",
                principal_id="codex",
                session_id="session-a",
                scopes=["compile:context"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=1_000_000,
            )
            loaded = load_authorized_context(
                conn,
                project="demo",
                task_contract_id=contract["task_contract_id"],
                capability_token=issued["capability_token"],
                authority_secret=secret,
                principal_type="agent",
                principal_id="codex",
                session_id="session-a",
                required_scope="compile:context",
                now_epoch_ms=1_000_001,
            )
            for mutation, message in (
                ({"project": "other"}, "project"),
                ({"authority_secret": b"wrong-secret-that-is-at-least-32bytes"}, "signature"),
                ({"principal_id": "claude"}, "principal"),
                ({"session_id": "session-b"}, "session"),
                ({"required_scope": "confirm:outcome"}, "scope"),
            ):
                kwargs = {
                    "project": "demo",
                    "task_contract_id": contract["task_contract_id"],
                    "capability_token": issued["capability_token"],
                    "authority_secret": secret,
                    "principal_type": "agent",
                    "principal_id": "codex",
                    "session_id": "session-a",
                    "required_scope": "compile:context",
                    "now_epoch_ms": 1_000_001,
                    **mutation,
                }
                with self.subTest(mutation=mutation), self.assertRaisesRegex(
                    PermissionError, message
                ):
                    load_authorized_context(conn, **kwargs)
            conn.close()

        self.assertEqual(loaded["authority_grant"]["grant_id"], "grant-session-a")
        self.assertEqual(loaded["authority_grant"]["principal_id"], "codex")
        self.assertNotIn("capability_token", loaded)

    def test_capability_expires_and_append_only_revocation_takes_effect(self):
        from rta_brain.context_authorization import (
            issue_task_contract_capability,
            load_authorized_context,
            revoke_task_contract_capability,
        )

        secret = b"authority-secret-for-tests-32bytes!"
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            contract = self._authorized_contract(conn)
            issued = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=contract["task_contract_id"],
                authority_secret=secret,
                grant_id="short-lived",
                principal_type="agent",
                principal_id="codex",
                session_id="session-a",
                scopes=["compile:context"],
                ttl_seconds=1,
                issued_by_id="owner",
                now_epoch_ms=2_000_000,
            )
            common = {
                "project": "demo",
                "task_contract_id": contract["task_contract_id"],
                "capability_token": issued["capability_token"],
                "authority_secret": secret,
                "principal_type": "agent",
                "principal_id": "codex",
                "session_id": "session-a",
                "required_scope": "compile:context",
            }
            load_authorized_context(conn, **common, now_epoch_ms=2_000_999)
            with self.assertRaisesRegex(PermissionError, "expired"):
                load_authorized_context(conn, **common, now_epoch_ms=2_001_000)

            second = issue_task_contract_capability(
                conn,
                project="demo",
                task_contract_id=contract["task_contract_id"],
                authority_secret=secret,
                grant_id="revoked-grant",
                principal_type="agent",
                principal_id="codex",
                session_id="session-a",
                scopes=["compile:context"],
                ttl_seconds=300,
                issued_by_id="owner",
                now_epoch_ms=3_000_000,
            )
            revoke_task_contract_capability(
                conn,
                project="demo",
                grant_id="revoked-grant",
                authority_secret=secret,
                revoked_by_id="owner",
                reason="task ended",
                now_epoch_ms=3_000_100,
            )
            with self.assertRaisesRegex(PermissionError, "revoked"):
                load_authorized_context(
                    conn,
                    **{**common, "capability_token": second["capability_token"]},
                    now_epoch_ms=3_000_101,
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE context_authority_grants SET grant_id = 'changed'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM context_authority_revocations")
            conn.close()

    def test_capability_issuance_is_idempotent_and_detects_request_reuse(self):
        from rta_brain.context_authorization import issue_task_contract_capability

        secret = b"authority-secret-for-tests-32bytes!"
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            contract = self._authorized_contract(conn)
            kwargs = {
                "project": "demo",
                "task_contract_id": contract["task_contract_id"],
                "authority_secret": secret,
                "grant_id": "idempotent-grant",
                "principal_type": "agent",
                "principal_id": "codex",
                "session_id": "session-a",
                "scopes": ["compile:context"],
                "ttl_seconds": 300,
                "issued_by_id": "owner",
                "now_epoch_ms": 4_000_000,
            }
            first = issue_task_contract_capability(conn, **kwargs)
            replay = issue_task_contract_capability(conn, **kwargs)
            with self.assertRaisesRegex(ValueError, "different capability"):
                issue_task_contract_capability(
                    conn, **{**kwargs, "principal_id": "claude"}
                )
            count = conn.execute(
                "SELECT COUNT(*) FROM context_authority_grants"
            ).fetchone()[0]
            conn.close()

        self.assertEqual(first["capability_token"], replay["capability_token"])
        self.assertEqual(first["capability_digest"], replay["capability_digest"])
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(count, 1)

    def test_outcome_confirmation_scope_requires_an_operator_principal(self):
        from rta_brain.context_authorization import issue_task_contract_capability

        secret = b"authority-secret-for-tests-32bytes!"
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            contract = self._authorized_contract(conn)
            common = {
                "project": "demo",
                "task_contract_id": contract["task_contract_id"],
                "authority_secret": secret,
                "session_id": "operator-session",
                "scopes": ["confirm:outcome"],
                "ttl_seconds": 300,
                "issued_by_id": "owner",
                "now_epoch_ms": 5_000_000,
            }
            with self.assertRaisesRegex(PermissionError, "operator principal"):
                issue_task_contract_capability(
                    conn,
                    **common,
                    grant_id="agent-confirmation",
                    principal_type="agent",
                    principal_id="codex",
                )
            with self.assertRaisesRegex(PermissionError, "operator principal"):
                issue_task_contract_capability(
                    conn,
                    **{**common, "scopes": ["audit:context"]},
                    grant_id="agent-audit",
                    principal_type="agent",
                    principal_id="codex",
                )
            confirmation = issue_task_contract_capability(
                conn,
                **common,
                grant_id="operator-confirmation",
                principal_type="operator",
                principal_id="owner",
            )
            conn.close()

        self.assertEqual(confirmation["grant_id"], "operator-confirmation")
        self.assertNotEqual(confirmation["capability_token"], secret.decode("utf-8"))

    def test_persisted_authorization_round_trips_and_is_idempotent(self):
        from rta_brain.context_authorization import (
            authorize_task_contract,
            load_authorized_context,
            register_agent_profile,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            profile = register_agent_profile(
                conn,
                project="demo",
                profile=self._profile(),
                actor_type="operator",
                actor_id="owner",
            )
            replay = register_agent_profile(
                conn,
                project="demo",
                profile=self._profile(),
                actor_type="operator",
                actor_id="owner",
            )
            contract = authorize_task_contract(
                conn,
                project="demo",
                agent_profile_version_id=profile["agent_profile_version_id"],
                contract=self._contract(),
                actor_type="operator",
                actor_id="owner",
            )
            loaded = load_authorized_context(
                conn,
                project="demo",
                task_contract_id=contract["task_contract_id"],
            )
            conn.close()

        self.assertEqual(replay, profile)
        self.assertEqual(loaded["profile"], self._profile())
        self.assertEqual(loaded["contract"], self._contract())
        self.assertEqual(loaded["profile_authority"], "operator")
        self.assertEqual(loaded["contract_authority"], "operator")

    def test_agent_cannot_register_verified_profile_or_authorize_contract(self):
        from rta_brain.context_authorization import (
            authorize_task_contract,
            register_agent_profile,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            with self.assertRaisesRegex(
                PermissionError, "verified profiles require operator authority"
            ):
                register_agent_profile(
                    conn,
                    project="demo",
                    profile=self._profile(),
                    actor_type="agent",
                    actor_id="codex",
                )
            profile = register_agent_profile(
                conn,
                project="demo",
                profile=self._profile(),
                actor_type="operator",
                actor_id="owner",
            )
            with self.assertRaisesRegex(
                PermissionError, "task contract authorization requires an operator"
            ):
                authorize_task_contract(
                    conn,
                    project="demo",
                    agent_profile_version_id=profile["agent_profile_version_id"],
                    contract=self._contract(),
                    actor_type="agent",
                    actor_id="codex",
                )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM task_contracts").fetchone()[0], 0
            )
            conn.close()

    def test_authorized_context_is_project_bound_and_digest_verified(self):
        from rta_brain.context_authorization import (
            authorize_task_contract,
            load_authorized_context,
            register_agent_profile,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            db.ensure_project(conn, "other", str(Path(tmp) / "other"))
            profile = register_agent_profile(
                conn,
                project="demo",
                profile=self._profile(),
                actor_type="operator",
                actor_id="owner",
            )
            contract = authorize_task_contract(
                conn,
                project="demo",
                agent_profile_version_id=profile["agent_profile_version_id"],
                contract=self._contract(),
                actor_type="operator",
                actor_id="owner",
            )
            with self.assertRaisesRegex(PermissionError, "not authorized for this project"):
                load_authorized_context(
                    conn,
                    project="other",
                    task_contract_id=contract["task_contract_id"],
                )
            conn.close()

    def test_profile_registration_rolls_back_on_keyboard_interrupt(self):
        from rta_brain.context_authorization import register_agent_profile

        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            with (
                patch(
                    "rta_brain.context_authorization._project_row",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                register_agent_profile(
                    conn,
                    project="demo",
                    profile=self._profile(),
                    actor_type="operator",
                    actor_id="owner",
                )

            self.assertFalse(conn.in_transaction)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM agent_profiles").fetchone()[0],
                0,
            )
            conn.close()

    def test_contract_authorization_rolls_back_on_keyboard_interrupt(self):
        from rta_brain.context_authorization import (
            authorize_task_contract,
            register_agent_profile,
        )

        with tempfile.TemporaryDirectory() as tmp:
            conn = self._fixture(tmp)
            profile = register_agent_profile(
                conn,
                project="demo",
                profile=self._profile(),
                actor_type="operator",
                actor_id="owner",
            )
            with (
                patch(
                    "rta_brain.context_authorization._project_row",
                    side_effect=KeyboardInterrupt,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                authorize_task_contract(
                    conn,
                    project="demo",
                    agent_profile_version_id=profile["agent_profile_version_id"],
                    contract=self._contract(),
                    actor_type="operator",
                    actor_id="owner",
                )

            self.assertFalse(conn.in_transaction)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM task_contracts").fetchone()[0],
                0,
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
