from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS agent_profiles (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        profile_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        retired_at TEXT,
        UNIQUE(project_id, profile_id),
        UNIQUE(id, project_id, profile_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_profile_versions (
        id INTEGER PRIMARY KEY,
        agent_profile_id INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        profile_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version > 0),
        schema_version TEXT NOT NULL,
        source TEXT NOT NULL CHECK(
            source IN ('builtin', 'host_observed', 'operator_declared', 'resolved')
        ),
        verification_status TEXT NOT NULL CHECK(
            verification_status IN ('default', 'observed', 'verified')
        ),
        canonical_json TEXT NOT NULL CHECK(json_valid(canonical_json)),
        digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        UNIQUE(agent_profile_id, version),
        UNIQUE(agent_profile_id, digest),
        UNIQUE(id, project_id, profile_id, digest),
        FOREIGN KEY(agent_profile_id, project_id, profile_id)
            REFERENCES agent_profiles(id, project_id, profile_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_contracts (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        agent_profile_version_id INTEGER NOT NULL,
        contract_id TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        canonical_json TEXT NOT NULL CHECK(json_valid(canonical_json)),
        digest TEXT NOT NULL,
        authorization_state TEXT NOT NULL CHECK(
            authorization_state IN ('proposal', 'operator_authorized')
        ),
        profile_id TEXT NOT NULL,
        profile_digest TEXT NOT NULL,
        created_at TEXT NOT NULL,
        actor_type TEXT NOT NULL CHECK(actor_type IN ('operator', 'agent_proposal', 'system')),
        actor_id TEXT NOT NULL,
        UNIQUE(project_id, contract_id),
        UNIQUE(project_id, digest),
        UNIQUE(id, project_id, digest, profile_digest),
        CHECK(
            (authorization_state = 'operator_authorized' AND actor_type = 'operator')
            OR
            (authorization_state = 'proposal' AND actor_type IN ('agent_proposal', 'system'))
        ),
        FOREIGN KEY(agent_profile_version_id, project_id, profile_id, profile_digest)
            REFERENCES agent_profile_versions(id, project_id, profile_id, digest)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_authority_grants (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        task_contract_id INTEGER NOT NULL REFERENCES task_contracts(id) ON DELETE RESTRICT,
        grant_id TEXT NOT NULL,
        claims_json TEXT NOT NULL CHECK(json_valid(claims_json)),
        capability_digest TEXT NOT NULL CHECK(length(capability_digest) = 64),
        issued_at_epoch_ms INTEGER NOT NULL CHECK(issued_at_epoch_ms >= 0),
        expires_at_epoch_ms INTEGER NOT NULL CHECK(expires_at_epoch_ms > issued_at_epoch_ms),
        issued_by_type TEXT NOT NULL CHECK(issued_by_type = 'operator'),
        issued_by_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(project_id, grant_id),
        UNIQUE(id, project_id, task_contract_id),
        UNIQUE(id, project_id, task_contract_id, capability_digest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_authority_revocations (
        id INTEGER PRIMARY KEY,
        authority_grant_id INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        task_contract_id INTEGER NOT NULL,
        capability_digest TEXT NOT NULL,
        revoked_at_epoch_ms INTEGER NOT NULL CHECK(revoked_at_epoch_ms >= 0),
        reason TEXT NOT NULL,
        revoked_by_type TEXT NOT NULL CHECK(revoked_by_type = 'operator'),
        revoked_by_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(authority_grant_id),
        FOREIGN KEY(authority_grant_id, project_id, task_contract_id, capability_digest)
            REFERENCES context_authority_grants(
                id, project_id, task_contract_id, capability_digest
            ) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_compilations (
        id INTEGER PRIMARY KEY,
        compilation_id TEXT NOT NULL UNIQUE,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        task_contract_id INTEGER NOT NULL,
        authority_grant_id INTEGER NOT NULL,
        contract_digest TEXT NOT NULL,
        profile_digest TEXT NOT NULL,
        envelope_digest TEXT NOT NULL,
        snapshot_digest TEXT NOT NULL,
        compiler_version TEXT NOT NULL,
        compiler_mode TEXT NOT NULL CHECK(
            compiler_mode IN ('minimal', 'balanced', 'investigative', 'handoff')
        ),
        status TEXT NOT NULL CHECK(status IN ('building', 'complete', 'abstained', 'failed')),
        effective_budget_json TEXT NOT NULL CHECK(json_valid(effective_budget_json)),
        receipt_digest TEXT,
        created_at TEXT NOT NULL,
        finalized_at TEXT,
        UNIQUE(id, project_id),
        CHECK(
            (status = 'building' AND receipt_digest IS NULL AND finalized_at IS NULL)
            OR
            (status IN ('complete', 'abstained', 'failed')
             AND receipt_digest IS NOT NULL AND finalized_at IS NOT NULL)
        ),
        FOREIGN KEY(task_contract_id, project_id, contract_digest, profile_digest)
            REFERENCES task_contracts(id, project_id, digest, profile_digest)
            ON DELETE RESTRICT,
        FOREIGN KEY(authority_grant_id, project_id, task_contract_id)
            REFERENCES context_authority_grants(id, project_id, task_contract_id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_candidate_receipts (
        id INTEGER PRIMARY KEY,
        compilation_id INTEGER NOT NULL REFERENCES context_compilations(id) ON DELETE RESTRICT,
        candidate_id TEXT NOT NULL,
        disposition TEXT NOT NULL CHECK(disposition IN (
            'included_mandatory', 'included_ranked', 'excluded_privacy',
            'excluded_scope', 'excluded_stale_or_invalid', 'excluded_duplicate',
            'excluded_low_marginal_utility', 'excluded_budget',
            'excluded_profile_incompatible', 'summarized_dependency', 'redacted'
        )),
        source_id TEXT NOT NULL,
        component_scores_json TEXT NOT NULL CHECK(json_valid(component_scores_json)),
        token_cost INTEGER NOT NULL CHECK(token_cost >= 0),
        explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
        privacy_class TEXT NOT NULL CHECK(
            privacy_class IN ('public', 'internal', 'sensitive', 'restricted')
        ),
        created_at TEXT NOT NULL,
        UNIQUE(compilation_id, candidate_id),
        UNIQUE(id, compilation_id, candidate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_retention_grants (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        grant_id TEXT NOT NULL,
        policy_digest TEXT NOT NULL,
        max_privacy_class TEXT NOT NULL CHECK(
            max_privacy_class IN ('public', 'internal', 'sensitive', 'restricted')
        ),
        max_payload_bytes INTEGER NOT NULL CHECK(
            max_payload_bytes > 0 AND max_payload_bytes <= 16777216
        ),
        authorized_by_type TEXT NOT NULL CHECK(authorized_by_type = 'operator'),
        authorized_by_id TEXT NOT NULL,
        valid_from_epoch_ms INTEGER NOT NULL CHECK(valid_from_epoch_ms >= 0),
        expires_at_epoch_ms INTEGER NOT NULL CHECK(expires_at_epoch_ms > valid_from_epoch_ms),
        created_at TEXT NOT NULL,
        UNIQUE(project_id, grant_id),
        UNIQUE(id, project_id, grant_id, policy_digest)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_pack_variants (
        id INTEGER PRIMARY KEY,
        compilation_id INTEGER NOT NULL,
        project_id INTEGER NOT NULL,
        variant_id TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('minimal', 'balanced', 'investigative', 'handoff')),
        pack_digest TEXT NOT NULL,
        token_count INTEGER NOT NULL CHECK(token_count >= 0),
        coverage_json TEXT NOT NULL CHECK(json_valid(coverage_json)),
        bounded_preview TEXT,
        preview_redacted INTEGER NOT NULL DEFAULT 0 CHECK(preview_redacted IN (0, 1)),
        privacy_class TEXT NOT NULL CHECK(
            privacy_class IN ('public', 'internal', 'sensitive', 'restricted')
        ),
        retention_grant_id INTEGER,
        retention_policy_id TEXT,
        retention_policy_digest TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(compilation_id, variant_id),
        CHECK(
            bounded_preview IS NULL
            OR length(CAST(bounded_preview AS BLOB)) <= 8192
        ),
        CHECK(
            privacy_class IN ('public', 'internal')
            OR bounded_preview IS NULL
            OR preview_redacted = 1
        ),
        CHECK(
            (retention_grant_id IS NULL AND retention_policy_id IS NULL
             AND retention_policy_digest IS NULL)
            OR
            (retention_grant_id IS NOT NULL AND retention_policy_id IS NOT NULL
             AND retention_policy_digest IS NOT NULL)
        ),
        UNIQUE(id, project_id, retention_grant_id),
        FOREIGN KEY(compilation_id, project_id)
            REFERENCES context_compilations(id, project_id) ON DELETE RESTRICT,
        FOREIGN KEY(retention_grant_id, project_id, retention_policy_id, retention_policy_digest)
            REFERENCES context_retention_grants(id, project_id, grant_id, policy_digest)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_variant_candidate_receipts (
        id INTEGER PRIMARY KEY,
        pack_variant_id INTEGER NOT NULL REFERENCES context_pack_variants(id) ON DELETE RESTRICT,
        compilation_id INTEGER NOT NULL REFERENCES context_compilations(id) ON DELETE RESTRICT,
        candidate_id TEXT NOT NULL,
        disposition TEXT NOT NULL CHECK(disposition IN (
            'included_mandatory', 'included_ranked', 'excluded_privacy',
            'excluded_scope', 'excluded_stale_or_invalid', 'excluded_duplicate',
            'excluded_low_marginal_utility', 'excluded_budget',
            'excluded_profile_incompatible', 'summarized_dependency', 'redacted'
        )),
        source_id TEXT NOT NULL,
        component_scores_json TEXT NOT NULL CHECK(json_valid(component_scores_json)),
        token_cost INTEGER NOT NULL CHECK(token_cost >= 0),
        explanation_json TEXT NOT NULL CHECK(json_valid(explanation_json)),
        privacy_class TEXT NOT NULL CHECK(
            privacy_class IN ('public', 'internal', 'sensitive', 'restricted')
        ),
        created_at TEXT NOT NULL,
        UNIQUE(pack_variant_id, candidate_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_retained_payloads (
        pack_variant_id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL,
        retention_grant_id INTEGER NOT NULL,
        payload_text TEXT NOT NULL CHECK(
            length(CAST(payload_text AS BLOB)) <= 16777216
        ),
        payload_digest TEXT NOT NULL,
        created_at_epoch_ms INTEGER NOT NULL CHECK(created_at_epoch_ms >= 0),
        expires_at_epoch_ms INTEGER NOT NULL CHECK(expires_at_epoch_ms > created_at_epoch_ms),
        FOREIGN KEY(pack_variant_id, project_id, retention_grant_id)
            REFERENCES context_pack_variants(id, project_id, retention_grant_id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_outcomes (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
        compilation_id INTEGER NOT NULL REFERENCES context_compilations(id) ON DELETE RESTRICT,
        authority_grant_id INTEGER,
        outcome_id TEXT NOT NULL,
        task_status TEXT NOT NULL CHECK(
            task_status IN ('success', 'partial_success', 'failure', 'interruption')
        ),
        attribution_level TEXT NOT NULL CHECK(
            attribution_level IN ('observed', 'correlated', 'operator_confirmed')
        ),
        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
        acceptance_results_json TEXT NOT NULL CHECK(json_valid(acceptance_results_json)),
        elapsed_ms INTEGER CHECK(elapsed_ms IS NULL OR elapsed_ms >= 0),
        input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
        output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
        created_at TEXT NOT NULL,
        actor_type TEXT NOT NULL CHECK(actor_type IN ('operator', 'agent', 'system')),
        actor_id TEXT NOT NULL,
        UNIQUE(project_id, outcome_id),
        UNIQUE(id, compilation_id),
        CHECK(
            (attribution_level = 'operator_confirmed'
             AND authority_grant_id IS NOT NULL
             AND actor_type = 'operator'
                AND json_type(evidence_json) = 'object'
                AND json(evidence_json) != '{}')
            OR
            (attribution_level != 'operator_confirmed' AND authority_grant_id IS NULL)
        ),
        FOREIGN KEY(compilation_id, project_id)
            REFERENCES context_compilations(id, project_id) ON DELETE RESTRICT,
        FOREIGN KEY(authority_grant_id)
            REFERENCES context_authority_grants(id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_attribution_edges (
        id INTEGER PRIMARY KEY,
        outcome_id INTEGER NOT NULL,
        compilation_id INTEGER NOT NULL,
        candidate_receipt_id INTEGER NOT NULL,
        candidate_id TEXT NOT NULL,
        assessment TEXT NOT NULL CHECK(
            assessment IN ('helpful', 'harmful', 'neutral', 'unused', 'unknown')
        ),
        attribution_level TEXT NOT NULL CHECK(
            attribution_level IN ('observed', 'correlated', 'operator_confirmed')
        ),
        evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
        created_at TEXT NOT NULL,
        UNIQUE(outcome_id, candidate_id, assessment),
        FOREIGN KEY(outcome_id, compilation_id)
            REFERENCES context_outcomes(id, compilation_id) ON DELETE RESTRICT,
        FOREIGN KEY(candidate_receipt_id, compilation_id, candidate_id)
            REFERENCES context_candidate_receipts(id, compilation_id, candidate_id)
            ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_benchmark_runs (
        id INTEGER PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id) ON DELETE RESTRICT,
        run_id TEXT NOT NULL UNIQUE,
        corpus_id TEXT NOT NULL,
        compiler_version TEXT NOT NULL,
        profile_digest TEXT NOT NULL,
        contract_digest TEXT NOT NULL,
        environment_json TEXT NOT NULL CHECK(json_valid(environment_json)),
        status TEXT NOT NULL CHECK(status IN ('building', 'complete', 'failed')),
        receipt_digest TEXT,
        created_at TEXT NOT NULL,
        finalized_at TEXT,
        CHECK(
            (status = 'building' AND receipt_digest IS NULL AND finalized_at IS NULL)
            OR
            (status IN ('complete', 'failed')
             AND receipt_digest IS NOT NULL AND finalized_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_benchmark_metrics (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES context_benchmark_runs(id) ON DELETE RESTRICT,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        sample_count INTEGER NOT NULL CHECK(sample_count >= 0),
        details_json TEXT NOT NULL CHECK(json_valid(details_json)),
        created_at TEXT NOT NULL,
        UNIQUE(run_id, metric_name)
    )
    """,
)

_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_agent_profiles_project ON agent_profiles(project_id, profile_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_contracts_project_created ON task_contracts(project_id, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_context_authority_grants_contract ON context_authority_grants(project_id, task_contract_id, expires_at_epoch_ms)",
    "CREATE INDEX IF NOT EXISTS idx_context_authority_revocations_project ON context_authority_revocations(project_id, revoked_at_epoch_ms DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_context_compilations_project_created ON context_compilations(project_id, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_context_candidates_compilation ON context_candidate_receipts(compilation_id, disposition, id)",
    "CREATE INDEX IF NOT EXISTS idx_context_variant_candidates_variant ON context_variant_candidate_receipts(pack_variant_id, disposition, id)",
    "CREATE INDEX IF NOT EXISTS idx_context_outcomes_project_created ON context_outcomes(project_id, created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_context_benchmarks_project_created ON context_benchmark_runs(project_id, created_at DESC, id DESC)",
)

_APPEND_ONLY_TABLES = (
    "agent_profile_versions",
    "task_contracts",
    "context_authority_grants",
    "context_authority_revocations",
    "context_candidate_receipts",
    "context_retention_grants",
    "context_pack_variants",
    "context_variant_candidate_receipts",
    "context_outcomes",
    "context_attribution_edges",
    "context_benchmark_metrics",
)

_V9_REQUIRED_COLUMNS = {
    "agent_profiles": {"id", "project_id", "profile_id", "retired_at"},
    "agent_profile_versions": {"id", "agent_profile_id", "project_id", "profile_id", "digest"},
    "task_contracts": {"id", "project_id", "agent_profile_version_id", "digest", "profile_digest"},
    "context_authority_grants": {"id", "project_id", "task_contract_id", "grant_id", "claims_json", "capability_digest", "expires_at_epoch_ms"},
    "context_authority_revocations": {"id", "authority_grant_id", "project_id", "task_contract_id", "capability_digest", "revoked_at_epoch_ms"},
    "context_compilations": {"id", "project_id", "task_contract_id", "authority_grant_id", "status", "receipt_digest", "finalized_at"},
    "context_candidate_receipts": {"id", "compilation_id", "candidate_id", "disposition"},
    "context_retention_grants": {"id", "project_id", "grant_id", "policy_digest", "max_payload_bytes", "valid_from_epoch_ms", "expires_at_epoch_ms"},
    "context_pack_variants": {"id", "compilation_id", "project_id", "retention_grant_id", "bounded_preview"},
    "context_variant_candidate_receipts": {"id", "pack_variant_id", "compilation_id", "candidate_id", "disposition"},
    "context_retained_payloads": {"pack_variant_id", "project_id", "retention_grant_id", "payload_text", "created_at_epoch_ms", "expires_at_epoch_ms"},
    "context_outcomes": {"id", "project_id", "compilation_id", "authority_grant_id", "outcome_id"},
    "context_attribution_edges": {"id", "outcome_id", "compilation_id", "candidate_receipt_id"},
    "context_benchmark_runs": {"id", "project_id", "run_id", "status", "receipt_digest", "finalized_at"},
    "context_benchmark_metrics": {"id", "run_id", "metric_name", "metric_value"},
}

_V9_REQUIRED_FOREIGN_PARENTS = {
    "agent_profile_versions": {"agent_profiles"},
    "task_contracts": {"agent_profile_versions", "projects"},
    "context_authority_grants": {"task_contracts", "projects"},
    "context_authority_revocations": {"context_authority_grants"},
    "context_compilations": {"task_contracts", "context_authority_grants", "projects"},
    "context_candidate_receipts": {"context_compilations"},
    "context_retention_grants": {"projects"},
    "context_pack_variants": {"context_compilations", "context_retention_grants"},
    "context_variant_candidate_receipts": {"context_compilations", "context_pack_variants"},
    "context_retained_payloads": {"context_pack_variants"},
    "context_outcomes": {"context_compilations", "context_authority_grants", "projects"},
    "context_attribution_edges": {"context_outcomes", "context_candidate_receipts"},
    "context_benchmark_runs": {"projects"},
    "context_benchmark_metrics": {"context_benchmark_runs"},
}

_V9_TRIGGER_FINGERPRINTS = {
    'agent_profile_versions_active_guard': '1f04116ec5c203a0e1d6a6da9642547d1cc86d8bd975b892dcdf3eb3f8fc6966',
    'agent_profile_versions_no_delete': '108af3ee53b8363f3077627252b5a51c5c8aea2949781b418d6e0f90a376781d',
    'agent_profile_versions_no_update': '9f35c10ad3e0d9d1374ec6a3c20e9c54b5d31dda6e9d042eaa586b2743205df3',
    'agent_profiles_identity_guard': '8828e6e4befa30896c0a4b42fd95f0d1b6cbebf8a59c85731485fd7be7ad1105',
    'agent_profiles_no_delete': '40819d9fcee0dae1b7dab32e83a60c21b6457af7b783a5ac2727aad2f1b5a160',
    'agent_profiles_retirement_guard': '1d0dc24c7aadcbf3194fe9f18dfdb86eecd30011835266fed2e4a554b0e4c4b9',
    'context_attribution_authority_guard': '089a98066cce74b6cd5cb3e28c043ca5324e3b7e825f1893034a8cd41d408985',
    'context_attribution_edges_no_delete': '9ff9bd843a0f9c51151be3bccf8b069d72e4f0b75653ba6e61292dd5ed743952',
    'context_attribution_edges_no_update': '5b135218eb55484fdaa892805eedaf25622e7cf4d228973ff134a27997ff455c',
    'context_authority_grants_contract_guard': '74c429136460d03ff96882d22ee7367ab3f4d481ace899ce2bb1a65988c53c63',
    'context_authority_grants_no_delete': 'bab20c8cf8d09a4eac11b9f12d9ec115947df4704c46613d9a37f446bdd7489b',
    'context_authority_grants_no_update': '00f403519c2198238796a4d11d930455d27985678b3f60660fbaad4ad35ffab6',
    'context_authority_revocations_no_delete': '81b7628cf4eeae64728ab7c1e1d989a6167a94aafcb9b513e52e40fa16a39847',
    'context_authority_revocations_no_update': 'd7f03962143751e7c8c1fa24e7f605fefe9ad6a37503183f94e95861e7bf0927',
    'context_authority_revocations_time_guard': '23a6c256f2e9e5d40be65c76875140756fe22402915d0f5bb1c08b23f0087068',
    'context_benchmark_metrics_building_guard': '4beb8b0c345ca6d536a749978b9d102db8a017dff9f87e20d29ed39fa55bb522',
    'context_benchmark_metrics_no_delete': '512d627e929fae9583bc0215be5520b43597737ca90a1f9fb8f2e5e7738444fc',
    'context_benchmark_metrics_no_update': 'd674ea190ddb2a7b3e662b498c324131b6cbbf9766f3eea53a856f2d68a32630',
    'context_benchmark_runs_building_insert_guard': '9db2335a929c2cf018cc5d2621ca9fe8efd610d2c83ddbe76ece7d8922e44a6a',
    'context_benchmark_runs_finalize_guard': 'dc049791d02081b1c2f6fa26ea6ba7bf2bc98d3eb6c2c71fad28b6646598a2ff',
    'context_benchmark_runs_no_delete': 'a0aee6a5b3e0b6fbfe318370803bd4966830abac447477dc1c1dc51fa3705239',
    'context_candidate_receipts_no_delete': 'be98fc9123a78d1ba1152443dd92c6a1b27260bc12a231ff5958a267cdf51c93',
    'context_candidate_receipts_no_update': '374f83c218d00f338d7442844db27a3f0ae059fd938b2af0d373a9b7f4a239c9',
    'context_candidates_building_guard': 'b26d0898bfb78e31f7faa02c93604bb9399fda0d0716eaa06c766168e000a377',
    'context_compilations_building_insert_guard': 'a3c1e86fe44d96cb49be8a8c2b11b0002421f93eddccfee2cf3d6977652038df',
    'context_compilations_finalize_guard': '99ce78992ebadd05ca48f972e8569415b13bf69faccef721f22a60c279ecaaaf',
    'context_compilations_no_delete': '53e39aef6dc4d8613b1ae2dc58fc63fecd99bba2a59f798135f14aecfad72612',
    'context_outcomes_no_delete': '52144c087a866bba24e20ba5ad40e908928ca737e6d64c61a1f939595c8cbd1b',
    'context_outcomes_no_update': '2e73a5407163b4a5b0de05d95c491c980b36de2581a94b13b101f3e3630ed8c6',
    'context_outcomes_authority_guard': '20349456df800cffd37bb975cd8d5adb7eaf475a3723978d2fdfc820d8c8dad2',
    'context_outcomes_terminal_guard': '177b12700fe1c2773aebbd81ba621d27a237d49c558c76b3551af1fde7616581',
    'context_pack_variants_no_delete': 'b6a542d9a0f071a9e48c452093b18df27a026627319d5965f61d502327af06e5',
    'context_pack_variants_no_update': '8e8d43f76c83c016bc93d864f7c0bf55c1fc9a30993483f807293bcd9feefb9a',
    'context_retained_payloads_insert_guard': '5a88029f2b425391041f0a95941b309d81f396b0292153bfbc9108be2be0c06c',
    'context_retained_payloads_no_update': 'cd4cc0967f17ee53e38a0b84bba58c212e8ca7eebea4e915ca0c25a703f93bc6',
    'context_retention_grants_no_delete': '5c49fadc01a487c89e3ae2093b16ef7bc97a486373c6e339d55ac6f78ecd42fb',
    'context_retention_grants_no_update': '561ec2bc8049704333815784f61d883b2ca220481e5b9527042a46ab0038e533',
    'context_variants_building_guard': 'caa7d06686426ca5c6f14ae006b9d1c0db57841052aeef9584dd920f272ae860',
    'context_variant_candidates_building_guard': '26e544f6c322a634289e99ff7c2f7fc609a9179bf85a3298c34aaf60aa16f0ff',
    'context_variant_candidate_receipts_no_delete': 'e01895f56ff9780f2e5e5b3b7b43934bd71b2871e8ebe19a4b8ef94cc3c95fcc',
    'context_variant_candidate_receipts_no_update': '67476bafc4aa803aa244a7297bc570bbc50175c1f08bc7900c5c2c8639ecba92',
    'task_contracts_active_profile_guard': '8a903690f36f6044a6259f542a57117afae94c65e73aa1547b1c800da9bc59ef',
    'task_contracts_no_delete': '87a117184f3a7e15208991ed05426d259b76b170531bc8b15312975a465f4cb6',
    'task_contracts_no_update': 'd37a37e21473cf778dff8e657276387766a4d681189fc36e90eaad53d2eca892',
}

_V9_TABLE_FINGERPRINTS = {
    'agent_profile_versions': '525f64bbc9a4ca72630a1fad0fddb416dd237b6ae698b74dc8e585b5d29fbaaf',
    'agent_profiles': '1f41dd921aa3c66e0482bd27ba3bfdc5301c4ca622e6618f3a6884ffea1c14b3',
    'context_attribution_edges': '4d2a73da55ced4d768ee6c4fe83626d545c9166ddc1d53b69fc0bef5f9b5c6bb',
    'context_authority_grants': '1fc573c3ed2127771fe3df60245077b577905173617d8cb11898e9229c9f8207',
    'context_authority_revocations': '3ca3c777cb72b4b74b2ddf95350f93cf97f9cffee975301d2a112f7903d82f1b',
    'context_benchmark_metrics': '36b34aa4a1f3f274ef364bba208c503ef57630d90748a74c4d5fe1f7abfb5d83',
    'context_benchmark_runs': 'f2cb2e02094ef88019ad2fbf7132165d5ba7455024a02d2ed4f3696dae7c733c',
    'context_candidate_receipts': 'a037d917d3565aae0503cbd6a8966b3721d48bfc3a235710d16fef40dd9bef38',
    'context_compilations': '4cfcc50c8fc71faabbcf3d1e49d8becba327e47d014e8222f496ba906865444a',
    'context_outcomes': '7a75850320b68d2a8f84bc1d2d493f1db2e3963b2783892fd0803c227e124028',
    'context_pack_variants': 'fa3e28f8443c1394727d7c0cfbb9e625e567d514c3da466040c19cadd5418ee7',
    'context_variant_candidate_receipts': '731db4d9cfc8aefb9ddf701aa7dd769f4fb3889deb94e5e5e0c16e4353b08289',
    'context_retained_payloads': 'e439deb4324e0c8deca1fcf964135d6d2ffdc1933fb5242e68418cf254abf022',
    'context_retention_grants': '6f0f938e93d09f8577ffe85b0892ce09aa0b0ac34efc0e76790796d3595cfbf3',
    'task_contracts': '1297caceb2c4dff755fd7ff355dcce978e3f7d3de40db1049cdf4385ea5dac83',
}

_V9_INDEX_FINGERPRINTS = {
    'idx_agent_profiles_project': 'b836e6fd823f47b9593b83f8df1196f6c358f45b5fb27e686ef43baa71ff9905',
    'idx_context_authority_grants_contract': 'a651bf331080bdec683b88f8c87cd1ae6145b8b3e5d6ae87f93fdd1b01a89132',
    'idx_context_authority_revocations_project': 'b8fa79a170519fb94a9933bf88171ae7117b9e9a502d0e9c0a975fd4ef27576b',
    'idx_context_benchmarks_project_created': '3f4567c92382bb37558ba5b85e88d468f4b3e14cf1f47e2ecfc5ea69f387637f',
    'idx_context_candidates_compilation': '2268721db5efc903cb25fe6ba684f2500233d51c44590b0885a96c370cb65188',
    'idx_context_variant_candidates_variant': '5df46ffb572435cf30701ae539929735543af274b5f557eff7fd2dddfaeb4c5a',
    'idx_context_compilations_project_created': 'c8ba4e56f82a5aef9d246f207c786b681126de90ed92ed04879de736b0764b7a',
    'idx_context_outcomes_project_created': '6b5975e3fe4117f9db0e9e4011e9c1115785d199d0288b3de02f38f6e0721017',
    'idx_task_contracts_project_created': '61b8b9f8f695d17cf442188aa0ca31c28d6c1fbc4bc74cc730d359cba1dea5e8',
}


def _schema_sql_fingerprint(sql: str) -> str:
    normalized = re.sub(r"\s+", " ", sql.strip()).replace(
        " IF NOT EXISTS ", " "
    ).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _validate_context_schema_v9(
    conn: sqlite3.Connection, *, include_triggers: bool = True
) -> None:
    if set(_V9_REQUIRED_COLUMNS) != set(_V9_TABLE_FINGERPRINTS):
        raise RuntimeError("internal schema v9 table fingerprint registry is incomplete")
    for table, required in _V9_REQUIRED_COLUMNS.items():
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not required.issubset(columns):
            missing = ", ".join(sorted(required - columns))
            raise ValueError(f"invalid schema v9 collision for {table}: missing {missing}")
        parents = {
            row["table"] for row in conn.execute(f"PRAGMA foreign_key_list({table})")
        }
        expected_parents = _V9_REQUIRED_FOREIGN_PARENTS.get(table, set())
        if not expected_parents.issubset(parents):
            missing = ", ".join(sorted(expected_parents - parents))
            raise ValueError(f"invalid schema v9 collision for {table}: missing FK {missing}")
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if table_sql is None or _schema_sql_fingerprint(table_sql["sql"]) != _V9_TABLE_FINGERPRINTS[table]:
            raise ValueError(f"invalid schema v9 collision: unsafe table {table}")
    if not include_triggers:
        return
    indexes = {
        row["name"]: row["sql"] or ""
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")
    }
    for name, expected in _V9_INDEX_FINGERPRINTS.items():
        if name not in indexes or _schema_sql_fingerprint(indexes[name]) != expected:
            raise ValueError(f"invalid schema v9 collision: unsafe index {name}")
    required_triggers = {
        f"{table}_{action}"
        for table in _APPEND_ONLY_TABLES
        for action in ("no_update", "no_delete")
    } | {
        "agent_profiles_identity_guard",
        "agent_profiles_retirement_guard",
        "agent_profiles_no_delete",
        "agent_profile_versions_active_guard",
        "task_contracts_active_profile_guard",
        "context_authority_grants_contract_guard",
        "context_authority_revocations_time_guard",
        "context_compilations_building_insert_guard",
        "context_compilations_finalize_guard",
        "context_compilations_no_delete",
        "context_candidates_building_guard",
        "context_variants_building_guard",
        "context_variant_candidates_building_guard",
        "context_retained_payloads_insert_guard",
        "context_retained_payloads_no_update",
        "context_outcomes_terminal_guard",
        "context_outcomes_authority_guard",
        "context_attribution_authority_guard",
        "context_benchmark_runs_building_insert_guard",
        "context_benchmark_runs_finalize_guard",
        "context_benchmark_runs_no_delete",
        "context_benchmark_metrics_building_guard",
    }
    trigger_rows = list(
        conn.execute(
            "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'"
        )
    )
    triggers = {row["name"]: row["sql"] or "" for row in trigger_rows}
    missing_triggers = sorted(required_triggers - set(triggers))
    if missing_triggers:
        raise ValueError(f"invalid schema v9 collision: missing trigger {missing_triggers[0]}")
    governed_triggers = {
        row["name"]
        for row in trigger_rows
        if row["tbl_name"] in _V9_REQUIRED_COLUMNS
    }
    unexpected_triggers = sorted(governed_triggers - required_triggers)
    if unexpected_triggers:
        raise ValueError(
            f"invalid schema v9 collision: unexpected trigger {unexpected_triggers[0]}"
        )
    if required_triggers != set(_V9_TRIGGER_FINGERPRINTS):
        raise RuntimeError("internal schema v9 trigger fingerprint registry is incomplete")
    for name in required_triggers:
        if _schema_sql_fingerprint(triggers[name]) != _V9_TRIGGER_FINGERPRINTS[name]:
            raise ValueError(f"invalid schema v9 collision: unsafe trigger {name}")


def validate_context_schema_v9(conn: sqlite3.Connection) -> None:
    """Reject a database that claims v9 without the required structural contract."""
    _validate_context_schema_v9(conn)


def migrate_context_schema_v9(conn: sqlite3.Connection) -> None:
    """Create the append-only context compiler receipt schema in the caller's transaction."""
    for statement in _TABLE_STATEMENTS:
        conn.execute(statement)
    _validate_context_schema_v9(conn, include_triggers=False)
    for statement in _INDEX_STATEMENTS:
        conn.execute(statement)
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS agent_profiles_identity_guard
        BEFORE UPDATE ON agent_profiles
        WHEN NEW.project_id != OLD.project_id
          OR NEW.profile_id != OLD.profile_id
          OR NEW.created_at != OLD.created_at
        BEGIN
            SELECT RAISE(ABORT, 'agent profile identity is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS agent_profile_versions_active_guard
        BEFORE INSERT ON agent_profile_versions
        WHEN EXISTS(
            SELECT 1 FROM agent_profiles
            WHERE id = NEW.agent_profile_id AND retired_at IS NOT NULL
        )
        BEGIN
            SELECT RAISE(ABORT, 'retired agent profile cannot receive versions');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS task_contracts_active_profile_guard
        BEFORE INSERT ON task_contracts
        WHEN EXISTS(
            SELECT 1 FROM agent_profile_versions v
            JOIN agent_profiles p ON p.id = v.agent_profile_id
            WHERE v.id = NEW.agent_profile_version_id AND p.retired_at IS NOT NULL
        )
        BEGIN
            SELECT RAISE(ABORT, 'retired agent profile cannot authorize new contracts');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_authority_grants_contract_guard
        BEFORE INSERT ON context_authority_grants
        WHEN NOT EXISTS(
            SELECT 1 FROM task_contracts
            WHERE id = NEW.task_contract_id
              AND project_id = NEW.project_id
              AND authorization_state = 'operator_authorized'
              AND actor_type = 'operator'
        )
        BEGIN
            SELECT RAISE(ABORT, 'authority grants require an operator-authorized project contract');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_authority_revocations_time_guard
        BEFORE INSERT ON context_authority_revocations
        WHEN NOT EXISTS(
            SELECT 1 FROM context_authority_grants
            WHERE id = NEW.authority_grant_id
              AND project_id = NEW.project_id
              AND task_contract_id = NEW.task_contract_id
              AND capability_digest = NEW.capability_digest
              AND NEW.revoked_at_epoch_ms >= issued_at_epoch_ms
        )
        BEGIN
            SELECT RAISE(ABORT, 'authority revocation must match an issued capability');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_compilations_building_insert_guard
        BEFORE INSERT ON context_compilations
        WHEN NEW.status != 'building'
          OR NOT EXISTS(
              SELECT 1 FROM task_contracts
              WHERE id = NEW.task_contract_id
                AND project_id = NEW.project_id
                AND digest = NEW.contract_digest
                AND profile_digest = NEW.profile_digest
                AND authorization_state = 'operator_authorized'
                AND actor_type = 'operator'
          )
          OR NOT EXISTS(
              SELECT 1 FROM context_authority_grants g
              WHERE g.id = NEW.authority_grant_id
                AND g.project_id = NEW.project_id
                AND g.task_contract_id = NEW.task_contract_id
                AND CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)
                    BETWEEN g.issued_at_epoch_ms AND g.expires_at_epoch_ms - 1
                AND NOT EXISTS(
                    SELECT 1 FROM context_authority_revocations r
                    WHERE r.authority_grant_id = g.id
                )
          )
        BEGIN
            SELECT RAISE(ABORT, 'new context compilations require building state and operator authority');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_compilations_finalize_guard
        BEFORE UPDATE ON context_compilations
        WHEN NOT (
            OLD.status = 'building'
            AND NEW.status IN ('complete', 'abstained', 'failed')
            AND OLD.receipt_digest IS NULL AND NEW.receipt_digest IS NOT NULL
            AND OLD.finalized_at IS NULL AND NEW.finalized_at IS NOT NULL
            AND NEW.id = OLD.id
            AND NEW.compilation_id = OLD.compilation_id
            AND NEW.project_id = OLD.project_id
            AND NEW.task_contract_id = OLD.task_contract_id
            AND NEW.authority_grant_id = OLD.authority_grant_id
            AND NEW.contract_digest = OLD.contract_digest
            AND NEW.profile_digest = OLD.profile_digest
            AND NEW.envelope_digest = OLD.envelope_digest
            AND NEW.snapshot_digest = OLD.snapshot_digest
            AND NEW.compiler_version = OLD.compiler_version
            AND NEW.compiler_mode = OLD.compiler_mode
            AND NEW.effective_budget_json = OLD.effective_budget_json
            AND NEW.created_at = OLD.created_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'context compilation finalization is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_compilations_no_delete
        BEFORE DELETE ON context_compilations
        BEGIN
            SELECT RAISE(ABORT, 'context_compilations is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_candidates_building_guard
        BEFORE INSERT ON context_candidate_receipts
        WHEN COALESCE((SELECT status FROM context_compilations WHERE id = NEW.compilation_id), '') != 'building'
        BEGIN
            SELECT RAISE(ABORT, 'candidate receipts require a building compilation');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_variants_building_guard
        BEFORE INSERT ON context_pack_variants
        WHEN COALESCE((SELECT status FROM context_compilations WHERE id = NEW.compilation_id), '') != 'building'
        BEGIN
            SELECT RAISE(ABORT, 'pack variants require a building compilation');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_variant_candidates_building_guard
        BEFORE INSERT ON context_variant_candidate_receipts
        WHEN NOT EXISTS(
            SELECT 1
            FROM context_pack_variants v
            JOIN context_compilations c ON c.id = NEW.compilation_id
            WHERE v.id = NEW.pack_variant_id
              AND v.compilation_id = NEW.compilation_id
              AND c.status = 'building'
        )
        BEGIN
            SELECT RAISE(ABORT, 'variant candidate receipts require their building compilation');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_retained_payloads_insert_guard
        BEFORE INSERT ON context_retained_payloads
        WHEN NOT EXISTS(
            SELECT 1
            FROM context_pack_variants v
            JOIN context_retention_grants g ON g.id = NEW.retention_grant_id
            WHERE v.id = NEW.pack_variant_id
              AND v.project_id = NEW.project_id
              AND v.retention_grant_id = NEW.retention_grant_id
              AND length(CAST(NEW.payload_text AS BLOB)) <= g.max_payload_bytes
              AND CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)
                  BETWEEN g.valid_from_epoch_ms AND g.expires_at_epoch_ms - 1
              AND NEW.created_at_epoch_ms >= g.valid_from_epoch_ms
              AND NEW.expires_at_epoch_ms
                  > CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)
              AND NEW.expires_at_epoch_ms <= g.expires_at_epoch_ms
              AND CASE v.privacy_class
                    WHEN 'public' THEN 0 WHEN 'internal' THEN 1
                    WHEN 'sensitive' THEN 2 ELSE 3 END
                  <= CASE g.max_privacy_class
                    WHEN 'public' THEN 0 WHEN 'internal' THEN 1
                    WHEN 'sensitive' THEN 2 ELSE 3 END
        )
        BEGIN
            SELECT RAISE(ABORT, 'retained payload exceeds its authorization grant');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_retained_payloads_no_update
        BEFORE UPDATE ON context_retained_payloads
        BEGIN
            SELECT RAISE(ABORT, 'retained payloads cannot be changed; delete after expiry');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_outcomes_terminal_guard
        BEFORE INSERT ON context_outcomes
        WHEN NOT EXISTS(
            SELECT 1 FROM context_compilations
            WHERE id = NEW.compilation_id
              AND status IN ('complete', 'abstained', 'failed')
              AND receipt_digest IS NOT NULL
              AND finalized_at IS NOT NULL
        )
        BEGIN
            SELECT RAISE(ABORT, 'outcomes require a terminal compilation receipt');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_outcomes_authority_guard
        BEFORE INSERT ON context_outcomes
        WHEN NEW.attribution_level = 'operator_confirmed'
          AND NOT EXISTS(
              SELECT 1
              FROM context_authority_grants g
              JOIN context_compilations c
                ON c.id = NEW.compilation_id
               AND c.project_id = NEW.project_id
               AND c.task_contract_id = g.task_contract_id
              WHERE g.id = NEW.authority_grant_id
                AND g.project_id = NEW.project_id
                AND json_extract(g.claims_json, '$.principal_type') = 'operator'
                AND json_extract(g.claims_json, '$.principal_id') = NEW.actor_id
                AND EXISTS(
                    SELECT 1 FROM json_each(g.claims_json, '$.scopes')
                    WHERE value = 'confirm:outcome'
                )
                AND CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)
                    BETWEEN g.issued_at_epoch_ms AND g.expires_at_epoch_ms - 1
                AND NOT EXISTS(
                    SELECT 1 FROM context_authority_revocations r
                    WHERE r.authority_grant_id = g.id
                )
          )
        BEGIN
            SELECT RAISE(ABORT, 'operator-confirmed outcomes require active operator authority');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_attribution_authority_guard
        BEFORE INSERT ON context_attribution_edges
        WHEN NOT EXISTS(
            SELECT 1 FROM context_outcomes o
            WHERE o.id = NEW.outcome_id
              AND (
                  NEW.attribution_level = 'observed'
                  OR (NEW.attribution_level = 'correlated'
                      AND o.attribution_level IN ('correlated', 'operator_confirmed'))
                  OR (NEW.attribution_level = 'operator_confirmed'
                      AND o.attribution_level = 'operator_confirmed'
                      AND json_type(NEW.evidence_json) = 'object'
                      AND json(NEW.evidence_json) != '{}')
              )
        )
        BEGIN
            SELECT RAISE(ABORT, 'attribution cannot exceed its outcome authority');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_benchmark_runs_building_insert_guard
        BEFORE INSERT ON context_benchmark_runs
        WHEN NEW.status != 'building'
        BEGIN
            SELECT RAISE(ABORT, 'benchmark runs must begin in building state');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_benchmark_runs_finalize_guard
        BEFORE UPDATE ON context_benchmark_runs
        WHEN NOT (
            OLD.status = 'building'
            AND NEW.status IN ('complete', 'failed')
            AND OLD.receipt_digest IS NULL AND NEW.receipt_digest IS NOT NULL
            AND OLD.finalized_at IS NULL AND NEW.finalized_at IS NOT NULL
            AND NEW.id = OLD.id
            AND NEW.project_id IS OLD.project_id
            AND NEW.run_id = OLD.run_id
            AND NEW.corpus_id = OLD.corpus_id
            AND NEW.compiler_version = OLD.compiler_version
            AND NEW.profile_digest = OLD.profile_digest
            AND NEW.contract_digest = OLD.contract_digest
            AND NEW.environment_json = OLD.environment_json
            AND NEW.created_at = OLD.created_at
        )
        BEGIN
            SELECT RAISE(ABORT, 'benchmark run finalization is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_benchmark_runs_no_delete
        BEFORE DELETE ON context_benchmark_runs
        BEGIN
            SELECT RAISE(ABORT, 'context_benchmark_runs is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS context_benchmark_metrics_building_guard
        BEFORE INSERT ON context_benchmark_metrics
        WHEN COALESCE((SELECT status FROM context_benchmark_runs WHERE id = NEW.run_id), '') != 'building'
        BEGIN
            SELECT RAISE(ABORT, 'benchmark metrics require a building run');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS agent_profiles_retirement_guard
        BEFORE UPDATE OF retired_at ON agent_profiles
        WHEN OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
        BEGIN
            SELECT RAISE(ABORT, 'agent profile retirement is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS agent_profiles_no_delete
        BEFORE DELETE ON agent_profiles
        BEGIN
            SELECT RAISE(ABORT, 'agent profiles are immutable');
        END
        """
    )
    for table in _APPEND_ONLY_TABLES:
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_no_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} is immutable');
            END
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table}_no_delete
            BEFORE DELETE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} is immutable');
            END
            """
        )
    _validate_context_schema_v9(conn)


def _count(conn: sqlite3.Connection, sql: str, parameters: tuple[Any, ...]) -> int:
    return int(conn.execute(sql, parameters).fetchone()[0])


def _describe_v8_compatibility_unlocked(
    conn: sqlite3.Connection, *, project: str
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, name, root_path FROM projects WHERE name = ?", (project,)
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown project: {project}")
    project_id = int(row["id"])
    omitted_v9 = {
        "agent_profiles": _count(
            conn, "SELECT COUNT(*) FROM agent_profiles WHERE project_id = ?", (project_id,)
        ),
        "agent_profile_versions": _count(
            conn,
            """SELECT COUNT(*) FROM agent_profile_versions v
               JOIN agent_profiles p ON p.id = v.agent_profile_id
               WHERE p.project_id = ?""",
            (project_id,),
        ),
        "task_contracts": _count(
            conn, "SELECT COUNT(*) FROM task_contracts WHERE project_id = ?", (project_id,)
        ),
        "context_compilations": _count(
            conn,
            "SELECT COUNT(*) FROM context_compilations WHERE project_id = ?",
            (project_id,),
        ),
        "context_candidate_receipts": _count(
            conn,
            """SELECT COUNT(*) FROM context_candidate_receipts r
               JOIN context_compilations c ON c.id = r.compilation_id
               WHERE c.project_id = ?""",
            (project_id,),
        ),
        "context_pack_variants": _count(
            conn,
            """SELECT COUNT(*) FROM context_pack_variants v
               JOIN context_compilations c ON c.id = v.compilation_id
               WHERE c.project_id = ?""",
            (project_id,),
        ),
        "context_variant_candidate_receipts": _count(
            conn,
            """SELECT COUNT(*) FROM context_variant_candidate_receipts r
               JOIN context_pack_variants v ON v.id = r.pack_variant_id
               JOIN context_compilations c ON c.id = v.compilation_id
               WHERE c.project_id = ?""",
            (project_id,),
        ),
        "context_retention_grants": _count(
            conn,
            "SELECT COUNT(*) FROM context_retention_grants WHERE project_id = ?",
            (project_id,),
        ),
        "context_retained_payloads": _count(
            conn,
            "SELECT COUNT(*) FROM context_retained_payloads WHERE project_id = ?",
            (project_id,),
        ),
        "context_outcomes": _count(
            conn, "SELECT COUNT(*) FROM context_outcomes WHERE project_id = ?", (project_id,)
        ),
        "context_attribution_edges": _count(
            conn,
            """SELECT COUNT(*) FROM context_attribution_edges e
               JOIN context_outcomes o ON o.id = e.outcome_id
               WHERE o.project_id = ?""",
            (project_id,),
        ),
        "context_benchmark_runs": _count(
            conn,
            "SELECT COUNT(*) FROM context_benchmark_runs WHERE project_id = ?",
            (project_id,),
        ),
        "context_benchmark_metrics": _count(
            conn,
            """SELECT COUNT(*) FROM context_benchmark_metrics m
               JOIN context_benchmark_runs r ON r.id = m.run_id
               WHERE r.project_id = ?""",
            (project_id,),
        ),
    }
    return {
        "operation": "v8_compatibility_omission_manifest",
        "schema_version": 8,
        "project": {"name": row["name"], "canonical_root_bound": bool(row["root_path"])},
        "omitted_v9": omitted_v9,
    }


def describe_v8_compatibility(
    conn: sqlite3.Connection, *, project: str
) -> dict[str, Any]:
    """Return one snapshot-consistent manifest; this does not export project payloads."""
    savepoint = "rta_v8_compatibility_snapshot"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        result = _describe_v8_compatibility_unlocked(conn, project=project)
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        return result
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise
