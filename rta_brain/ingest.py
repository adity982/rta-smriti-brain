import hashlib
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


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def walk_repo(root: Path):
    root = root.resolve()
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS or part.lower().startswith(IGNORED_PREFIXES) for part in parts):
            continue
        if path.is_file() and is_text_file(path):
            yield path


def read_text(path: Path, max_bytes: int = 512_000) -> str | None:
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
    flattened = []
    for item in candidates:
        if isinstance(item, tuple):
            flattened.extend(part for part in item if part)
        else:
            flattened.append(item)
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


def build_file_record(root: Path, path: Path) -> FileRecord | None:
    text = read_text(path)
    if text is None:
        return None
    return FileRecord(
        path=path.resolve(),
        relative_path=path.resolve().relative_to(root.resolve()).as_posix(),
        text=text,
        sha256=sha256_text(text),
        symbols=extract_symbols(text),
        imports=extract_imports(text),
        chunks=chunk_text(text),
    )
