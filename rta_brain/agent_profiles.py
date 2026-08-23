"""Conservative agent-consumption profiles with explicit authority precedence."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

AGENT_PROFILE_SCHEMA_VERSION = "rta-smriti.agent-profile/v1"
PROFILE_SOURCES = frozenset({"builtin", "host_observed", "operator_declared", "resolved"})
VERIFICATION_STATES = frozenset({"default", "observed", "verified"})
PRIVACY_LEVELS = ("public", "internal", "sensitive", "restricted")

_PROFILE_FIELDS = frozenset({
    "schema_version", "profile_id", "source", "verification_status",
    "input_modalities", "artifact_forms", "max_input_tokens",
    "reserved_output_tokens", "host_overhead_tokens", "tool_overhead_tokens",
    "tokenizer_family", "supports", "max_item_bytes", "max_attachment_bytes",
    "privacy_ceiling", "project_scopes", "rendering_conventions",
    "unsupported_features", "field_sources",
})
_SUPPORT_FIELDS = frozenset({
    "mcp_resources", "resource_links", "file_references", "structured_json",
})
_CAPABILITY_FIELDS = (
    "input_modalities", "artifact_forms", "max_input_tokens",
    "reserved_output_tokens", "host_overhead_tokens", "tool_overhead_tokens",
    "tokenizer_family", "supports", "max_item_bytes", "max_attachment_bytes",
    "rendering_conventions", "unsupported_features",
)
_GRANT_FIELDS = ("privacy_ceiling", "project_scopes")
_FIELD_SOURCE_VALUES = frozenset({"builtin", "host_observed", "operator_verified"})


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: frozenset[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {name} field: {unknown[0]}")


def _text(value: Any, name: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if required and not normalized:
        raise ValueError(f"{name} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum:,} characters")
    return normalized


def _string_list(value: Any, name: str, *, maximum_items: int, maximum_length: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if len(value) > maximum_items:
        raise ValueError(f"{name} exceeds {maximum_items} items")
    result = [_text(item, f"{name} item", maximum=maximum_length, required=True) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must contain unique items")
    return result


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
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:,} and {maximum:,}")
    return value


def validate_agent_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a source-specific profile and return a detached normalized value."""
    profile = _mapping(payload, "agent profile")
    _reject_unknown(profile, _PROFILE_FIELDS, "agent profile")
    if profile.get("schema_version") != AGENT_PROFILE_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {AGENT_PROFILE_SCHEMA_VERSION}")
    source = _text(profile.get("source"), "source", maximum=32, required=True).lower()
    if source not in PROFILE_SOURCES:
        raise ValueError("source is invalid")
    verification = _text(
        profile.get("verification_status"), "verification_status", maximum=32, required=True,
    ).lower()
    if verification not in VERIFICATION_STATES:
        raise ValueError("verification_status is invalid")
    privacy = _text(
        profile.get("privacy_ceiling", "internal"), "privacy_ceiling", maximum=32, required=True,
    ).lower()
    if privacy not in PRIVACY_LEVELS:
        raise ValueError("privacy_ceiling is invalid")

    supports = _mapping(profile.get("supports", {}), "supports")
    _reject_unknown(supports, _SUPPORT_FIELDS, "supports")
    normalized_supports = {}
    for field in sorted(_SUPPORT_FIELDS):
        value = supports.get(field, False)
        if not isinstance(value, bool):
            raise ValueError(f"supports.{field} must be a boolean")
        normalized_supports[field] = value

    tokenizer = profile.get("tokenizer_family")
    normalized_tokenizer = None if tokenizer is None else _text(
        tokenizer, "tokenizer_family", maximum=128, required=True,
    )
    normalized = {
        "schema_version": AGENT_PROFILE_SCHEMA_VERSION,
        "profile_id": _text(profile.get("profile_id"), "profile_id", maximum=128, required=True),
        "source": source,
        "verification_status": verification,
        "input_modalities": _string_list(
            profile.get("input_modalities", ["text"]), "input_modalities",
            maximum_items=16, maximum_length=64,
        ),
        "artifact_forms": _string_list(
            profile.get("artifact_forms", ["inline_text"]), "artifact_forms",
            maximum_items=32, maximum_length=64,
        ),
        "max_input_tokens": _integer(
            profile.get("max_input_tokens"), "max_input_tokens",
            minimum=256, maximum=1_000_000, nullable=True,
        ),
        "reserved_output_tokens": _integer(
            profile.get("reserved_output_tokens", 0), "reserved_output_tokens",
            minimum=0, maximum=500_000,
        ),
        "host_overhead_tokens": _integer(
            profile.get("host_overhead_tokens", 0), "host_overhead_tokens",
            minimum=0, maximum=500_000,
        ),
        "tool_overhead_tokens": _integer(
            profile.get("tool_overhead_tokens", 0), "tool_overhead_tokens",
            minimum=0, maximum=500_000,
        ),
        "tokenizer_family": normalized_tokenizer,
        "supports": normalized_supports,
        "max_item_bytes": _integer(
            profile.get("max_item_bytes", 64 * 1024), "max_item_bytes",
            minimum=1, maximum=16 * 1024 * 1024,
        ),
        "max_attachment_bytes": _integer(
            profile.get("max_attachment_bytes", 64 * 1024), "max_attachment_bytes",
            minimum=1, maximum=64 * 1024 * 1024,
        ),
        "privacy_ceiling": privacy,
        "project_scopes": _string_list(
            profile.get("project_scopes", []), "project_scopes",
            maximum_items=20, maximum_length=200,
        ),
        "rendering_conventions": _string_list(
            profile.get("rendering_conventions", ["plain_text"]), "rendering_conventions",
            maximum_items=32, maximum_length=128,
        ),
        "unsupported_features": _string_list(
            profile.get("unsupported_features", []), "unsupported_features",
            maximum_items=100, maximum_length=128,
        ),
    }
    field_sources = profile.get("field_sources")
    if source == "resolved":
        sources = _mapping(field_sources, "field_sources")
        expected_fields = frozenset((*_CAPABILITY_FIELDS, *_GRANT_FIELDS))
        _reject_unknown(sources, expected_fields, "field_sources")
        missing = sorted(expected_fields - set(sources))
        if missing:
            raise ValueError(f"field_sources is missing: {missing[0]}")
        normalized_sources = {}
        for field in sorted(expected_fields):
            selected = _text(
                sources[field], f"field_sources.{field}", maximum=32, required=True,
            ).lower()
            if selected not in _FIELD_SOURCE_VALUES:
                raise ValueError(f"field_sources.{field} is invalid")
            normalized_sources[field] = selected
        normalized["field_sources"] = normalized_sources
    elif field_sources is not None:
        raise ValueError("field_sources is only valid for a resolved profile")
    return normalized


def builtin_agent_profile(profile_id: str = "universal") -> dict[str, Any]:
    if str(profile_id).strip() != "universal":
        raise ValueError(f"unknown built-in agent profile: {profile_id}")
    return validate_agent_profile({
        "schema_version": AGENT_PROFILE_SCHEMA_VERSION,
        "profile_id": "universal",
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
        "max_item_bytes": 64 * 1024,
        "max_attachment_bytes": 64 * 1024,
        "privacy_ceiling": "internal",
        "project_scopes": [],
        "rendering_conventions": ["plain_text"],
        "unsupported_features": [],
    })


def resolve_agent_profile(
    profile_id: str = "universal",
    *,
    host_observed: dict[str, Any] | None = None,
    operator_verified: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve capabilities without allowing host observations to create grants."""
    base = builtin_agent_profile(profile_id)
    resolved = {key: value.copy() if isinstance(value, (dict, list)) else value for key, value in base.items()}
    if host_observed is None and operator_verified is None:
        return resolved
    field_sources = {
        field: "builtin"
        for field in (*_CAPABILITY_FIELDS, *_GRANT_FIELDS)
    }

    if host_observed is not None:
        observed = validate_agent_profile(host_observed)
        if observed["source"] != "host_observed" or observed["verification_status"] != "observed":
            raise ValueError("host profile must be host_observed and observed")
        if observed["profile_id"] != base["profile_id"]:
            raise ValueError("host profile_id must match the requested base profile")
        for field in _CAPABILITY_FIELDS:
            value = observed[field]
            resolved[field] = value.copy() if isinstance(value, (dict, list)) else value
            field_sources[field] = "host_observed"
        resolved["source"] = "resolved"
        resolved["verification_status"] = "observed"

    if operator_verified is not None:
        operator_payload = _mapping(operator_verified, "operator profile")
        if str(operator_payload.get("verification_status") or "").strip().lower() != "verified":
            raise ValueError("operator profile must be verified")
        operator = validate_agent_profile(operator_payload)
        if operator["source"] != "operator_declared":
            raise ValueError("operator profile must be operator_declared")
        if operator["profile_id"] != base["profile_id"]:
            raise ValueError("operator profile_id must match the requested base profile")
        for field in (*_CAPABILITY_FIELDS, *_GRANT_FIELDS):
            value = operator[field]
            resolved[field] = value.copy() if isinstance(value, (dict, list)) else value
            field_sources[field] = "operator_verified"
        resolved["source"] = "resolved"
        resolved["verification_status"] = "verified"

    resolved["field_sources"] = field_sources
    return resolved


def agent_profile_digest(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_agent_profile(profile).encode("utf-8")).hexdigest()


def canonical_agent_profile(profile: dict[str, Any]) -> str:
    normalized = validate_agent_profile(profile)
    return json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
