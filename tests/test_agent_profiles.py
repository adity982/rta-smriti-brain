import copy
import unittest


class AgentProfileTests(unittest.TestCase):
    def _profile(
        self,
        *,
        source="operator_declared",
        verification="verified",
        profile_id="custom-local-agent",
    ):
        return {
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": profile_id,
            "source": source,
            "verification_status": verification,
            "input_modalities": ["text"],
            "artifact_forms": ["inline_text", "file_reference"],
            "max_input_tokens": 8192,
            "reserved_output_tokens": 1024,
            "host_overhead_tokens": 256,
            "tool_overhead_tokens": 128,
            "tokenizer_family": "cl100k_base",
            "supports": {
                "mcp_resources": True,
                "resource_links": True,
                "file_references": True,
                "structured_json": True,
            },
            "max_item_bytes": 262_144,
            "max_attachment_bytes": 1_048_576,
            "privacy_ceiling": "sensitive",
            "project_scopes": ["atlas-relay-demo"],
            "rendering_conventions": ["markdown", "json"],
            "unsupported_features": ["video"],
        }

    def test_universal_profile_is_conservative_and_digestible(self):
        try:
            from rta_brain.agent_profiles import (
                agent_profile_digest,
                builtin_agent_profile,
            )
        except ModuleNotFoundError:
            self.fail("rta_brain.agent_profiles is not implemented")

        profile = builtin_agent_profile("universal")
        self.assertEqual(profile["source"], "builtin")
        self.assertEqual(profile["verification_status"], "default")
        self.assertEqual(profile["input_modalities"], ["text"])
        self.assertEqual(profile["artifact_forms"], ["inline_text"])
        self.assertIsNone(profile["max_input_tokens"])
        self.assertEqual(profile["privacy_ceiling"], "internal")
        self.assertFalse(any(profile["supports"].values()))
        self.assertEqual(len(agent_profile_digest(profile)), 64)

    def test_profile_validation_rejects_unknown_fields_and_invalid_bounds(self):
        from rta_brain.agent_profiles import validate_agent_profile

        unknown = self._profile()
        unknown["model_intelligence"] = "high"
        with self.assertRaisesRegex(ValueError, "unknown agent profile field: model_intelligence"):
            validate_agent_profile(unknown)

        nested = self._profile()
        nested["supports"]["shell_execution"] = True
        with self.assertRaisesRegex(ValueError, "unknown supports field: shell_execution"):
            validate_agent_profile(nested)

        oversized = self._profile()
        oversized["max_item_bytes"] = 17 * 1024 * 1024
        with self.assertRaisesRegex(ValueError, "max_item_bytes"):
            validate_agent_profile(oversized)

    def test_host_observation_can_describe_consumption_but_cannot_raise_grants(self):
        from rta_brain.agent_profiles import resolve_agent_profile

        host = self._profile(
            source="host_observed", verification="observed", profile_id="universal",
        )
        host["privacy_ceiling"] = "restricted"
        host["project_scopes"] = ["atlas-relay-demo", "other-private-project"]
        resolved = resolve_agent_profile("universal", host_observed=host)

        self.assertEqual(resolved["max_input_tokens"], 8192)
        self.assertTrue(resolved["supports"]["file_references"])
        self.assertEqual(resolved["privacy_ceiling"], "internal")
        self.assertEqual(resolved["project_scopes"], [])
        self.assertEqual(resolved["field_sources"]["max_input_tokens"], "host_observed")
        self.assertEqual(resolved["field_sources"]["privacy_ceiling"], "builtin")

    def test_verified_operator_profile_has_final_precedence(self):
        from rta_brain.agent_profiles import resolve_agent_profile

        host = self._profile(
            source="host_observed", verification="observed", profile_id="universal",
        )
        host["max_input_tokens"] = 16_384
        operator = self._profile(profile_id="universal")
        operator["max_input_tokens"] = 4096
        operator["privacy_ceiling"] = "sensitive"
        resolved = resolve_agent_profile(
            "universal",
            host_observed=host,
            operator_verified=operator,
        )

        self.assertEqual(resolved["max_input_tokens"], 4096)
        self.assertEqual(resolved["privacy_ceiling"], "sensitive")
        self.assertEqual(resolved["source"], "resolved")
        self.assertEqual(resolved["verification_status"], "verified")
        self.assertEqual(resolved["field_sources"]["max_input_tokens"], "operator_verified")
        self.assertEqual(resolved["field_sources"]["privacy_ceiling"], "operator_verified")

    def test_unverified_operator_input_is_rejected(self):
        from rta_brain.agent_profiles import resolve_agent_profile

        operator = self._profile(verification="observed")
        with self.assertRaisesRegex(ValueError, "operator profile must be verified"):
            resolve_agent_profile("universal", operator_verified=operator)

        with self.assertRaisesRegex(ValueError, "operator profile must be an object"):
            resolve_agent_profile("universal", operator_verified=[])

    def test_host_observation_cannot_replace_profile_identity(self):
        from rta_brain.agent_profiles import resolve_agent_profile

        host = self._profile(source="host_observed", verification="observed")
        with self.assertRaisesRegex(ValueError, "host profile_id must match"):
            resolve_agent_profile("universal", host_observed=host)

    def test_resolved_profile_is_canonicalizable_and_digestible(self):
        from rta_brain.agent_profiles import (
            agent_profile_digest,
            canonical_agent_profile,
            resolve_agent_profile,
        )

        host = self._profile(
            source="host_observed", verification="observed", profile_id="universal",
        )
        operator = self._profile(profile_id="universal")
        resolved = resolve_agent_profile(
            "universal", host_observed=host, operator_verified=operator,
        )

        self.assertIn('"source":"resolved"', canonical_agent_profile(resolved))
        self.assertEqual(len(agent_profile_digest(resolved)), 64)
        self.assertEqual(resolved["field_sources"]["privacy_ceiling"], "operator_verified")

        default = resolve_agent_profile("universal")
        self.assertEqual(default["source"], "builtin")
        self.assertNotIn("field_sources", default)
        self.assertIn('"source":"builtin"', canonical_agent_profile(default))

    def test_profile_canonicalization_normalizes_unicode_line_endings_and_key_order(self):
        from rta_brain.agent_profiles import canonical_agent_profile

        first = self._profile()
        first["rendering_conventions"] = ["Cafe\u0301\r\nmarkdown"]
        second = dict(reversed(list(self._profile().items())))
        second["rendering_conventions"] = ["Caf\u00e9\nmarkdown"]

        self.assertEqual(canonical_agent_profile(first), canonical_agent_profile(second))

    def test_omitted_profile_defaults_match_explicit_defaults(self):
        from rta_brain.agent_profiles import canonical_agent_profile

        explicit = {
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": "minimal",
            "source": "builtin",
            "verification_status": "default",
            "input_modalities": ["text"],
            "artifact_forms": ["inline_text"],
            "max_input_tokens": None,
            "reserved_output_tokens": 0,
            "host_overhead_tokens": 0,
            "tool_overhead_tokens": 0,
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
            "project_scopes": [],
            "rendering_conventions": ["plain_text"],
            "unsupported_features": [],
        }
        omitted = {
            "schema_version": "rta-smriti.agent-profile/v1",
            "profile_id": "minimal",
            "source": "builtin",
            "verification_status": "default",
        }

        self.assertEqual(canonical_agent_profile(explicit), canonical_agent_profile(omitted))

    def test_validation_returns_a_detached_value(self):
        from rta_brain.agent_profiles import validate_agent_profile

        payload = self._profile()
        original = copy.deepcopy(payload)
        validated = validate_agent_profile(payload)
        validated["input_modalities"].append("image")

        self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()
