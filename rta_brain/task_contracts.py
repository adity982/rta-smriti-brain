"""Strict, deterministic task contracts for context compilation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

TASK_CONTRACT_SCHEMA_VERSION = "rta-smriti.task-contract/v1"
RISK_CLASSES = frozenset(
    {"routine", "consequential", "security_sensitive", "release_critical"}
)
COMPILER_MODES = frozenset({"minimal", "balanced", "investigative", "handoff"})
COMPILER_MODE_ORDER = ("minimal", "balanced", "investigative", "handoff")
PRIVACY_LEVELS = ("public", "internal", "sensitive", "restricted")
ACTOR_TYPES = frozenset({"operator", "agent_proposal", "system"})
MIN_COMPILABLE_TOKENS = 256

_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "project",
        "objective",
        "task_type",
        "risk_class",
        "acceptance_criteria",
        "required_evidence",
        "stop_conditions",
        "escalation_conditions",
        "prohibited_repetition",
        "prohibited_actions",
        "scope",
        "informational_tool_grants",
        "agent_profile_id",
        "budgets",
        "compiler_mode",
        "created_at",
        "created_by",
        "authorization",
        "control_index",
        "comparison_modes",
    }
)
_SCOPE_FIELDS = frozenset(
    {
        "projects",
        "source_types",
        "privacy_ceiling",
        "valid_at",
        "recorded_sequence",
        "path_globs",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "max_input_tokens",
        "reserved_output_tokens",
        "host_overhead_tokens",
        "tool_overhead_tokens",
        "safety_margin_tokens",
    }
)
_ACTOR_FIELDS = frozenset({"actor_type", "actor_id"})
_AUTHORIZATION_FIELDS = frozenset({"state", "authorized_by", "authorized_at", "source"})
_CALLER_AUTHORITIES = frozenset({"operator", "agent", "system"})
_INFORMATIONAL_GRANT_PREFIXES = ("read:", "query:", "inspect:", "context:", "evidence:")
_CONTROL_COLLECTIONS = (
    ("acceptance_criteria", "accept"),
    ("required_evidence", "evidence"),
    ("stop_conditions", "stop"),
    ("escalation_conditions", "escalate"),
    ("prohibited_repetition", "repeat"),
    ("prohibited_actions", "action"),
)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} field: {unknown[0]}")


def _text(value: Any, name: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if required and not normalized:
        raise ValueError(f"{name} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum:,} characters")
    return normalized


def _string_list(
    value: Any,
    name: str,
    *,
    maximum_items: int,
    maximum_length: int,
    minimum_items: int = 0,
) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    if len(value) < minimum_items:
        raise ValueError(f"{name} requires at least {minimum_items} item")
    if len(value) > maximum_items:
        raise ValueError(f"{name} exceeds {maximum_items} items")
    normalized = [
        _text(item, f"{name} item", maximum=maximum_length, required=True)
        for item in value
    ]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} must contain unique items")
    return normalized


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int,
    nullable: bool = False,
) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:,} and {maximum:,}")
    return value


def _timestamp(value: Any, name: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    text = _text(value, name, maximum=64, required=True)
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        text,
    ):
        raise ValueError(
            f"{name} must use RFC 3339 with Z or +/-HH:MM and 1 to 6 fractional digits"
        )
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    normalized = parsed.astimezone(UTC)
    return normalized.isoformat(
        timespec="microseconds" if normalized.microsecond else "seconds"
    )


def _required(payload: dict[str, Any], field: str) -> Any:
    if field not in payload:
        raise ValueError(f"{field} is required")
    return payload[field]


def _relative_globs(values: list[str]) -> list[str]:
    portable = []
    for value in values:
        normalized = value.replace("\\", "/")
        if (
            normalized.startswith(("/", "//"))
            or re.match(r"^[A-Za-z]:", normalized)
            or ".." in normalized.split("/")
        ):
            raise ValueError("scope.path_globs must stay project-relative")
        portable.append(normalized)
    if len(portable) != len(set(portable)):
        raise ValueError("scope.path_globs must contain unique portable paths")
    return portable


def _build_control_index(contract: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = {}
    for field, prefix in _CONTROL_COLLECTIONS:
        rows = []
        for statement in contract[field]:
            digest = hashlib.sha256(
                f"{field}\0{statement}".encode("utf-8", errors="strict")
            ).hexdigest()[:16]
            rows.append({"control_id": f"{prefix}-{digest}", "statement": statement})
        index[field] = rows
    return index


def validate_task_contract(
    payload: dict[str, Any],
    *,
    authority: str = "agent",
) -> dict[str, Any]:
    """Validate and normalize one immutable task contract without mutating input."""
    contract = _mapping(payload, "task contract")
    _reject_unknown(contract, _ROOT_FIELDS, "task contract")
    caller_authority = str(authority or "").strip().lower()
    if caller_authority not in _CALLER_AUTHORITIES:
        raise ValueError("authority must be operator, agent, or system")
    if _required(contract, "schema_version") != TASK_CONTRACT_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {TASK_CONTRACT_SCHEMA_VERSION}")

    scope = _mapping(_required(contract, "scope"), "scope")
    _reject_unknown(scope, _SCOPE_FIELDS, "scope")
    privacy_ceiling = _text(
        _required(scope, "privacy_ceiling"),
        "scope.privacy_ceiling",
        maximum=32,
        required=True,
    ).lower()
    if privacy_ceiling not in PRIVACY_LEVELS:
        raise ValueError("scope.privacy_ceiling is invalid")

    budgets = _mapping(_required(contract, "budgets"), "budgets")
    _reject_unknown(budgets, _BUDGET_FIELDS, "budgets")
    normalized_budgets = {
        "max_input_tokens": _integer(
            _required(budgets, "max_input_tokens"),
            "budgets.max_input_tokens",
            minimum=256,
            maximum=1_000_000,
        ),
        "reserved_output_tokens": _integer(
            _required(budgets, "reserved_output_tokens"),
            "budgets.reserved_output_tokens",
            minimum=0,
            maximum=500_000,
        ),
        "host_overhead_tokens": _integer(
            budgets.get("host_overhead_tokens", 0),
            "budgets.host_overhead_tokens",
            minimum=0,
            maximum=500_000,
        ),
        "tool_overhead_tokens": _integer(
            budgets.get("tool_overhead_tokens", 0),
            "budgets.tool_overhead_tokens",
            minimum=0,
            maximum=500_000,
        ),
        "safety_margin_tokens": _integer(
            budgets.get("safety_margin_tokens", 128),
            "budgets.safety_margin_tokens",
            minimum=0,
            maximum=100_000,
        ),
    }
    available = (
        normalized_budgets["max_input_tokens"]
        - normalized_budgets["reserved_output_tokens"]
        - normalized_budgets["host_overhead_tokens"]
        - normalized_budgets["tool_overhead_tokens"]
        - normalized_budgets["safety_margin_tokens"]
    )
    if available < MIN_COMPILABLE_TOKENS:
        raise ValueError(
            "invalid budget arithmetic: at least 256 tokens must remain for compiled input"
        )

    created_by = _mapping(_required(contract, "created_by"), "created_by")
    _reject_unknown(created_by, _ACTOR_FIELDS, "created_by")
    actor_type = _text(
        _required(created_by, "actor_type"),
        "created_by.actor_type",
        maximum=32,
        required=True,
    ).lower()
    if actor_type not in ACTOR_TYPES:
        raise ValueError("created_by.actor_type is invalid")
    if actor_type == "operator" and caller_authority != "operator":
        raise ValueError("operator contract requires operator authority")
    if actor_type == "system" and caller_authority != "system":
        raise ValueError("system contract requires system authority")

    mode = _text(
        _required(contract, "compiler_mode"), "compiler_mode", maximum=32, required=True
    ).lower()
    if mode not in COMPILER_MODES:
        raise ValueError("compiler_mode is invalid")
    comparison_value = contract.get("comparison_modes", [])
    if not isinstance(comparison_value, list):
        raise TypeError("comparison_modes must be a list")
    if len(comparison_value) > 3:
        raise ValueError("comparison_modes exceeds 3 items")
    comparison_modes = [
        _text(value, "comparison_modes item", maximum=32, required=True).lower()
        for value in comparison_value
    ]
    if (
        len(set(comparison_modes)) != len(comparison_modes)
        or mode in comparison_modes
        or any(value not in COMPILER_MODES for value in comparison_modes)
    ):
        raise ValueError(
            "comparison_modes must contain unique supported modes other than compiler_mode"
        )
    comparison_modes.sort(key=COMPILER_MODE_ORDER.index)
    risk_class = _text(
        _required(contract, "risk_class"), "risk_class", maximum=32, required=True
    ).lower()
    if risk_class not in RISK_CLASSES:
        raise ValueError("risk_class is invalid")

    grants = _string_list(
        contract.get("informational_tool_grants", []),
        "informational_tool_grants",
        maximum_items=100,
        maximum_length=256,
    )
    if actor_type == "agent_proposal":
        if PRIVACY_LEVELS.index(privacy_ceiling) > PRIVACY_LEVELS.index("internal"):
            raise ValueError(
                "agent proposal cannot grant sensitive or restricted privacy"
            )
        if any(grant.casefold().startswith("owner:") for grant in grants):
            raise ValueError("agent proposal cannot grant owner capability")
    if any(
        not grant.casefold().startswith(_INFORMATIONAL_GRANT_PREFIXES)
        for grant in grants
    ):
        raise ValueError(
            "informational_tool_grants must name an informational read-only capability"
        )
    for grant in grants:
        prefix = grant.split(":", 1)[0]
        if prefix != prefix.casefold():
            raise ValueError(
                "informational_tool_grants require a lowercase canonical prefix"
            )

    project_name = _text(
        _required(contract, "project"), "project", maximum=200, required=True
    )
    scope_projects = _string_list(
        _required(scope, "projects"),
        "scope.projects",
        minimum_items=1,
        maximum_items=20,
        maximum_length=200,
    )
    if project_name not in scope_projects:
        raise ValueError("project must be included in scope.projects")
    if actor_type == "agent_proposal" and scope_projects != [project_name]:
        raise ValueError("agent proposal cannot grant cross-project scope")
    created_at = _timestamp(_required(contract, "created_at"), "created_at")
    actor_id = _text(
        _required(created_by, "actor_id"),
        "created_by.actor_id",
        maximum=256,
        required=True,
    )
    authorization = {
        "state": "operator_authorized" if actor_type == "operator" else "proposal",
        "authorized_by": actor_id if actor_type == "operator" else None,
        "authorized_at": created_at if actor_type == "operator" else None,
        "source": "operator_boundary"
        if actor_type == "operator"
        else "untrusted_proposal",
    }
    supplied_authorization = contract.get("authorization")
    if supplied_authorization is not None:
        supplied = _mapping(supplied_authorization, "authorization")
        _reject_unknown(supplied, _AUTHORIZATION_FIELDS, "authorization")
        if supplied != authorization:
            raise ValueError("authorization does not match caller authority")

    normalized_scope = {
        "projects": scope_projects,
        "source_types": _string_list(
            scope.get("source_types", []),
            "scope.source_types",
            maximum_items=50,
            maximum_length=128,
        ),
        "privacy_ceiling": privacy_ceiling,
        "valid_at": _timestamp(scope.get("valid_at"), "scope.valid_at", nullable=True),
        "recorded_sequence": _integer(
            scope.get("recorded_sequence"),
            "scope.recorded_sequence",
            minimum=0,
            maximum=9_223_372_036_854_775_807,
            nullable=True,
        ),
        "path_globs": _relative_globs(
            _string_list(
                scope.get("path_globs", []),
                "scope.path_globs",
                maximum_items=100,
                maximum_length=500,
            )
        ),
    }
    normalized = {
        "schema_version": TASK_CONTRACT_SCHEMA_VERSION,
        "contract_id": _text(
            _required(contract, "contract_id"),
            "contract_id",
            maximum=128,
            required=True,
        ),
        "project": project_name,
        "objective": _text(
            _required(contract, "objective"), "objective", maximum=10_000, required=True
        ),
        "task_type": _text(
            contract.get("task_type", "general"),
            "task_type",
            maximum=128,
            required=True,
        ),
        "risk_class": risk_class,
        "acceptance_criteria": _string_list(
            _required(contract, "acceptance_criteria"),
            "acceptance_criteria",
            minimum_items=1,
            maximum_items=100,
            maximum_length=2_000,
        ),
        "required_evidence": _string_list(
            contract.get("required_evidence", []),
            "required_evidence",
            maximum_items=100,
            maximum_length=1_000,
        ),
        "stop_conditions": _string_list(
            _required(contract, "stop_conditions"),
            "stop_conditions",
            minimum_items=1,
            maximum_items=100,
            maximum_length=2_000,
        ),
        "escalation_conditions": _string_list(
            contract.get("escalation_conditions", []),
            "escalation_conditions",
            maximum_items=100,
            maximum_length=2_000,
        ),
        "prohibited_repetition": _string_list(
            contract.get("prohibited_repetition", []),
            "prohibited_repetition",
            maximum_items=100,
            maximum_length=2_000,
        ),
        "prohibited_actions": _string_list(
            _required(contract, "prohibited_actions"),
            "prohibited_actions",
            minimum_items=1,
            maximum_items=100,
            maximum_length=256,
        ),
        "scope": normalized_scope,
        "informational_tool_grants": grants,
        "agent_profile_id": _text(
            _required(contract, "agent_profile_id"),
            "agent_profile_id",
            maximum=128,
            required=True,
        ),
        "budgets": normalized_budgets,
        "compiler_mode": mode,
        "comparison_modes": comparison_modes,
        "created_at": created_at,
        "created_by": {
            "actor_type": actor_type,
            "actor_id": actor_id,
        },
        "authorization": authorization,
    }
    control_index = _build_control_index(normalized)
    if (
        contract.get("control_index") is not None
        and contract["control_index"] != control_index
    ):
        raise ValueError("control_index does not match normalized control statements")
    normalized["control_index"] = control_index
    return normalized


def available_context_tokens(
    contract: dict[str, Any], *, authority: str = "agent"
) -> int:
    normalized = validate_task_contract(contract, authority=authority)
    budgets = normalized["budgets"]
    return int(
        budgets["max_input_tokens"]
        - budgets["reserved_output_tokens"]
        - budgets["host_overhead_tokens"]
        - budgets["tool_overhead_tokens"]
        - budgets["safety_margin_tokens"]
    )


def canonical_task_contract(
    contract: dict[str, Any], *, authority: str = "agent"
) -> str:
    normalized = validate_task_contract(contract, authority=authority)
    persistence_body = dict(normalized)
    if not persistence_body["comparison_modes"]:
        # Preserve the frozen v1 digest for contracts created before comparison variants.
        persistence_body.pop("comparison_modes")
    return json.dumps(
        persistence_body,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def task_contract_digest(contract: dict[str, Any], *, authority: str = "agent") -> str:
    return hashlib.sha256(
        canonical_task_contract(contract, authority=authority).encode("utf-8")
    ).hexdigest()
