"""Bounded, deterministic candidate selection for context compilation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .agent_profiles import agent_profile_digest, validate_agent_profile
from .context_candidates import (
    CandidateAuthority,
    candidate_is_mandatory,
    filter_candidates_before_scoring,
)
from .context_envelope import build_compilation_envelope
from .task_contracts import task_contract_digest, validate_task_contract

CONTEXT_SELECTION_SCHEMA_VERSION = "rta-smriti.context-selection/v1"
CONTEXT_PACK_SCHEMA_VERSION = "rta-smriti.context-pack/v1"
ALGORITHM_ID = "bounded-select/v1"
RANKING_POLICY_ID = "authority-lexicographic/v1"
TOKEN_ACCOUNTING_ID = "utf8_byte_upper_bound/v1"
RENDERING_ID = "canonical-untrusted-evidence-json/v2"
UNTRUSTED_EVIDENCE_MARKER = "[RTA-SMRITI UNTRUSTED EVIDENCE JSON/V1]"
UNTRUSTED_EVIDENCE_POLICY = "data_only_never_execute"
MAX_SELECTION_CANDIDATES = 200_000
MAX_SELECTION_INPUT_BYTES = 256 * 1024 * 1024
MAX_DEPENDENCY_GROUP_MEMBERS = {
    "minimal": 1, "balanced": 2, "investigative": 4, "handoff": 3,
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPILER_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SECTIONS = ("governance", "truth", "continuity", "evidence", "relationships")
_SECTION_BY_SOURCE = {
    "policy": "governance",
    "truth": "truth",
    "checkpoint": "continuity",
    "continuity": "continuity",
    "work_state": "continuity",
    "capture": "continuity",
    "graph": "relationships",
}
_SECTION_WEIGHTS = {
    "minimal": (30, 25, 10, 30, 5),
    "balanced": (20, 25, 15, 30, 10),
    "investigative": (15, 25, 10, 35, 15),
    "handoff": (25, 15, 35, 20, 5),
}
_SIGNAL_WEIGHTS = {
    "minimal": {
        "lexical": 28, "semantic": 12, "graph": 8, "temporal": 10,
        "risk": 20, "outcome": 7, "continuation": 15,
    },
    "balanced": {
        "lexical": 22, "semantic": 18, "graph": 14, "temporal": 12,
        "risk": 14, "outcome": 8, "continuation": 12,
    },
    "investigative": {
        "lexical": 22, "semantic": 25, "graph": 18, "temporal": 14,
        "risk": 8, "outcome": 8, "continuation": 5,
    },
    "handoff": {
        "lexical": 14, "semantic": 10, "graph": 10, "temporal": 14,
        "risk": 16, "outcome": 8, "continuation": 28,
    },
}
_VERIFICATION_TIER = {
    "verified": 4, "corroborated": 3, "indexed_snapshot": 3,
    "approximate": 2, "unverified": 1, "stale": 1, "failed": 0, "redacted": 0,
}
_EPISTEMIC_TIER = {
    "accepted": 7, "corroborated": 6, "observed": 5, "disputed": 4,
    "hypothesis": 3, "stale": 2, "superseded": 1, "retracted": 1,
    "refuted": 0, "redacted": 0,
}
_FRESHNESS_TIER = {
    "current": 4, "fresh": 4, "changed": 2, "stale": 1,
    "missing": 0, "invalid": 0, "redacted": 0,
}
_BLOCKING_RISKS = {"consequential", "security_sensitive", "release_critical"}
_PRIVATE_BLOCKING_REASONS = {
    "mandatory_candidate_excluded_before_scoring",
    "contradiction_cohort_incomplete",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8", errors="strict")).hexdigest()


def _charged_tokens(text: str) -> int:
    return len(text.encode("utf-8", errors="strict"))


def _signal_micros(value: float) -> int:
    return int(
        (Decimal(str(value)) * Decimal(1_000_000)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP,
        )
    )


def _authority_tier(candidate: dict[str, Any]) -> int:
    authority = candidate["authority_class"].casefold()
    if authority in {"operator_checkpoint", "operator_decision", "operator"}:
        return 7
    if authority == "governance_policy":
        return 6
    if authority in {
        "system_checkpoint", "structured_work_state", "indexed_repository",
        "memory:pratyaksha", "legacy:pratyaksha",
    }:
        return 5
    if authority in {"memory:sabda", "legacy:sabda", "session_event"}:
        return 4
    if authority in {"memory:anumana", "legacy:anumana"}:
        return 3
    if authority in {"memory:smriti", "legacy:smriti"}:
        return 2
    if (
        authority in {
            "agent_checkpoint", "derived_graph", "memory:kalpana", "legacy:kalpana",
        }
        or authority.startswith(("agent-", "agent:"))
    ):
        return 1
    return 0


def _component_scores(candidate: dict[str, Any], mode: str) -> dict[str, Any]:
    signal_micros = {
        name: _signal_micros(candidate["signals"][name])
        for name in _SIGNAL_WEIGHTS[mode]
    }
    weighted_signal = sum(
        signal_micros[name] * weight
        for name, weight in _SIGNAL_WEIGHTS[mode].items()
    ) // 100
    return {
        "authority_tier": _authority_tier(candidate),
        "verification_tier": _VERIFICATION_TIER.get(
            candidate["verification_status"].casefold(), 0,
        ),
        "epistemic_tier": _EPISTEMIC_TIER.get(candidate["epistemic_state"].casefold(), 0),
        "freshness_tier": _FRESHNESS_TIER.get(candidate["freshness"].casefold(), 0),
        "signal_micros": signal_micros,
        "weighted_signal_micros": weighted_signal,
    }


def _score_micros(components: dict[str, Any]) -> int:
    return (
        components["authority_tier"] * 10**16
        + components["verification_tier"] * 10**14
        + components["epistemic_tier"] * 10**12
        + components["freshness_tier"] * 10**10
        + components["weighted_signal_micros"]
    )


def _section(candidate: dict[str, Any]) -> str:
    return _SECTION_BY_SOURCE.get(candidate["source_type"], "evidence")


def _section_budgets(total: int, mode: str) -> dict[str, int]:
    weights = _SECTION_WEIGHTS[mode]
    allocations = {
        section: total * weight // 100
        for section, weight in zip(_SECTIONS, weights, strict=True)
    }
    remainders = sorted(
        (
            (-(total * weight % 100), index, section)
            for index, (section, weight) in enumerate(zip(_SECTIONS, weights, strict=True))
        )
    )
    for _fraction, _index, section in remainders[: total - sum(allocations.values())]:
        allocations[section] += 1
    return allocations


def _input_size(candidate: dict[str, Any]) -> int:
    return sum(
        len(value.encode("utf-8", errors="strict"))
        for value in (
            str(candidate.get("candidate_id") or ""),
            str(candidate.get("source_id") or ""),
            str(candidate.get("source_version") or ""),
            str(candidate.get("minimum_excerpt") or ""),
            str(candidate.get("expanded_excerpt") or ""),
            _canonical(candidate.get("provenance_chain") or []),
            _canonical(candidate.get("validator_state") or {}),
        )
    )


def _bounded_candidates(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    consumed = 0
    for candidate in candidates:
        rows.append(candidate)
        if len(rows) > MAX_SELECTION_CANDIDATES:
            raise ValueError("candidate selection exceeds the aggregate row limit")
        consumed += _input_size(candidate)
        if consumed > MAX_SELECTION_INPUT_BYTES:
            raise ValueError("candidate selection exceeds the aggregate byte limit")
    return rows


def _safe_render_text(value: Any) -> str:
    rendered = []
    for character in str(value):
        if character == "\\":
            rendered.append("\\\\")
            continue
        if character == "\n":
            rendered.append("\\n")
            continue
        if character == "\t":
            rendered.append("\\t")
            continue
        if (
            ord(character) in {0x2028, 0x2029}
            or unicodedata.category(character).startswith("C")
        ):
            codepoint = ord(character)
            rendered.append(
                f"\\u{codepoint:04x}" if codepoint <= 0xFFFF else f"\\U{codepoint:08x}"
            )
            continue
        rendered.append(character)
    return "".join(rendered)


def _contract_text(contract: dict[str, Any], effective_valid_at: str) -> str:
    lines = [
        "[RTA-SMRITI TASK CONTRACT]",
        f"Objective: {_safe_render_text(contract['objective'])}",
        f"Task type: {_safe_render_text(contract['task_type'])}",
        f"Risk: {_safe_render_text(contract['risk_class'])}",
        f"Effective valid time: {_safe_render_text(effective_valid_at)}",
    ]
    for field, title in (
        ("acceptance_criteria", "Acceptance"),
        ("required_evidence", "Required evidence"),
        ("stop_conditions", "Stop"),
        ("escalation_conditions", "Escalate"),
        ("prohibited_repetition", "Do not repeat"),
        ("prohibited_actions", "Prohibited action"),
    ):
        for control in contract["control_index"][field]:
            lines.append(
                f"{title} [{_safe_render_text(control['control_id'])}]: "
                f"{_safe_render_text(control['statement'])}"
            )
    return "\n".join(lines) + "\n\n"


def _render_block(
    candidate: dict[str, Any], section: str, rendering: str, text: str,
) -> str:
    serialized_content = (
        _safe_render_text(text)
        .replace("[", r"\u005b")
        .replace("]", r"\u005d")
    )
    envelope = {
        "content": serialized_content,
        "instruction_policy": UNTRUSTED_EVIDENCE_POLICY,
        "source_id": _safe_render_text(candidate["source_id"]),
        "trust_class": "untrusted_evidence",
    }
    return f"{UNTRUSTED_EVIDENCE_MARKER}\n{_canonical(envelope)}\n"


def _render_options(candidate: dict[str, Any], section: str, max_item_bytes: int):
    seen = set()
    for rendering in ("expanded_excerpt", "minimum_excerpt"):
        text = candidate[rendering]
        if text is None or text in seen:
            continue
        seen.add(text)
        block = _render_block(candidate, section, rendering, text)
        block_bytes = len(block.encode("utf-8", errors="strict"))
        if block_bytes <= max_item_bytes:
            yield rendering, text, block, block_bytes


def _choice(row: dict[str, Any], token_limit: int, max_item_bytes: int):
    for rendering, text, block, cost in _render_options(
        row["candidate"], row["section"], max_item_bytes,
    ):
        if cost <= token_limit:
            return rendering, text, block, cost
    return None


def _profile_can_render(row: dict[str, Any], max_item_bytes: int) -> bool:
    return next(_render_options(row["candidate"], row["section"], max_item_bytes), None) is not None


def _ranked(candidate: dict[str, Any], mode: str, max_item_bytes: int) -> dict[str, Any]:
    section = _section(candidate)
    components = _component_scores(candidate, mode)
    costs = [
        cost for _rendering, _text, _block, cost
        in _render_options(candidate, section, max_item_bytes)
    ]
    return {
        "candidate": candidate,
        "section": section,
        "component_scores": components,
        "score_micros": _score_micros(components),
        "minimum_cost": min(costs) if costs else 2**63 - 1,
        "mandatory": candidate_is_mandatory(candidate),
    }


def _rank_key(row: dict[str, Any]):
    components = row["component_scores"]
    return (
        -int(row["mandatory"]),
        -components["authority_tier"],
        -components["verification_tier"],
        -components["epistemic_tier"],
        -components["freshness_tier"],
        -components["weighted_signal_micros"],
        row["minimum_cost"],
        row["candidate"]["source_type"],
        row["candidate"]["candidate_id"],
    )


def _selection_receipt(
    row: dict[str, Any], disposition: str, *, rendering: str | None = None,
    token_cost: int = 0, reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    candidate = row["candidate"]
    return {
        "stage": "selection",
        "candidate_id": candidate["candidate_id"],
        "source_id": candidate["source_id"],
        "disposition": disposition,
        "section": row["section"],
        "score_micros": row["score_micros"],
        "component_scores": json.loads(_canonical(row["component_scores"])),
        "token_cost": token_cost,
        "privacy_class": candidate["privacy_class"],
        "rendering": rendering,
        "reason_codes": list(reason_codes or []),
    }


def _selected_row(
    row: dict[str, Any], disposition: str, rendering: str, text: str,
    rendered_text: str, token_cost: int,
) -> dict[str, Any]:
    candidate = row["candidate"]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_id": candidate["source_id"],
        "source_type": candidate["source_type"],
        "content_ref": candidate["content_ref"],
        "section": row["section"],
        "disposition": disposition,
        "rendering": rendering,
        "text": text,
        "rendered_text": rendered_text,
        "token_cost": token_cost,
        "score_micros": row["score_micros"],
        "component_scores": json.loads(_canonical(row["component_scores"])),
    }


def _pre_score_receipts(excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(candidate["hard_disposition"] or "redacted" for candidate in excluded)
    return [
        {
            "stage": "pre_score", "disposition": disposition, "count": count,
            "reason_codes": ["excluded_before_scoring"],
        }
        for disposition, count in sorted(counts.items())
    ]


def select_context_candidates(
    candidates: Iterable[dict[str, Any]], *, contract: dict[str, Any],
    profile: dict[str, Any], authority: str, profile_authority: str,
    candidate_authority: CandidateAuthority, snapshot_digest: str,
    compiler_version: str, compiler_mode_override: str | None = None,
) -> dict[str, Any]:
    """Select authorized evidence without executing tools or mutating source state."""
    if not isinstance(snapshot_digest, str) or not _SHA256.fullmatch(snapshot_digest):
        raise ValueError("snapshot_digest must be a lowercase SHA-256 digest")
    if not isinstance(compiler_version, str) or not _COMPILER_VERSION.fullmatch(compiler_version):
        raise ValueError("compiler_version is invalid")

    normalized_contract = validate_task_contract(contract, authority=authority)
    normalized_profile = validate_agent_profile(profile)
    if normalized_contract["scope"]["projects"] != [normalized_contract["project"]]:
        raise ValueError("v0.8 context compilation requires a single-project contract")
    envelope = build_compilation_envelope(
        normalized_contract, normalized_profile, authority=authority,
        profile_authority=profile_authority,
    )
    effective_valid_at = normalized_contract["scope"]["valid_at"] or normalized_contract["created_at"]
    filter_contract = json.loads(_canonical(normalized_contract))
    filter_contract["scope"]["valid_at"] = effective_valid_at
    bounded = _bounded_candidates(candidates)
    filtered = filter_candidates_before_scoring(
        bounded, contract=filter_contract, profile=normalized_profile,
        authority=authority, profile_authority=profile_authority,
        candidate_authority=candidate_authority,
    )
    mode = normalized_contract["compiler_mode"]
    if compiler_mode_override is not None:
        requested_mode = str(compiler_mode_override or "").strip().casefold()
        if requested_mode not in normalized_contract["comparison_modes"]:
            raise PermissionError("compiler comparison mode is not operator authorized")
        mode = requested_mode
    ranked = sorted(
        (
            _ranked(candidate, mode, normalized_profile["max_item_bytes"])
            for candidate in filtered["scorable"]
        ),
        key=_rank_key,
    )
    candidate_set_digest = _digest(sorted(
        candidate["candidate_id"] for candidate in filtered["scorable"]
    ))

    receipts = _pre_score_receipts(filtered["excluded"])
    duplicate_winners: dict[str, dict[str, Any]] = {}
    eligible = []
    for row in ranked:
        candidate = row["candidate"]
        if row["mandatory"]:
            eligible.append(row)
            continue
        contradiction = candidate["contradiction_group"]
        duplicate_key = candidate["duplicate_group"] or f"content:{candidate['content_hash']}"
        if duplicate_key in duplicate_winners and not contradiction:
            receipts.append(_selection_receipt(
                row, "excluded_duplicate", reason_codes=["duplicate_lower_rank"],
            ))
            continue
        if not contradiction:
            duplicate_winners[duplicate_key] = row
        eligible.append(row)

    total_budget = envelope["effective_budget"]["available_context_tokens"]
    contract_text = _contract_text(normalized_contract, effective_valid_at)
    contract_tokens = _charged_tokens(contract_text)
    candidate_budget = max(0, total_budget - contract_tokens)
    section_budget = _section_budgets(candidate_budget, mode)
    section_used = {section: 0 for section in _SECTIONS}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    dependency_counts: Counter[str] = Counter()
    used_candidates = 0
    blocking_reasons: list[str] = []

    if contract_tokens > total_budget:
        blocking_reasons = ["task_contract_exceeds_budget"]
    elif filtered["blocking_counts"]["mandatory_excluded"]:
        blocking_reasons = ["mandatory_candidate_excluded_before_scoring"]
    elif (
        filtered["blocking_counts"]["incomplete_contradiction_groups"]
        and normalized_contract["risk_class"] in _BLOCKING_RISKS
    ):
        blocking_reasons = ["contradiction_cohort_incomplete"]

    def add_selected(row: dict[str, Any], disposition: str, choice, reason: str) -> None:
        nonlocal used_candidates
        rendering, text, block, cost = choice
        selected.append(_selected_row(row, disposition, rendering, text, block, cost))
        receipts.append(_selection_receipt(
            row, disposition, rendering=rendering, token_cost=cost, reason_codes=[reason],
        ))
        selected_ids.add(row["candidate"]["candidate_id"])
        used_candidates += cost
        section_used[row["section"]] += cost
        dependency_group = row["candidate"]["dependency_group"]
        if dependency_group:
            dependency_counts[dependency_group] += 1

    mandatory = [row for row in eligible if row["mandatory"]]
    for row in mandatory if not blocking_reasons else []:
        choice = _choice(
            row, candidate_budget - used_candidates, normalized_profile["max_item_bytes"],
        )
        if choice is None:
            blocking_reasons = [
                "mandatory_candidate_exceeds_budget"
                if _profile_can_render(row, normalized_profile["max_item_bytes"])
                else "mandatory_candidate_profile_incompatible"
            ]
            break
        add_selected(row, "included_mandatory", choice, "host_control_plane_mandatory")

    contradiction_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        group = row["candidate"]["contradiction_group"]
        if group and row["candidate"]["candidate_id"] not in selected_ids:
            contradiction_rows[group].append(row)
    cohorts = [
        (min(_rank_key(row) for row in cohort), group, cohort)
        for group, cohort in contradiction_rows.items()
        if len(cohort) > 1
    ]
    cohorts.sort(key=lambda item: (item[0], item[1]))
    ungrouped = [
        row
        for row in eligible
        if not row["candidate"]["contradiction_group"]
        or len(contradiction_rows[row["candidate"]["contradiction_group"]]) < 2
    ]
    ungrouped_index = 0
    for cohort_rank, _group, cohort in cohorts if not blocking_reasons else []:
        while (
            ungrouped_index < len(ungrouped)
            and _rank_key(ungrouped[ungrouped_index]) < cohort_rank
        ):
            row = ungrouped[ungrouped_index]
            ungrouped_index += 1
            if row["candidate"]["candidate_id"] in selected_ids:
                continue
            choice = _choice(
                row,
                candidate_budget - used_candidates,
                normalized_profile["max_item_bytes"],
            )
            if choice is not None:
                add_selected(row, "included_ranked", choice, "authority_precedes_cohort")
        choices = []
        remaining = candidate_budget - used_candidates
        for row in cohort:
            choice = _choice(row, remaining, normalized_profile["max_item_bytes"])
            if choice is None:
                choices = []
                break
            choices.append((row, choice))
            remaining -= choice[3]
        if not choices:
            material = any(
                row["component_scores"]["authority_tier"] >= 3
                or row["component_scores"]["verification_tier"] >= 3
                for row in cohort
            )
            if normalized_contract["risk_class"] in _BLOCKING_RISKS and material:
                blocking_reasons = ["contradiction_cohort_exceeds_budget"]
                break
            for row in cohort:
                receipts.append(_selection_receipt(
                    row, "excluded_budget", reason_codes=["contradiction_cohort_atomic_omission"],
                ))
            continue
        for row, choice in choices:
            add_selected(row, "included_ranked", choice, "contradiction_cohort_atomic")

    if blocking_reasons:
        selected = []
        selected_ids.clear()
        used_candidates = 0
        section_used = {section: 0 for section in _SECTIONS}
        receipts = [
            receipt for receipt in receipts
            if receipt["stage"] == "pre_score"
            or receipt["disposition"] not in {
                "included_mandatory", "included_ranked", "summarized_dependency",
            }
        ]
        existing = {
            receipt.get("candidate_id")
            for receipt in receipts if receipt["stage"] == "selection"
        }
        for row in eligible:
            if row["candidate"]["candidate_id"] not in existing:
                receipts.append(_selection_receipt(
                    row, "excluded_budget", reason_codes=["compilation_abstained"],
                ))
    else:
        regular = [
            row for row in eligible
            if row["candidate"]["candidate_id"] not in selected_ids
            and not (
                row["candidate"]["contradiction_group"]
                and len(contradiction_rows[row["candidate"]["contradiction_group"]]) > 1
            )
        ]
        dependency_cap = MAX_DEPENDENCY_GROUP_MEMBERS[mode]

        def try_select(row: dict[str, Any], limit: int, reason: str) -> bool:
            dependency_group = row["candidate"]["dependency_group"]
            if dependency_group and dependency_counts[dependency_group] >= dependency_cap:
                return False
            choice = _choice(
                row, min(limit, candidate_budget - used_candidates),
                normalized_profile["max_item_bytes"],
            )
            if choice is None:
                return False
            add_selected(row, "included_ranked", choice, reason)
            return True

        for section in _SECTIONS:
            remaining = max(0, section_budget[section] - section_used[section])
            for row in (candidate for candidate in regular if candidate["section"] == section):
                if remaining <= 0:
                    break
                before = used_candidates
                if try_select(row, remaining, "section_coverage"):
                    remaining -= used_candidates - before

        for row in regular:
            candidate_id = row["candidate"]["candidate_id"]
            if candidate_id in selected_ids:
                continue
            if (
                used_candidates < candidate_budget
                and try_select(row, candidate_budget - used_candidates, "deterministic_spillover")
            ):
                continue
            dependency_group = row["candidate"]["dependency_group"]
            if not _profile_can_render(row, normalized_profile["max_item_bytes"]):
                disposition = "excluded_profile_incompatible"
                reason = "agent_profile_item_limit"
            elif dependency_group and dependency_counts[dependency_group] >= dependency_cap:
                disposition = "excluded_low_marginal_utility"
                reason = "dependency_group_diversity_cap"
            else:
                disposition = "excluded_budget"
                reason = "no_complete_rendering_fits"
            receipts.append(_selection_receipt(row, disposition, reason_codes=[reason]))

    selected.sort(key=lambda row: (
        0 if row["disposition"] == "included_mandatory" else 1,
        -row["score_micros"],
        row["candidate_id"],
    ))
    receipts.sort(key=lambda row: (
        0 if row["stage"] == "pre_score" else 1,
        str(row.get("candidate_id") or ""),
        row["disposition"],
    ))

    contradiction_totals = Counter(
        row["candidate"]["contradiction_group"]
        for row in eligible if row["candidate"]["contradiction_group"]
    )
    contradiction_selected = Counter(
        row["candidate"]["contradiction_group"]
        for row in eligible
        if row["candidate"]["candidate_id"] in selected_ids
        and row["candidate"]["contradiction_group"]
    )
    observed_groups = {group for group, count in contradiction_totals.items() if count > 1}
    preserved_groups = {
        group for group in observed_groups
        if contradiction_selected[group] == contradiction_totals[group]
    }
    warnings: list[str] = []
    if (
        filtered["blocking_counts"]["incomplete_contradiction_groups"]
        or observed_groups != preserved_groups
    ):
        warnings.append("contradiction_coverage_degraded")
    status = "abstained" if blocking_reasons or not selected else "complete"
    if not selected and not blocking_reasons:
        blocking_reasons = ["no_eligible_candidates" if not eligible else "no_candidate_fits_budget"]
    section_selected = Counter(row["section"] for row in selected)
    section_eligible = Counter(row["section"] for row in eligible)
    emitted_contract_text = contract_text if contract_tokens <= total_budget else ""
    emitted_contract_tokens = contract_tokens if emitted_contract_text else 0
    used = emitted_contract_tokens + used_candidates
    body = {
        "schema_version": CONTEXT_SELECTION_SCHEMA_VERSION,
        "algorithm_id": ALGORITHM_ID,
        "ranking_policy_id": RANKING_POLICY_ID,
        "token_accounting_id": TOKEN_ACCOUNTING_ID,
        "rendering_id": RENDERING_ID,
        "unicode_version": unicodedata.unidata_version,
        "status": status,
        "compiler_version": compiler_version,
        "compiler_mode": mode,
        "snapshot_digest": snapshot_digest,
        "contract_digest": task_contract_digest(normalized_contract, authority=authority),
        "profile_digest": agent_profile_digest(normalized_profile),
        "envelope_digest": envelope["envelope_digest"],
        "candidate_set_digest": candidate_set_digest,
        "effective_valid_at": effective_valid_at,
        "contract_text": emitted_contract_text,
        "budget": {
            "available_tokens": total_budget,
            "control_tokens": emitted_contract_tokens,
            "required_control_tokens": contract_tokens,
            "candidate_budget_tokens": candidate_budget,
            "candidate_tokens": used_candidates,
            "used_tokens": used,
            "remaining_tokens": max(0, total_budget - used),
            "section_allocations": section_budget,
            "section_used": section_used,
            "token_estimator": TOKEN_ACCOUNTING_ID,
        },
        "selected": selected,
        "receipts": receipts,
        "coverage": {
            "input_candidates": len(bounded),
            "pre_score_excluded": len(filtered["excluded"]),
            "eligible_candidates": len(eligible),
            "selected_candidates": len(selected),
            "omitted_candidates": max(0, len(bounded) - len(selected)),
            "section_eligible": {section: section_eligible[section] for section in _SECTIONS},
            "section_selected": {section: section_selected[section] for section in _SECTIONS},
            "contradiction_groups": len(observed_groups),
            "contradiction_groups_preserved": len(preserved_groups),
            "contradictions_preserved": bool(observed_groups and observed_groups == preserved_groups),
            "incomplete_private_contradiction_groups": filtered["blocking_counts"][
                "incomplete_contradiction_groups"
            ],
            "token_utilization_micros": used * 1_000_000 // total_budget,
        },
        "warnings": warnings,
        "blocking_reasons": blocking_reasons,
    }
    body["selection_digest"] = _digest(body)
    return json.loads(_canonical(body))


def build_consumer_context_pack(selection: dict[str, Any]) -> dict[str, Any]:
    """Project an operator selection receipt into a privacy-safe agent context pack."""
    if not isinstance(selection, dict):
        raise TypeError("selection must be an object")
    if selection.get("schema_version") != CONTEXT_SELECTION_SCHEMA_VERSION:
        raise ValueError("selection schema version is invalid")
    supplied_digest = selection.get("selection_digest")
    if not isinstance(supplied_digest, str) or not _SHA256.fullmatch(supplied_digest):
        raise ValueError("selection digest is invalid")
    digest_body = json.loads(_canonical(selection))
    digest_body.pop("selection_digest", None)
    if _digest(digest_body) != supplied_digest:
        raise ValueError("selection integrity check failed")

    selected = []
    rendered = []
    for row in selection.get("selected", []):
        if not isinstance(row, dict):
            raise TypeError("selected context row must be an object")
        block = row.get("rendered_text")
        if not isinstance(block, str):
            raise TypeError("selected context row is missing rendered text")
        rendered.append(block)
        selected.append({
            "candidate_id": row["candidate_id"],
            "source_id": _safe_render_text(row["source_id"]),
            "source_type": _safe_render_text(row["source_type"]),
            "content_ref": row["content_ref"],
            "section": _safe_render_text(row["section"]),
            "rendering": _safe_render_text(row["rendering"]),
            "text": (
                _safe_render_text(row["text"])
                .replace("[", r"\u005b")
                .replace("]", r"\u005d")
            ),
            "trust_class": "untrusted_evidence",
            "instruction_policy": UNTRUSTED_EVIDENCE_POLICY,
        })
    blocking_reasons = []
    for reason in selection.get("blocking_reasons", []):
        visible = (
            "authorization_or_evidence_incomplete"
            if reason in _PRIVATE_BLOCKING_REASONS
            else reason
        )
        if visible not in blocking_reasons:
            blocking_reasons.append(visible)
    warnings = []
    if "contradiction_coverage_degraded" in selection.get("warnings", []):
        warnings.append("coverage_degraded")
    budget = selection["budget"]
    body = {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "status": selection["status"],
        "compiler_version": selection["compiler_version"],
        "compiler_mode": selection["compiler_mode"],
        "snapshot_digest": selection["snapshot_digest"],
        "contract_digest": selection["contract_digest"],
        "profile_digest": selection["profile_digest"],
        "envelope_digest": selection["envelope_digest"],
        "effective_valid_at": selection["effective_valid_at"],
        "context_text": selection["contract_text"] + "".join(rendered),
        "selected": selected,
        "budget": {
            "available_tokens": budget["available_tokens"],
            "used_tokens": budget["used_tokens"],
            "remaining_tokens": budget["remaining_tokens"],
            "token_estimator": budget["token_estimator"],
        },
        "warnings": warnings,
        "blocking_reasons": blocking_reasons,
    }
    body["context_pack_digest"] = _digest(body)
    return json.loads(_canonical(body))
