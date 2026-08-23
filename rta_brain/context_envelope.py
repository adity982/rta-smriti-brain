"""Authorized, digest-bound input envelope for deterministic context compilation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .agent_profiles import (
    PRIVACY_LEVELS,
    agent_profile_digest,
    builtin_agent_profile,
    validate_agent_profile,
)
from .task_contracts import (
    MIN_COMPILABLE_TOKENS,
    task_contract_digest,
    validate_task_contract,
)

COMPILATION_ENVELOPE_SCHEMA_VERSION = "rta-smriti.compilation-envelope/v1"


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _effective_budget(contract: dict[str, Any], profile: dict[str, Any]) -> dict[str, int]:
    requested = contract["budgets"]
    profile_max = profile["max_input_tokens"]
    maximum = int(requested["max_input_tokens"])
    if profile_max is not None and maximum > int(profile_max):
        raise ValueError("contract max_input_tokens exceeds agent profile max_input_tokens")
    for field in ("reserved_output_tokens", "host_overhead_tokens", "tool_overhead_tokens"):
        if int(requested[field]) != int(profile[field]):
            raise ValueError(f"contract {field} conflicts with agent profile")
    reserve = int(requested["reserved_output_tokens"])
    host = int(requested["host_overhead_tokens"])
    tools = int(requested["tool_overhead_tokens"])
    safety = int(requested["safety_margin_tokens"])
    available = maximum - reserve - host - tools - safety
    if available < MIN_COMPILABLE_TOKENS:
        raise ValueError(
            "effective contract/profile budget leaves fewer than 256 tokens for compiled input"
        )
    return {
        "max_input_tokens": maximum,
        "reserved_output_tokens": reserve,
        "host_overhead_tokens": host,
        "tool_overhead_tokens": tools,
        "safety_margin_tokens": safety,
        "available_context_tokens": available,
    }


def build_compilation_envelope(
    contract: dict[str, Any],
    profile: dict[str, Any],
    *,
    authority: str = "agent",
    profile_authority: str = "host",
) -> dict[str, Any]:
    """Bind normalized authority, profile limits, and budgets before any retrieval."""
    normalized_contract = validate_task_contract(contract, authority=authority)
    normalized_profile = validate_agent_profile(profile)
    selected_profile_authority = str(profile_authority or "").strip().lower()
    if selected_profile_authority not in {"operator", "host", "builtin"}:
        raise ValueError("profile_authority must be operator, host, or builtin")
    profile_source = normalized_profile["source"]
    if profile_source == "builtin" and normalized_profile != builtin_agent_profile(
        normalized_profile["profile_id"]
    ):
        raise ValueError("builtin profile body does not match the registered builtin profile")
    if profile_source == "host_observed":
        raise ValueError("raw host_observed profile cannot authorize a compilation envelope")
    if profile_source == "operator_declared" and (
        selected_profile_authority != "operator"
        or normalized_profile["verification_status"] != "verified"
    ):
        raise ValueError("operator_declared profile requires verified operator authority")
    if profile_source == "resolved":
        field_sources = normalized_profile["field_sources"]
        if (
            selected_profile_authority != "operator"
            or normalized_profile["verification_status"] != "verified"
            or field_sources["privacy_ceiling"] != "operator_verified"
            or field_sources["project_scopes"] != "operator_verified"
        ):
            raise ValueError("resolved profile grants require verified operator authority")
    if profile_source == "builtin" and selected_profile_authority != "builtin":
        raise ValueError("builtin profile requires builtin profile authority")
    if normalized_profile["profile_id"] != normalized_contract["agent_profile_id"]:
        raise ValueError("agent profile does not match task contract agent_profile_id")
    if (
        PRIVACY_LEVELS.index(normalized_contract["scope"]["privacy_ceiling"])
        > PRIVACY_LEVELS.index(normalized_profile["privacy_ceiling"])
    ):
        raise ValueError("task contract privacy ceiling exceeds the agent profile grant")
    profile_scopes = set(normalized_profile["project_scopes"])
    contract_scopes = set(normalized_contract["scope"]["projects"])
    if not profile_scopes:
        raise ValueError("agent profile grants no project scope")
    if not contract_scopes.issubset(profile_scopes):
        raise ValueError("task contract project scope exceeds the agent profile grant")

    body = {
        "schema_version": COMPILATION_ENVELOPE_SCHEMA_VERSION,
        "contract_digest": task_contract_digest(normalized_contract, authority=authority),
        "profile_digest": agent_profile_digest(normalized_profile),
        "authorization": normalized_contract["authorization"],
        "profile_authority": selected_profile_authority,
        "effective_budget": _effective_budget(normalized_contract, normalized_profile),
    }
    body["envelope_digest"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    return body
