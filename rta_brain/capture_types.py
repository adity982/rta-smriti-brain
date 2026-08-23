"""Strict, dependency-free types for the universal capture bus."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .privacy import find_sensitive_text

CAPTURE_SCHEMA_VERSION = "rta-smriti.capture/v1"
CAPTURE_PROFILES = frozenset({"metadata-only", "continuity", "forensic"})
CAPTURE_PRIVACY_CLASSES = ("public", "internal", "sensitive", "restricted")
CAPTURE_VERIFICATION_STATES = frozenset({"unverified", "verified", "failed", "stale"})
CAPTURE_EVENT_NAMES = frozenset({
    "session.started.v1", "session.resumed.v1", "session.ended.v1",
    "turn.started.v1", "turn.completed.v1", "turn.interrupted.v1", "turn.compacted.v1",
    "prompt.submitted.v1", "agent.message.v1", "user.decision.v1", "user.approval.v1",
    "tool.requested.v1", "tool.started.v1", "tool.completed.v1", "tool.failed.v1",
    "command.started.v1", "command.completed.v1",
    "file.read.v1", "file.edited.v1",
    "mcp.requested.v1", "mcp.completed.v1",
    "automation.changed.v1", "checkpoint.created.v1",
    "adapter.heartbeat.v1", "adapter.error.v1", "capture.gap.v1", "vendor.event.v1",
})
CAPTURE_EVENT_HASH_FIELDS = (
    "actor_id", "actor_type", "attributes_json", "payload_row_id", "causation_event_id",
    "checkout_identity", "correlation_id", "dirty_digest", "event_id",
    "event_name", "external_event_id", "external_session_id", "gap_state",
    "idempotency_key", "normalized_sha256", "observed_at", "occurred_at",
    "original_bytes", "parent_span_id", "policy_digest", "previous_event_hash",
    "privacy_class", "project_id", "project_sequence", "recorded_at",
    "redaction_count", "repository_commit", "repository_identity",
    "repository_ref", "source_cursor", "source_id", "source_sha256",
    "span_id", "stored_bytes", "trace_id", "truncation_count",
    "verification_status",
)

DEFAULT_MAX_EVENT_BYTES = 256_000
DEFAULT_MAX_FIELD_CHARS = 16_000
DEFAULT_MAX_COLLECTION_ITEMS = 100


class _FrozenDict(dict):
    def _immutable(self, *_args, **_kwargs):
        raise TypeError("normalized capture attributes are immutable")

    __delitem__ = _immutable
    __ior__ = _immutable
    __setitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class _FrozenList(list):
    def _immutable(self, *_args, **_kwargs):
        raise TypeError("normalized capture attributes are immutable")

    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    __setitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _freeze_json(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_json(child) for child in value)
    return value


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("capture value is not finite canonical JSON") from exc


def capture_event_envelope(row: Mapping[str, Any]) -> dict[str, Any]:
    """Select the version-1 fields covered by a capture event hash."""

    return {key: row[key] for key in CAPTURE_EVENT_HASH_FIELDS}


def _required_text(name: str, value: Any, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    selected = value.strip()
    if not selected or len(selected) > maximum or "\0" in selected:
        raise ValueError(f"{name} must contain 1 to {maximum} safe characters")
    return selected


def _optional_text(name: str, value: Any, *, maximum: int = 512) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, maximum=maximum)


def _opaque_identifier(name: str, value: Any, *, length: int) -> str | None:
    selected = _optional_text(name, value, maximum=length)
    if selected is None:
        return None
    if len(selected) != length or any(character not in "0123456789abcdef" for character in selected):
        raise ValueError(f"{name} must be {length} lower-case hexadecimal characters")
    if set(selected) == {"0"}:
        raise ValueError(f"{name} must not be the all-zero identifier")
    return selected


def _strict_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class CapturePolicy:
    profile: str = "metadata-only"
    enabled_event_names: tuple[str, ...] = field(
        default_factory=lambda: tuple(sorted(CAPTURE_EVENT_NAMES - {"vendor.event.v1"}))
    )
    field_allowlist: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    privacy_ceiling: str = "internal"
    retain_payloads: bool = False
    retention_seconds: int = 30 * 24 * 60 * 60
    max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES
    max_field_chars: int = DEFAULT_MAX_FIELD_CHARS
    max_collection_items: int = DEFAULT_MAX_COLLECTION_ITEMS

    def __post_init__(self) -> None:
        if self.profile not in CAPTURE_PROFILES:
            raise ValueError(f"unsupported capture profile: {self.profile}")
        if self.privacy_ceiling not in CAPTURE_PRIVACY_CLASSES:
            raise ValueError(f"unsupported capture privacy ceiling: {self.privacy_ceiling}")
        if self.profile != "forensic" and self.retain_payloads:
            raise ValueError("payload retention requires the forensic capture profile")
        _strict_int("retention_seconds", self.retention_seconds, 0, 10 * 365 * 24 * 60 * 60)
        _strict_int("max_event_bytes", self.max_event_bytes, 1_024, 1_048_576)
        _strict_int("max_field_chars", self.max_field_chars, 256, 256_000)
        _strict_int("max_collection_items", self.max_collection_items, 1, 10_000)
        unknown = set(self.enabled_event_names).difference(CAPTURE_EVENT_NAMES)
        if unknown:
            raise ValueError(f"unsupported capture event names: {', '.join(sorted(unknown))}")
        for event_name, keys in self.field_allowlist.items():
            if event_name not in CAPTURE_EVENT_NAMES:
                raise ValueError(f"unsupported field allowlist event: {event_name}")
            if not all(isinstance(key, str) and key.strip() for key in keys):
                raise ValueError("capture field allowlist keys must be non-empty strings")

    @classmethod
    def metadata_only(cls) -> CapturePolicy:
        return cls(profile="metadata-only")

    @classmethod
    def continuity(cls) -> CapturePolicy:
        return cls(
            profile="continuity",
            field_allowlist={
                "prompt.submitted.v1": ("text", "role"),
                "agent.message.v1": ("text", "role", "event_kind"),
                "user.decision.v1": ("text", "decision"),
                "user.approval.v1": ("text", "decision", "scope"),
                "tool.completed.v1": ("tool", "status", "summary", "duration_ms"),
                "tool.failed.v1": ("tool", "status", "error_class", "summary", "duration_ms"),
                "command.completed.v1": ("command", "exit_code", "summary", "duration_ms"),
                "file.read.v1": ("path",),
                "file.edited.v1": ("path", "status"),
                "turn.interrupted.v1": ("reason", "summary"),
                "turn.compacted.v1": ("summary",),
                "capture.gap.v1": ("reason", "from_cursor", "to_cursor", "omitted_bytes"),
            },
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CAPTURE_SCHEMA_VERSION,
            "profile": self.profile,
            "enabled_event_names": sorted(self.enabled_event_names),
            "field_allowlist": {
                key: sorted(str(item) for item in value)
                for key, value in sorted(self.field_allowlist.items())
            },
            "privacy_ceiling": self.privacy_ceiling,
            "retain_payloads": bool(self.retain_payloads),
            "retention_seconds": int(self.retention_seconds),
            "max_event_bytes": int(self.max_event_bytes),
            "max_field_chars": int(self.max_field_chars),
            "max_collection_items": int(self.max_collection_items),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict()).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class CaptureEnvelope:
    adapter: str
    adapter_version: str
    event_name: str
    session_id: str
    source_cursor: str
    observed_at: str
    payload: Mapping[str, Any]
    external_event_id: str | None = None
    occurred_at: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    causation_event_id: str | None = None
    correlation_id: str | None = None
    actor_type: str = "agent"
    actor_id: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _required_text("adapter", self.adapter, maximum=64))
        object.__setattr__(self, "adapter_version", _required_text("adapter_version", self.adapter_version, maximum=64))
        selected_event = _required_text("event_name", self.event_name, maximum=128)
        if selected_event not in CAPTURE_EVENT_NAMES:
            raise ValueError(f"unsupported capture event name: {selected_event}")
        object.__setattr__(self, "event_name", selected_event)
        object.__setattr__(self, "session_id", _required_text("session_id", self.session_id, maximum=512))
        object.__setattr__(self, "source_cursor", _required_text("source_cursor", self.source_cursor, maximum=512))
        object.__setattr__(self, "observed_at", _required_text("observed_at", self.observed_at, maximum=64))
        object.__setattr__(self, "external_event_id", _optional_text("external_event_id", self.external_event_id, maximum=512))
        object.__setattr__(self, "occurred_at", _optional_text("occurred_at", self.occurred_at, maximum=64))
        object.__setattr__(self, "trace_id", _opaque_identifier("trace_id", self.trace_id, length=32))
        object.__setattr__(self, "span_id", _opaque_identifier("span_id", self.span_id, length=16))
        object.__setattr__(self, "parent_span_id", _opaque_identifier("parent_span_id", self.parent_span_id, length=16))
        object.__setattr__(self, "causation_event_id", _optional_text("causation_event_id", self.causation_event_id, maximum=512))
        object.__setattr__(self, "correlation_id", _optional_text("correlation_id", self.correlation_id, maximum=512))
        object.__setattr__(self, "actor_type", _required_text("actor_type", self.actor_type, maximum=64))
        object.__setattr__(self, "actor_id", _required_text("actor_id", self.actor_id, maximum=256))
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        canonical_json(dict(self.payload))


@dataclass(frozen=True)
class NormalizedEvent:
    event_name: str
    session_id: str
    source_cursor: str
    observed_at: str
    attributes: Mapping[str, Any]
    external_event_id: str | None = None
    occurred_at: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    causation_event_id: str | None = None
    correlation_id: str | None = None
    actor_type: str = "agent"
    actor_id: str = "unknown"

    def __post_init__(self) -> None:
        envelope = CaptureEnvelope(
            adapter="normalized", adapter_version="1", event_name=self.event_name,
            session_id=self.session_id, source_cursor=self.source_cursor,
            observed_at=self.observed_at, payload=self.attributes,
            external_event_id=self.external_event_id, occurred_at=self.occurred_at,
            trace_id=self.trace_id, span_id=self.span_id, parent_span_id=self.parent_span_id,
            causation_event_id=self.causation_event_id, correlation_id=self.correlation_id,
            actor_type=self.actor_type, actor_id=self.actor_id,
        )
        for name in (
            "event_name", "session_id", "source_cursor", "observed_at", "external_event_id",
            "occurred_at", "trace_id", "span_id", "parent_span_id", "causation_event_id",
            "correlation_id", "actor_type", "actor_id",
        ):
            object.__setattr__(self, name, getattr(envelope, name))
        object.__setattr__(self, "attributes", _freeze_json(self.attributes))

    @classmethod
    def from_envelope(
        cls, envelope: CaptureEnvelope, *, attributes: Mapping[str, Any],
    ) -> NormalizedEvent:
        return cls(
            event_name=envelope.event_name, session_id=envelope.session_id,
            source_cursor=envelope.source_cursor, observed_at=envelope.observed_at,
            attributes=attributes, external_event_id=envelope.external_event_id,
            occurred_at=envelope.occurred_at, trace_id=envelope.trace_id,
            span_id=envelope.span_id, parent_span_id=envelope.parent_span_id,
            causation_event_id=envelope.causation_event_id,
            correlation_id=envelope.correlation_id, actor_type=envelope.actor_type,
            actor_id=envelope.actor_id,
        )


@dataclass(frozen=True)
class CaptureSource:
    source_id: str
    adapter: str
    adapter_version: str
    installation_scope: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        source_id = _required_text("source_id", self.source_id, maximum=256)
        if find_sensitive_text(source_id):
            raise ValueError("source_id contains sensitive content")
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "adapter", _required_text("adapter", self.adapter, maximum=64))
        object.__setattr__(self, "adapter_version", _required_text("adapter_version", self.adapter_version, maximum=64))
        if self.installation_scope not in {"project", "user", "transcript", "api"}:
            raise ValueError(f"unsupported installation scope: {self.installation_scope}")
        if not isinstance(self.config_fingerprint, str) or len(self.config_fingerprint) != 64:
            raise ValueError("config_fingerprint must be a 64-character digest")


@dataclass(frozen=True)
class CaptureReplayPage:
    events: tuple[NormalizedEvent, ...]
    next_cursor: str | None
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple) or not all(isinstance(item, NormalizedEvent) for item in self.events):
            raise TypeError("replay events must be a tuple of NormalizedEvent values")
        object.__setattr__(self, "next_cursor", _optional_text("next_cursor", self.next_cursor, maximum=512))
        if type(self.complete) is not bool:
            raise TypeError("complete must be a boolean")
