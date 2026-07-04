"""Static analysis parser for building the Knowledge Graph.

Supports Python (via ast module — built-in, zero cost) and
JS/TS (via regex-based import extraction — no extra deps needed for MVP).

Each parser returns a ParseResult with:
  - imports: list of (source_file, imported_file) edges
  - api_routes: list of route paths defined in this file
  - db_tables: list of table/model names defined in this file
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParseResult:
    file_path: str
    language: str
    imports: list[str] = field(default_factory=list)   # paths this file imports
    api_routes: list[str] = field(default_factory=list) # route strings defined here
    db_tables: list[str] = field(default_factory=list)  # model/table names defined here
    error: str | None = None                             # parse error if any


def detect_language(file_path: str) -> str | None:
    """Return language key for supported file types, None for unsupported."""
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
    }
    return mapping.get(ext)


def parse_file(file_path: str, content: str) -> ParseResult:
    """Parse a single file and extract graph data."""
    language = detect_language(file_path)
    if language is None:
        return ParseResult(file_path=file_path, language="unknown")

    if language == "python":
        return _parse_python(file_path, content)
    else:
        return _parse_js_ts(file_path, content, language)


# --- Python parser ---

def _parse_python(file_path: str, content: str) -> ParseResult:
    result = ParseResult(file_path=file_path, language="python")
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        result.error = f"SyntaxError: {e}"
        return result

    file_dir = str(Path(file_path).parent)

    for node in ast.walk(tree):
        # Extract imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                result.imports.append(_module_to_path(alias.name))

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level > 0:
                    # Relative import — resolve relative to current file directory
                    resolved = _resolve_relative(file_dir, node.level, node.module)
                    result.imports.append(resolved)
                else:
                    result.imports.append(_module_to_path(node.module))

        # Detect FastAPI route decorators
        elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                route = _extract_fastapi_route(decorator)
                if route:
                    result.api_routes.append(route)

        # Detect SQLAlchemy table names from __tablename__ = "..."
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                    and item.targets[0].id == "__tablename__"
                    and isinstance(item.value, ast.Constant)
                ):
                    result.db_tables.append(str(item.value.value))

    return result


def _module_to_path(module: str) -> str:
    """Convert a dotted module name to a relative file path hint."""
    return module.replace(".", "/")


def _resolve_relative(file_dir: str, level: int, module: str) -> str:
    """Resolve a relative import to a path hint."""
    parts = file_dir.split("/")
    # Go up `level - 1` directories (level=1 means current package)
    if level > 1:
        parts = parts[:-(level - 1)] if level - 1 < len(parts) else []
    base = "/".join(parts)
    if module:
        return f"{base}/{module.replace('.', '/')}" if base else module.replace(".", "/")
    return base


def _extract_fastapi_route(decorator) -> str | None:
    """Extract route path from FastAPI decorators like @router.get('/path')."""
    try:
        # Handles: @router.get("/path"), @app.post("/path"), etc.
        if isinstance(decorator, ast.Call):
            func = decorator.func
            if isinstance(func, ast.Attribute) and func.attr in (
                "get", "post", "put", "patch", "delete", "head", "options"
            ):
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    return str(decorator.args[0].value)
    except Exception:
        pass
    return None


# --- JS/TS parser (regex-based) ---

# Match: import ... from './path' or require('./path')
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]*?\s+from\s+)?|require\s*\(\s*)['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Match Express-style routes: router.get('/path', ...) or app.post('/path', ...)
_JS_ROUTE_RE = re.compile(
    r"""(?:router|app)\s*\.\s*(?:get|post|put|patch|delete)\s*\(\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)

# Match Sequelize/TypeORM table names: @Table({ tableName: 'users' }) or tableName: 'users'
_JS_TABLE_RE = re.compile(
    r"""tableName\s*[=:]\s*['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def _parse_js_ts(file_path: str, content: str, language: str) -> ParseResult:
    result = ParseResult(file_path=file_path, language=language)

    for match in _JS_IMPORT_RE.finditer(content):
        raw_import = match.group(1)
        # Only track relative imports (start with ./ or ../)
        if raw_import.startswith("."):
            result.imports.append(raw_import)

    for match in _JS_ROUTE_RE.finditer(content):
        result.api_routes.append(match.group(1))

    for match in _JS_TABLE_RE.finditer(content):
        result.db_tables.append(match.group(1))

    return result