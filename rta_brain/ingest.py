import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".venv-wsl-cuda",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
    ".agents",
    ".firecrawl",
    ".playwright-cli",
    ".pytest_cache",
    ".superpowers",
    "audit",
    "build",
    "coverage",
    "data",
    "dist",
    "execution_leases",
    "logs",
    "output",
    "state_write_locks",
    "test-results",
    "unused",
}

IGNORED_PREFIXES = (
    "tmp",
    ".tmp",
    ".venv",
    "temp",
    "cache",
    "__pycache__",
)

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".css",
    ".html",
    ".sql",
    ".ps1",
    ".sh",
}

MAX_REPO_FILES = 50_000
MAX_FILE_BYTES = 512_000
MAX_REPO_TOTAL_BYTES = 2_000_000_000
MAX_REPO_TRAVERSED_ENTRIES = 250_000

SYMBOL_PATTERNS = [
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*function\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^\s*export\s+function\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^\s*export\s+class\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE),
]

IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_\.]*)", re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+import\s+", re.MULTILINE),
    re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"require\(['\"]([^'\"]+)['\"]\)"),
]


@dataclass(frozen=True)
class FileRecord:
    path: Path
    relative_path: str
    text: str
    sha256: str
    symbols: list[str]
    imports: list[str]
    chunks: list[str]
    parser: str = "regex"
    parser_warnings: tuple[str, ...] = ()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def walk_repo(root: Path, rejected: list[dict[str, str]] | None = None, max_file_bytes: int = MAX_FILE_BYTES):
    root = root.resolve()

    def reject(path: Path, reason: str) -> None:
        if rejected is not None:
            rejected.append({"path": str(path.absolute()), "reason": reason})

    yielded = 0
    total_bytes = 0
    traversed = 0
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        traversed += len(directories) + len(filenames)
        if traversed > MAX_REPO_TRAVERSED_ENTRIES:
            raise ValueError(f"repository exceeds the {MAX_REPO_TRAVERSED_ENTRIES:,} entry traversal limit")
        kept_directories = []
        for name in directories:
            path = current_path / name
            if name in IGNORED_DIRS or name.lower().startswith(IGNORED_PREFIXES):
                continue
            if path.is_symlink():
                reject(path, "symlink-directory")
                continue
            kept_directories.append(name)
        directories[:] = kept_directories
        for name in filenames:
            path = current_path / name
            if name.lower().startswith(IGNORED_PREFIXES) or not is_text_file(path):
                continue
            if path.is_symlink():
                reject(path, "symlink-file")
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                reject(path, "unresolvable-or-outside-root")
                continue
            try:
                stat = resolved.stat()
            except OSError:
                reject(path, "unreadable-metadata")
                continue
            if not resolved.is_file():
                reject(path, "not-a-regular-file")
                continue
            if stat.st_nlink > 1:
                reject(path, "hard-link-file")
                continue
            if stat.st_size > max_file_bytes:
                reject(path, f"oversized:{stat.st_size}")
                continue
            yielded += 1
            if yielded > MAX_REPO_FILES:
                raise ValueError(f"repository exceeds the {MAX_REPO_FILES:,} file ingestion limit")
            total_bytes += stat.st_size
            if total_bytes > MAX_REPO_TOTAL_BYTES:
                raise ValueError(f"repository exceeds the {MAX_REPO_TOTAL_BYTES:,} byte ingestion limit")
            yield resolved


def read_text(path: Path, max_bytes: int = MAX_FILE_BYTES) -> str | None:
    if path.stat().st_size > max_bytes:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    except OSError:
        return None


def extract_symbols(text: str) -> list[str]:
    found = []
    for pattern in SYMBOL_PATTERNS:
        found.extend(match.group(1) for match in pattern.finditer(text))
    return sorted(set(found), key=str.lower)


def extract_imports(text: str) -> list[str]:
    found = []
    for pattern in IMPORT_PATTERNS:
        found.extend(match.group(1) for match in pattern.finditer(text))
    return sorted(set(found), key=str.lower)


def extract_terms(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b|`([^`]{2,80})`", text)
    uppercase = re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text)
    flattened = [item for item in candidates if item] + uppercase
    words = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{3,}\b", text)
    important = [word for word in words if word.lower() in {"attestation", "release", "memory", "graph", "codex", "context", "agent"}]
    return sorted(set(flattened + important), key=str.lower)[:24]


def chunk_text(text: str, max_chars: int = 1800) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks = []
    current = ""
    for paragraph in paragraphs or [text.strip()]:
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.append(current[:max_chars])
            current = paragraph
    if current:
        chunks.append(current[:max_chars])
    return chunks[:80]


def build_file_record(
    root: Path,
    path: Path,
    max_bytes: int = MAX_FILE_BYTES,
    parser_name: str = "regex",
    lsp_command: str = "",
    parser_registry=None,
) -> FileRecord | None:
    text = read_text(path, max_bytes=max_bytes)
    if text is None:
        return None
    from .parsers import ParserRegistry

    registry = parser_registry or ParserRegistry(lsp_command=lsp_command)
    parsed = registry.parse(path, text, parser_name=parser_name)
    return FileRecord(
        path=path.resolve(),
        relative_path=path.resolve().relative_to(root.resolve()).as_posix(),
        text=text,
        sha256=sha256_text(text),
        symbols=parsed.symbols,
        imports=parsed.imports,
        chunks=chunk_text(text),
        parser=parsed.parser,
        parser_warnings=tuple(parsed.warnings),
    )
