"""Bounded sensitive-text detection shared by exports and release scans."""

from __future__ import annotations

import re
from dataclasses import dataclass


MAX_SENSITIVE_TEXT_CHARS = 100_000


@dataclass(frozen=True)
class SensitiveFinding:
    label: str
    start: int
    end: int


SECRET_TEXT_PATTERNS = {
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "openai-style-token": re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}\b"),
    "private-key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
        r"[\s\S]{0,100000}?(?:-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|\Z)"
    ),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "assigned-secret": re.compile(
        r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|password|access[_-]?token|client[_-]?secret)"
        r"\s*[:=]\s*(?:['\"][^'\"\r\n]{1,4096}['\"]|[^\s,;]{1,4096})"
    ),
}

PATH_TEXT_PATTERNS = {
    "windows-user-path": re.compile(r"(?i)\b[A-Z]:[\\/]Users[\\/][^\\/\x00\r\n]{1,100}[\\/]"),
    "posix-user-path": re.compile(r"/(?:Users|home)/[^/\x00\r\n]{1,100}/"),
    "unc-path": re.compile(r"\\\\[^\\/\x00\r\n]{1,253}\\[^\\/\x00\r\n]{1,100}(?:\\[^\x00\r\n]{1,4096})?"),
    "windows-absolute-path": re.compile(
        r"(?i)(?<![A-Za-z0-9_])[A-Z]:[\\/]"
        r"(?:[A-Za-z0-9._ -]{1,120}[\\/]){1,32}[A-Za-z0-9._ -]{1,200}"
    ),
    "posix-absolute-path": re.compile(
        r"(?<![:/A-Za-z0-9_])/(?!/)"
        r"(?:[A-Za-z0-9._ -]{1,120}/){1,32}[A-Za-z0-9._ -]{1,200}"
    ),
}

SENSITIVE_TEXT_PATTERNS = {**SECRET_TEXT_PATTERNS, **PATH_TEXT_PATTERNS}


def _byte_patterns(patterns: dict[str, re.Pattern[str]]) -> dict[str, re.Pattern[bytes]]:
    return {
        label: re.compile(pattern.pattern.encode("ascii"), re.IGNORECASE if pattern.flags & re.IGNORECASE else 0)
        for label, pattern in patterns.items()
    }


SECRET_BYTE_PATTERNS = _byte_patterns(SECRET_TEXT_PATTERNS)
PATH_BYTE_PATTERNS = _byte_patterns(PATH_TEXT_PATTERNS)

# Release scanning deliberately limits path checks to private-machine locations.
# Source trees legitimately contain URL routes and portable POSIX paths; bundle
# values do not have that ambiguity and use the full detector above.
RELEASE_SECRET_BYTE_PATTERNS = {
    "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    "github-token": re.compile(rb"gh[pousr]_[A-Za-z0-9_]{30,}"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "assigned-secret": re.compile(
        rb"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret)"
        rb"\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"
    ),
}
RELEASE_PATH_BYTE_PATTERNS = {
    label: PATH_BYTE_PATTERNS[label]
    for label in ("windows-user-path", "posix-user-path", "unc-path")
}


def find_sensitive_text(value: str, *, max_chars: int = MAX_SENSITIVE_TEXT_CHARS) -> list[SensitiveFinding]:
    text = str(value)
    if len(text) > max_chars:
        raise ValueError(f"sensitive-text scan exceeds the {max_chars:,} character limit")
    findings = []
    for label, pattern in SENSITIVE_TEXT_PATTERNS.items():
        findings.extend(SensitiveFinding(label, match.start(), match.end()) for match in pattern.finditer(text))
    return sorted(findings, key=lambda item: (item.start, item.end, item.label))


def redact_sensitive_text(value: str, replacement: str = "[REDACTED]") -> tuple[str, int]:
    text = str(value)
    if len(text) > MAX_SENSITIVE_TEXT_CHARS:
        raise ValueError(f"sensitive-text redaction exceeds the {MAX_SENSITIVE_TEXT_CHARS:,} character limit")
    redactions = 0
    for pattern in SENSITIVE_TEXT_PATTERNS.values():
        text, count = pattern.subn(replacement, text)
        redactions += count
    return text, redactions
