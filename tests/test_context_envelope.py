import unittest


class AuthorizedCompilationEnvelopeTests(unittest.TestCase):
    def _contract(self):
        return {
            "schema_version": "rta-smriti.task-contract/v1",
            "contract_id": "contract-envelope-001",
            "project": "atlas-relay-demo",
            "objective": "Continue release qualification without publishing.",
            "risk_class": "release_critical",
            "acceptance_criteria": ["Browser acceptance passes."],
            "stop_conditions": ["Canonical identity changes."],
            "prohibited_actions": ["publish"],
            "scope": {
                "projects": ["atlas-relay-demo"],
                "privacy_ceiling": "internal",
            },
            "agent_profile_id": "universal",
            "budgets": {
                "max_input_tokens": 4096,
                "reserved_output_tokens": 1024,
                "host_overhead_tokens": 128,
                "tool_overhead_tokens": 64,
                "safety_margin_tokens": 128,
            },
            "compiler_mode": "handoff",
            "created_at": "2026-08-22T00:00:00Z",
            "created_by": {"actor_type": "operator", "actor_id": "owner"},
        }

    def _profile(self, *, source="operator_declared", verification="verified"):
        return {
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": "universal",
            "source": source,
            "verification_status": verification,
            "input_modalities": ["text"],
            "artifact_forms": ["inline_text"],
            "max_input_tokens": 4096,
            "reserved_output_tokens": 1024,
            "host_overhead_tokens": 128,
            "tool_overhead_tokens": 64,
            "tokenizer_family": None,
            "supports": {
                "mcp_resources": False,
                "resource_links": False,
                "file_references": False,
                "structured_json": False,
            },
            "max_item_bytes": 65536,
            "max_attachment_bytes": 65536,
            "privacy_ceiling": "internal",
            "project_scopes": ["atlas-relay-demo"],
            "rendering_conventions": ["plain_text"],
            "unsupported_features": [],
        }

    def test_envelope_binds_contract_profile_authorization_and_effective_budget(self):
        try:
            from rta_brain.context_envelope import build_compilation_envelope
        except ModuleNotFoundError:
            self.fail("the authorized compilation envelope is not implemented")

        envelope = build_compilation_envelope(
            self._contract(),
            self._profile(),
            authority="operator",
            profile_authority="operator",
        )

        self.assertEqual(envelope["schema_version"], "rta-smriti.compilation-envelope/v1")
        self.assertEqual(envelope["authorization"]["state"], "operator_authorized")
        self.assertEqual(len(envelope["contract_digest"]), 64)
        self.assertEqual(len(envelope["profile_digest"]), 64)
        self.assertEqual(len(envelope["envelope_digest"]), 64)
        self.assertEqual(envelope["effective_budget"]["available_context_tokens"], 2752)
        self.assertEqual(envelope["effective_budget"]["max_input_tokens"], 4096)

    def test_profile_budget_conflicts_fail_closed_instead_of_silent_clamping(self):
        from rta_brain.context_envelope import build_compilation_envelope

        profile = self._profile()
        profile["max_input_tokens"] = 2048
        with self.assertRaisesRegex(ValueError, "contract max_input_tokens exceeds agent profile"):
            build_compilation_envelope(
                self._contract(), profile, authority="operator", profile_authority="operator",
            )

        overhead = self._profile()
        overhead["host_overhead_tokens"] = 256
        with self.assertRaisesRegex(ValueError, "host_overhead_tokens conflicts"):
            build_compilation_envelope(
                self._contract(), overhead, authority="operator", profile_authority="operator",
            )

    def test_profile_identity_scope_and_privacy_mismatch_fail_closed(self):
        from rta_brain.context_envelope import build_compilation_envelope

        wrong_id = self._profile()
        wrong_id["profile_id"] = "different"
        with self.assertRaisesRegex(ValueError, "agent profile does not match"):
            build_compilation_envelope(
                self._contract(), wrong_id, authority="operator", profile_authority="operator",
            )

        private_contract = self._contract()
        private_contract["scope"]["privacy_ceiling"] = "sensitive"
        with self.assertRaisesRegex(ValueError, "privacy ceiling exceeds"):
            build_compilation_envelope(
                private_contract,
                self._profile(),
                authority="operator",
                profile_authority="operator",
            )

    def test_raw_host_observation_and_empty_project_grants_are_rejected(self):
        from rta_brain.agent_profiles import builtin_agent_profile
        from rta_brain.context_envelope import build_compilation_envelope

        host = self._profile(source="host_observed", verification="observed")
        host["privacy_ceiling"] = "restricted"
        with self.assertRaisesRegex(ValueError, "raw host_observed profile"):
            build_compilation_envelope(
                self._contract(), host, authority="operator", profile_authority="host",
            )

        with self.assertRaisesRegex(ValueError, "profile grants no project scope"):
            build_compilation_envelope(
                self._contract(), builtin_agent_profile("universal"),
                authority="operator", profile_authority="builtin",
            )

    def test_caller_cannot_mutate_a_builtin_profile_body(self):
        from rta_brain.agent_profiles import builtin_agent_profile
        from rta_brain.context_envelope import build_compilation_envelope

        forged = builtin_agent_profile("universal")
        forged["project_scopes"] = ["atlas-relay-demo"]
        forged["max_input_tokens"] = 4096
        forged["reserved_output_tokens"] = 1024
        forged["host_overhead_tokens"] = 128
        forged["tool_overhead_tokens"] = 64
        with self.assertRaisesRegex(ValueError, "builtin profile body does not match"):
            build_compilation_envelope(
                self._contract(), forged,
                authority="operator", profile_authority="builtin",
            )

    def test_resolved_profile_is_envelope_compatible_and_host_cannot_raise_grants(self):
        from rta_brain.agent_profiles import resolve_agent_profile
        from rta_brain.context_envelope import build_compilation_envelope

        host = self._profile(source="host_observed", verification="observed")
        host["max_input_tokens"] = 8192
        host["privacy_ceiling"] = "restricted"
        host["project_scopes"] = ["other-private-project"]
        operator = self._profile()
        resolved = resolve_agent_profile(
            "universal", host_observed=host, operator_verified=operator,
        )
        envelope = build_compilation_envelope(
            self._contract(), resolved,
            authority="operator", profile_authority="operator",
        )

        self.assertEqual(resolved["privacy_ceiling"], "internal")
        self.assertEqual(resolved["project_scopes"], ["atlas-relay-demo"])
        self.assertEqual(envelope["effective_budget"]["available_context_tokens"], 2752)

    def test_agent_proposal_envelope_remains_a_proposal(self):
        from rta_brain.agent_profiles import builtin_agent_profile
        from rta_brain.context_envelope import build_compilation_envelope

        contract = self._contract()
        contract["created_by"] = {"actor_type": "agent_proposal", "actor_id": "agent-a"}
        envelope = build_compilation_envelope(
            contract,
            self._profile(),
            authority="agent",
            profile_authority="operator",
        )

        self.assertEqual(envelope["authorization"]["state"], "proposal")
        self.assertIsNone(envelope["authorization"]["authorized_by"])

    def test_envelope_digest_is_stable_and_changes_with_bound_inputs(self):
        from rta_brain.context_envelope import build_compilation_envelope

        first = build_compilation_envelope(
            self._contract(), self._profile(),
            authority="operator", profile_authority="operator",
        )
        second = build_compilation_envelope(
            dict(reversed(list(self._contract().items()))), self._profile(),
            authority="operator", profile_authority="operator",
        )
        changed = self._contract()
        changed["objective"] = "A different objective."
        third = build_compilation_envelope(
            changed, self._profile(),
            authority="operator", profile_authority="operator",
        )
        changed_profile = self._profile()
        changed_profile["max_item_bytes"] = 32768
        fourth = build_compilation_envelope(
            self._contract(), changed_profile,
            authority="operator", profile_authority="operator",
        )

        self.assertEqual(first["envelope_digest"], second["envelope_digest"])
        self.assertNotEqual(first["envelope_digest"], third["envelope_digest"])
        self.assertNotEqual(first["envelope_digest"], fourth["envelope_digest"])
        self.assertNotIn("contract_canonical", first)
        self.assertNotIn("profile_canonical", first)

    def test_v1_persistence_digest_vectors_are_frozen(self):
        from rta_brain.agent_profiles import agent_profile_digest
        from rta_brain.context_envelope import build_compilation_envelope
        from rta_brain.task_contracts import task_contract_digest

        contract = self._contract()
        profile = self._profile()
        envelope = build_compilation_envelope(
            contract, profile, authority="operator", profile_authority="operator",
        )

        self.assertEqual(
            task_contract_digest(contract, authority="operator"),
            "de70b24c93503a293ea9cc14f3d9394b5fdcbf7265024b70d615cfb9f62153c7",
        )
        self.assertEqual(
            agent_profile_digest(profile),
            "87708b11ed870ab05f5ec3e096f1d2521c3759270e51c243833906992e252a98",
        )
        self.assertEqual(
            envelope["envelope_digest"],
            "c1207ef406b50140598654f13dad6f853612f9f38a77e74ed7fd73afa27fa621",
        )


if __name__ == "__main__":
    unittest.main()
