import copy
import unittest


class TaskContractTests(unittest.TestCase):
    def _contract(self):
        return {
            "schema_version": "rta-smriti.task-contract/v1",
            "contract_id": "contract-001",
            "project": "atlas-relay-demo",
            "objective": "Qualify the release candidate without publishing it.",
            "task_type": "release-qualification",
            "risk_class": "release_critical",
            "acceptance_criteria": [
                "The rendered browser acceptance journey passes.",
                "The owner reviews the exact candidate before publication.",
            ],
            "required_evidence": ["browser acceptance receipt"],
            "stop_conditions": ["Stop if the canonical checkout changes."],
            "escalation_conditions": ["Escalate a privacy-scan finding."],
            "prohibited_repetition": ["Do not rerun superseded release assets."],
            "prohibited_actions": ["publish", "push", "tag"],
            "scope": {
                "projects": ["atlas-relay-demo"],
                "source_types": ["checkpoint", "truth_claim", "policy"],
                "privacy_ceiling": "internal",
                "valid_at": "2026-08-22T05:30:00+05:30",
                "recorded_sequence": 31,
                "path_globs": ["src/**", "tests/**"],
            },
            "informational_tool_grants": ["read:files", "read:tests"],
            "agent_profile_id": "universal",
            "budgets": {
                "max_input_tokens": 4096,
                "reserved_output_tokens": 1024,
                "host_overhead_tokens": 256,
                "tool_overhead_tokens": 128,
                "safety_margin_tokens": 128,
            },
            "compiler_mode": "balanced",
            "created_at": "2026-08-22T05:30:00+05:30",
            "created_by": {"actor_type": "operator", "actor_id": "owner"},
        }

    def test_canonical_serialization_and_digest_are_stable(self):
        try:
            from rta_brain.task_contracts import (
                canonical_task_contract,
                task_contract_digest,
                validate_task_contract,
            )
        except ModuleNotFoundError:
            self.fail("rta_brain.task_contracts is not implemented")

        first = self._contract()
        second = dict(reversed(list(first.items())))
        validated = validate_task_contract(first, authority="operator")

        self.assertEqual(validated["created_at"], "2026-08-22T00:00:00+00:00")
        self.assertEqual(validated["scope"]["valid_at"], "2026-08-22T00:00:00+00:00")
        self.assertEqual(
            canonical_task_contract(first, authority="operator"),
            canonical_task_contract(second, authority="operator"),
        )
        self.assertEqual(
            task_contract_digest(first, authority="operator"),
            task_contract_digest(second, authority="operator"),
        )
        self.assertEqual(len(task_contract_digest(first, authority="operator")), 64)

    def test_unknown_fields_are_rejected_at_every_schema_boundary(self):
        from rta_brain.task_contracts import validate_task_contract

        root = self._contract()
        root["surprise"] = True
        with self.assertRaisesRegex(ValueError, "unknown task contract field: surprise"):
            validate_task_contract(root, authority="operator")

        nested = self._contract()
        nested["scope"]["surprise"] = True
        with self.assertRaisesRegex(ValueError, "unknown scope field: surprise"):
            validate_task_contract(nested, authority="operator")

        actor = self._contract()
        actor["created_by"]["authority"] = "owner"
        with self.assertRaisesRegex(ValueError, "unknown created_by field: authority"):
            validate_task_contract(actor, authority="operator")

    def test_required_controls_and_bounds_fail_closed(self):
        from rta_brain.task_contracts import validate_task_contract

        for field in ("acceptance_criteria", "stop_conditions", "prohibited_actions"):
            payload = self._contract()
            payload[field] = []
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, field):
                    validate_task_contract(payload, authority="operator")

        oversized = self._contract()
        oversized["objective"] = "x" * 10_001
        with self.assertRaisesRegex(ValueError, "objective exceeds 10,000 characters"):
            validate_task_contract(oversized, authority="operator")

        too_many = self._contract()
        too_many["acceptance_criteria"] = [f"criterion-{index}" for index in range(101)]
        with self.assertRaisesRegex(ValueError, "acceptance_criteria exceeds 100 items"):
            validate_task_contract(too_many, authority="operator")

    def test_budget_arithmetic_preserves_a_minimum_compilable_input(self):
        from rta_brain.task_contracts import (
            available_context_tokens,
            validate_task_contract,
        )

        valid = validate_task_contract(self._contract(), authority="operator")
        self.assertEqual(available_context_tokens(valid, authority="operator"), 2560)

        invalid = self._contract()
        invalid["budgets"] = {
            "max_input_tokens": 1024,
            "reserved_output_tokens": 512,
            "host_overhead_tokens": 256,
            "tool_overhead_tokens": 128,
            "safety_margin_tokens": 128,
        }
        with self.assertRaisesRegex(ValueError, "at least 256 tokens must remain"):
            validate_task_contract(invalid, authority="operator")

    def test_comparison_modes_are_explicit_bounded_and_canonical(self):
        from rta_brain.task_contracts import validate_task_contract

        payload = self._contract()
        payload["comparison_modes"] = ["investigative", "minimal"]
        normalized = validate_task_contract(payload, authority="operator")
        self.assertEqual(normalized["comparison_modes"], ["minimal", "investigative"])

        for invalid in (
            ["balanced"],
            ["minimal", "minimal"],
            ["minimal", "balanced", "investigative", "handoff"],
            ["invented"],
        ):
            rejected = self._contract()
            rejected["comparison_modes"] = invalid
            with self.subTest(modes=invalid), self.assertRaisesRegex(
                ValueError, "comparison_modes"
            ):
                validate_task_contract(rejected, authority="operator")

    def test_agent_proposals_cannot_self_grant_private_or_owner_authority(self):
        from rta_brain.task_contracts import validate_task_contract

        restricted = self._contract()
        restricted["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        restricted["scope"]["privacy_ceiling"] = "restricted"
        with self.assertRaisesRegex(ValueError, "agent proposal cannot grant sensitive or restricted privacy"):
            validate_task_contract(restricted, authority="agent")

        owner_grant = self._contract()
        owner_grant["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        owner_grant["informational_tool_grants"] = ["read:files", "owner:publish"]
        with self.assertRaisesRegex(ValueError, "agent proposal cannot grant owner capability"):
            validate_task_contract(owner_grant, authority="agent")

        for unsafe_grant in ("publish", "admin:publish", "execute:tool", "model:route"):
            unsafe = self._contract()
            unsafe["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
            unsafe["informational_tool_grants"] = [unsafe_grant]
            with self.subTest(grant=unsafe_grant):
                with self.assertRaisesRegex(ValueError, "informational read-only capability"):
                    validate_task_contract(unsafe, authority="agent")

        noncanonical = self._contract()
        noncanonical["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        noncanonical["informational_tool_grants"] = ["READ:files"]
        with self.assertRaisesRegex(ValueError, "lowercase canonical prefix"):
            validate_task_contract(noncanonical, authority="agent")

        safe = self._contract()
        safe["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        self.assertEqual(
            validate_task_contract(safe, authority="agent")["scope"]["privacy_ceiling"],
            "internal",
        )

    def test_validation_returns_a_detached_normalized_value(self):
        from rta_brain.task_contracts import validate_task_contract

        payload = self._contract()
        original = copy.deepcopy(payload)
        normalized = validate_task_contract(payload, authority="operator")
        normalized["scope"]["projects"].append("other")

        self.assertEqual(payload, original)

    def test_caller_authority_cannot_be_self_declared_in_json(self):
        from rta_brain.task_contracts import validate_task_contract

        spoofed = self._contract()
        with self.assertRaisesRegex(ValueError, "operator contract requires operator authority"):
            validate_task_contract(spoofed, authority="agent")

        authorized = validate_task_contract(spoofed, authority="operator")
        self.assertEqual(authorized["authorization"]["state"], "operator_authorized")
        self.assertEqual(authorized["authorization"]["authorized_by"], "owner")

    def test_equivalent_unicode_line_endings_and_explicit_defaults_canonicalize_equally(self):
        from rta_brain.task_contracts import canonical_task_contract

        explicit = self._contract()
        explicit["objective"] = "Cafe\u0301 release\r\nqualification"
        omitted = self._contract()
        omitted["objective"] = "Caf\u00e9 release\nqualification"
        for field in (
            "task_type", "required_evidence", "escalation_conditions",
            "prohibited_repetition", "informational_tool_grants",
        ):
            omitted.pop(field)
        omitted["budgets"].pop("host_overhead_tokens")
        omitted["budgets"].pop("tool_overhead_tokens")
        omitted["budgets"].pop("safety_margin_tokens")
        omitted["scope"].pop("source_types")
        omitted["scope"].pop("path_globs")
        explicit["task_type"] = "general"
        explicit["required_evidence"] = []
        explicit["escalation_conditions"] = []
        explicit["prohibited_repetition"] = []
        explicit["informational_tool_grants"] = []
        explicit["budgets"]["host_overhead_tokens"] = 0
        explicit["budgets"]["tool_overhead_tokens"] = 0
        explicit["budgets"]["safety_margin_tokens"] = 128
        explicit["scope"]["source_types"] = []
        explicit["scope"]["path_globs"] = []

        self.assertEqual(
            canonical_task_contract(explicit, authority="operator"),
            canonical_task_contract(omitted, authority="operator"),
        )

    def test_project_scope_and_path_globs_fail_closed(self):
        from rta_brain.task_contracts import validate_task_contract

        mismatch = self._contract()
        mismatch["scope"]["projects"] = ["other-project"]
        with self.assertRaisesRegex(ValueError, "project must be included in scope.projects"):
            validate_task_contract(mismatch, authority="operator")

        cross_project = self._contract()
        cross_project["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        cross_project["scope"]["projects"].append("other-project")
        with self.assertRaisesRegex(ValueError, "agent proposal cannot grant cross-project scope"):
            validate_task_contract(cross_project, authority="agent")

        for unsafe in (
            "../secrets/**", "C:/private/**", "D:../secret/**",
            "D:relative/**", "/etc/**", "//server/share/**",
        ):
            payload = self._contract()
            payload["scope"]["path_globs"] = [unsafe]
            with self.subTest(path=unsafe):
                with self.assertRaisesRegex(ValueError, "project-relative"):
                    validate_task_contract(payload, authority="operator")

    def test_control_ids_are_stable_and_bound_to_normalized_statements(self):
        from rta_brain.task_contracts import validate_task_contract

        first = self._contract()
        first["acceptance_criteria"] = ["Cafe\u0301 output is verified."]
        second = self._contract()
        second["acceptance_criteria"] = ["Caf\u00e9 output is verified."]

        first_index = validate_task_contract(first, authority="operator")["control_index"]
        second_index = validate_task_contract(second, authority="operator")["control_index"]

        self.assertEqual(first_index, second_index)
        self.assertRegex(first_index["acceptance_criteria"][0]["control_id"], r"^accept-[0-9a-f]{16}$")
        self.assertEqual(
            first_index["acceptance_criteria"][0]["statement"],
            "Caf\u00e9 output is verified.",
        )
        self.assertRegex(first_index["stop_conditions"][0]["control_id"], r"^stop-[0-9a-f]{16}$")
        self.assertRegex(first_index["prohibited_actions"][0]["control_id"], r"^action-[0-9a-f]{16}$")

    def test_path_glob_separators_canonicalize_portably(self):
        from rta_brain.task_contracts import canonical_task_contract

        windows_style = self._contract()
        windows_style["scope"]["path_globs"] = ["src\\**\\*.py"]
        portable = self._contract()
        portable["scope"]["path_globs"] = ["src/**/*.py"]

        self.assertEqual(
            canonical_task_contract(windows_style, authority="operator"),
            canonical_task_contract(portable, authority="operator"),
        )

    def test_subsecond_authorization_times_remain_distinct_in_digests(self):
        from rta_brain.task_contracts import (
            task_contract_digest,
            validate_task_contract,
        )

        first = self._contract()
        first["created_at"] = "2026-08-22T00:00:00.100000Z"
        second = self._contract()
        second["created_at"] = "2026-08-22T00:00:00.900000Z"

        first_normalized = validate_task_contract(first, authority="operator")
        second_normalized = validate_task_contract(second, authority="operator")
        self.assertEqual(first_normalized["created_at"], "2026-08-22T00:00:00.100000+00:00")
        self.assertEqual(second_normalized["created_at"], "2026-08-22T00:00:00.900000+00:00")
        self.assertNotEqual(
            task_contract_digest(first, authority="operator"),
            task_contract_digest(second, authority="operator"),
        )

        for timestamp in (
            "2026-08-22T00:00:00.1234567Z",
            "2026-08-22T00:00:00.1234561+00",
            "2026-08-22T00:00:00.1234569+000000",
            "2026-08-22T00:00:00.1234567+00:00:00",
        ):
            unsupported = self._contract()
            unsupported["created_at"] = timestamp
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValueError, "RFC 3339.*1 to 6 fractional digits"):
                    validate_task_contract(unsupported, authority="operator")


if __name__ == "__main__":
    unittest.main()
