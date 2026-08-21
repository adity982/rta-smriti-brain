"""Parser adapter registry with deterministic and optional backends."""

from __future__ import annotations

import importlib.metadata
import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)", re.MULTILINE),
)
IMPORT_PATTERNS = (
    re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE),
    re.compile(r"^\s*from\s+([A-Za-z_][A-Za-z0-9_.]*)\s+import\s+", re.MULTILINE),
    re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    re.compile(r"require\(['\"]([^'\"]+)['\"]\)"),
)
CALL_PATTERN = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$.]*)\s*\(")
CALL_EXCLUSIONS = frozenset({
    "and", "assert", "async", "await", "catch", "class", "def", "elif", "except",
    "for", "function", "if", "lambda", "match", "new", "not", "or", "raise",
    "return", "sizeof", "super", "switch", "throw", "try", "typeof", "while", "with",
})

TREE_SITTER_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}
TREE_SITTER_SYMBOL_NODES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition"},
    "typescript": {"function_declaration", "class_declaration", "method_definition", "interface_declaration", "type_alias_declaration"},
    "tsx": {"function_declaration", "class_declaration", "method_definition", "interface_declaration", "type_alias_declaration"},
    "go": {"function_declaration", "method_declaration", "type_spec"},
    "rust": {"function_item", "struct_item", "enum_item", "trait_item", "union_item", "type_item", "mod_item"},
    "java": {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration", "method_declaration", "constructor_declaration"},
}
TREE_SITTER_IMPORT_NODES = {
    "python": {"import_statement", "import_from_statement"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "tsx": {"import_statement"},
    "go": {"import_declaration", "import_spec"},
    "rust": {"use_declaration"},
    "java": {"import_declaration"},
}
TREE_SITTER_CALL_NODES = {
    "python": {"call"},
    "javascript": {"call_expression"},
    "typescript": {"call_expression"},
    "tsx": {"call_expression"},
    "go": {"call_expression"},
    "rust": {"call_expression"},
    "java": {"method_invocation"},
}


@dataclass
class ParseResult:
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    parser: str = "regex"
    warnings: list[str] = field(default_factory=list)


class ParserAdapter(Protocol):
    name: str

    def parse(self, path: Path, text: str) -> ParseResult: ...


class RegexParser:
    name = "regex"

    def parse(self, _path: Path, text: str) -> ParseResult:
        symbols = {match.group(1) for pattern in SYMBOL_PATTERNS for match in pattern.finditer(text)}
        imports = {match.group(1) for pattern in IMPORT_PATTERNS for match in pattern.finditer(text)}
        calls = {
            match.group(1).split(".")[-1]
            for match in CALL_PATTERN.finditer(text)
            if match.group(1).casefold() not in CALL_EXCLUSIONS
            and match.group(1).split(".")[-1] not in symbols
        }
        return ParseResult(
            symbols=sorted(symbols, key=str.lower),
            imports=sorted(imports, key=str.lower),
            calls=sorted(calls, key=str.lower),
            parser=self.name,
        )


class TreeSitterParser:
    name = "tree-sitter"

    def __init__(self) -> None:
        try:
            from tree_sitter_language_pack import get_parser
        except ImportError:
            get_parser = None
        self._get_parser = get_parser

    @property
    def available(self) -> bool:
        return self._get_parser is not None

    def parse(self, path: Path, text: str) -> ParseResult:
        if not self.available:
            raise RuntimeError("tree-sitter-language-pack is not installed")
        language = TREE_SITTER_LANGUAGES.get(path.suffix.lower())
        if not language:
            raise RuntimeError(f"Tree-sitter language is not configured for {path.suffix or 'this file'}")
        source = text.encode("utf-8")
        tree = self._get_parser(language).parse(source)
        symbols: set[str] = set()
        imports: set[str] = set()
        calls: set[str] = set()

        def node_text(node) -> str:
            return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

        def import_names(snippet: str) -> set[str]:
            if language == "go":
                return set(re.findall(r'(?m)^\s*(?:import\s+)?(?:[A-Za-z_][A-Za-z0-9_]*\s+)?["`]([^"`]+)["`]', snippet))
            if language == "rust":
                return {match.strip() for match in re.findall(r"\buse\s+([^;]+)", snippet) if match.strip()}
            if language == "java":
                return set(re.findall(r"\bimport\s+(?:static\s+)?([A-Za-z_][A-Za-z0-9_.*]+)\s*;", snippet))
            return set(RegexParser().parse(path, snippet).imports)

        def visit(node) -> None:
            if node.type in TREE_SITTER_SYMBOL_NODES.get(language, set()):
                name = node.child_by_field_name("name")
                if name:
                    symbols.add(node_text(name))
            if node.type in TREE_SITTER_IMPORT_NODES.get(language, set()):
                imports.update(import_names(node_text(node)))
            if node.type in TREE_SITTER_CALL_NODES.get(language, set()):
                callee = node.child_by_field_name("function") or node.child_by_field_name("name")
                if callee:
                    identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", node_text(callee))
                    if identifiers and identifiers[-1].casefold() not in CALL_EXCLUSIONS:
                        calls.add(identifiers[-1])
            for child in node.children:
                visit(child)

        visit(tree.root_node)
        return ParseResult(
            symbols=sorted(symbols, key=str.lower),
            imports=sorted(imports, key=str.lower),
            calls=sorted(calls, key=str.lower),
            parser=self.name,
        )


class LspParser:
    """Adapter for explicit commands that return one JSON document-symbol response."""

    name = "lsp"

    def __init__(self, command: str = "") -> None:
        self.command = command.strip()

    @property
    def available(self) -> bool:
        return bool(self.command)

    def parse(self, path: Path, text: str) -> ParseResult:
        if not self.command:
            raise RuntimeError("an LSP adapter command must be configured")
        request = json.dumps({"path": str(path), "text": text})
        completed = subprocess.run(
            shlex.split(self.command), input=request, text=True, capture_output=True, timeout=30, check=False,
        )
        if completed.returncode:
            raise RuntimeError(f"LSP adapter exited with code {completed.returncode}")
        payload = json.loads(completed.stdout)
        return ParseResult(
            symbols=sorted({str(item) for item in payload.get("symbols", [])}, key=str.lower),
            imports=sorted({str(item) for item in payload.get("imports", [])}, key=str.lower),
            calls=sorted(
                {str(item) for item in payload.get("calls", RegexParser().parse(path, text).calls)},
                key=str.lower,
            ),
            parser=self.name,
        )


class ParserRegistry:
    def __init__(self, load_entry_points: bool = True, lsp_command: str = "") -> None:
        self._parsers: dict[str, ParserAdapter] = {}
        self.register(RegexParser())
        self.register(TreeSitterParser())
        self.register(LspParser(lsp_command))
        if load_entry_points:
            self._load_entry_points()

    def register(self, parser: ParserAdapter) -> None:
        self._parsers[parser.name] = parser

    def _load_entry_points(self) -> None:
        try:
            points = importlib.metadata.entry_points(group="rta_smriti.parsers")
        except TypeError:
            points = importlib.metadata.entry_points().get("rta_smriti.parsers", [])
        for point in points:
            self.register(point.load()())

    def capabilities(self) -> dict[str, dict]:
        capabilities = {
            name: {"available": bool(getattr(parser, "available", True)), "source": parser.__class__.__name__}
            for name, parser in sorted(self._parsers.items())
        }
        capabilities["auto"] = {
            "available": True,
            "source": "TreeSitterThenRegex",
            "tree_sitter_available": capabilities.get("tree-sitter", {}).get("available", False),
        }
        return capabilities

    def parse(self, path: Path, text: str, parser_name: str = "regex") -> ParseResult:
        if parser_name == "auto":
            tree_sitter = self._parsers["tree-sitter"]
            if bool(getattr(tree_sitter, "available", False)):
                try:
                    result = tree_sitter.parse(path, text)
                    result.parser = "auto:tree-sitter"
                    return result
                except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
                    pass
            result = self._parsers["regex"].parse(path, text)
            result.parser = "auto:regex"
            return result
        parser = self._parsers.get(parser_name)
        if parser is None:
            raise ValueError(f"unknown parser adapter: {parser_name}")
        try:
            return parser.parse(path, text)
        except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            if parser_name == "regex":
                raise
            fallback = self._parsers["regex"].parse(path, text)
            fallback.warnings.append(f"{parser_name} unavailable; used regex: {exc}")
            return fallback
