import argparse
import re
import subprocess
import sys
from pathlib import Path


SECRET_PATTERNS = {
    "aws-access-key": re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    "github-token": re.compile(rb"gh[pousr]_[A-Za-z0-9_]{30,}"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "assigned-secret": re.compile(rb"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"),
}

PATH_PATTERNS = {
    "windows-user-path": re.compile(rb"(?i)[A-Z]:[\\/]Users[\\/][^\\/\x00\r\n]{1,100}[\\/]"),
    "posix-user-path": re.compile(rb"/(?:Users|home)/[^/\x00\r\n]{1,100}/"),
    "unc-path": re.compile(rb"\\\\[^\\/\x00\r\n]{1,253}\\[^\\/\x00\r\n]{1,100}\\"),
}

FORBIDDEN_SUFFIXES = {".db", ".key", ".log", ".pem", ".sqlite", ".sqlite-shm", ".sqlite-wal"}
FORBIDDEN_NAMES = {".env"}
MAX_SCAN_BYTES = 25 * 1024 * 1024


def path_scan_views(data: bytes) -> list[bytes]:
    """Expose text and metadata strings without interpreting compressed payloads."""
    views: list[bytes] = []
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        printable_runs = re.findall(rb"[\x20-\x7e]{4,}", data)
        if printable_runs:
            views.append(b"\n".join(printable_runs))
    else:
        views.append(data)

    prefixes = []
    for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        prefixes.extend((f"{drive}:\\Users\\", f"{drive}:/Users/"))
    prefixes.extend(("/Users/", "/home/"))
    for prefix in prefixes:
        for encoding in ("utf-16-le", "utf-16-be"):
            marker = prefix.encode(encoding)
            start = data.find(marker)
            while start >= 0:
                decoded = data[start : start + 512].decode(encoding, errors="ignore").encode("utf-8", errors="ignore")
                if decoded:
                    views.append(decoded)
                start = data.find(marker, start + len(marker))
    return views


def is_placeholder_path(match: bytes) -> bool:
    lowered = match.lower()
    return any(marker in lowered for marker in (b"<real-name>", b"<username>", b"%userprofile%", b"$env:userprofile", b"{username}", b"[username]"))


def candidate_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / item for item in result.stdout.splitlines() if item and (root / item).is_file()]


def scan(root: Path, deny_terms: list[str]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    deny_patterns = [(f"private-term:{term}", re.compile(re.escape(term).encode(), re.IGNORECASE)) for term in deny_terms if term]
    for path in candidate_files(root):
        relative = path.relative_to(root).as_posix()
        lower_name = path.name.lower()
        lower_suffixes = "".join(path.suffixes).lower()
        if lower_name in FORBIDDEN_NAMES or any(lower_suffixes.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            findings.append((relative, "forbidden-release-file"))
            continue
        if path.stat().st_size > MAX_SCAN_BYTES:
            findings.append((relative, f"unscanned-file-over-{MAX_SCAN_BYTES}-bytes"))
            continue
        data = path.read_bytes()
        for label, pattern in [*SECRET_PATTERNS.items(), *deny_patterns]:
            for match in pattern.finditer(data):
                findings.append((relative, label))
                break
        if relative != "scripts/privacy_scan.py":
            for label, pattern in PATH_PATTERNS.items():
                matches = (match.group(0) for view in path_scan_views(data) for match in pattern.finditer(view))
                if any(not is_placeholder_path(match) for match in matches):
                    findings.append((relative, label))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public-candidate files for credentials, local paths, and private names.")
    parser.add_argument("--deny-term", action="append", default=[], help="Private project, client, or product name that must not appear. Repeat as needed.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root, args.deny_term)
    print(f"privacy scan: {len(candidate_files(root))} candidate files")
    if findings:
        for path, category in findings:
            print(f"BLOCK {category}: {path}")
        return 1
    print("privacy scan: PASS (no credential signatures, absolute user paths, forbidden files, or denied terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
