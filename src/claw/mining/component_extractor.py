"""Reusable component extraction helpers for CAM-SEQ.

This module now supports a precision ladder:

- Tree-sitter when the optional parser packages are installed
- Python AST fallback for Python
- Regex heuristics fallback for JavaScript/TypeScript

The public call surface stays stable so miner call sites and M2 contracts do
not drift while parser precision improves.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ExtractedComponent:
    title: str
    component_type: str
    file_path: str
    symbol_name: str
    symbol_kind: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    language: Optional[str] = None
    decorators: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    ast_fingerprint: str = ""
    note: str = ""


_PY_ROUTE_DECORATOR_HINTS = {"get", "post", "put", "patch", "delete", "route"}
_JS_FUNC_COMPONENT_TYPES = {"function_declaration", "generator_function_declaration"}
_JS_CLASS_COMPONENT_TYPES = {"class_declaration"}
_TS_VAR_COMPONENT_TYPES = {"lexical_declaration", "variable_statement"}


def _detect_language(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".tsx":
        return "tsx"
    if suffix == ".ts":
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    return None


def _classify_component(
    symbol_name: str,
    *,
    symbol_kind: str,
    relative_path: str,
    decorators: list[str],
    is_async: bool = False,
) -> str:
    name = symbol_name.lower()
    path = relative_path.lower()
    decos = [d.lower() for d in decorators]

    if "fixture" in name or any("fixture" in d for d in decos) or "fixtures" in path:
        return "test_fixture"
    if any(any(hint in deco for hint in _PY_ROUTE_DECORATOR_HINTS) for deco in decos):
        return "route_handler"
    if any(tok in name for tok in ("validate", "validator", "schema", "clean_")):
        return "validator"
    if any(tok in name for tok in ("worker", "job", "queue", "consumer", "processor", "handler")):
        return "worker" if is_async or symbol_kind == "function" else "service"
    if any(tok in name for tok in ("client", "session", "auth", "token", "oauth")):
        return "client" if symbol_kind == "class" else "helper"
    if symbol_kind == "class":
        return "class_component"
    return "helper"


def _fingerprint(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _keyword_tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) >= 3]


def _tree_sitter_modules() -> Optional[dict[str, Any]]:
    try:
        from tree_sitter import Language, Parser  # type: ignore
    except Exception:
        return None

    modules: dict[str, Any] = {"Language": Language, "Parser": Parser}
    for module_name, key in (
        ("tree_sitter_python", "python"),
        ("tree_sitter_javascript", "javascript"),
        ("tree_sitter_typescript", "typescript"),
    ):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        modules[key] = module
        if key == "typescript":
            modules["tsx"] = module
    return modules


def _build_parser(language: str) -> Optional[Any]:
    modules = _tree_sitter_modules()
    if not modules or language not in modules:
        return None

    language_module = modules[language]
    parser_cls = modules["Parser"]
    language_cls = modules["Language"]

    language_factory = getattr(language_module, "language", None)
    if language_factory is None and language == "typescript":
        language_factory = getattr(language_module, "language_typescript", None)
    if language_factory is None and language == "tsx":
        language_factory = getattr(language_module, "language_tsx", None)
    if language_factory is None:
        return None

    tree_language = language_cls(language_factory())
    try:
        return parser_cls(tree_language)
    except TypeError:
        parser = parser_cls()
        set_language = getattr(parser, "set_language", None)
        if set_language is not None:
            set_language(tree_language)
        else:
            try:
                parser.language = tree_language
            except Exception:
                return None
        return parser


def _ts_node_text(node: Any, text_bytes: bytes) -> str:
    try:
        if hasattr(node, "text") and isinstance(node.text, (bytes, bytearray)):
            return bytes(node.text).decode("utf-8", errors="replace")
    except Exception:
        pass
    start = getattr(node, "start_byte", None)
    end = getattr(node, "end_byte", None)
    if isinstance(start, int) and isinstance(end, int):
        return text_bytes[start:end].decode("utf-8", errors="replace")
    return ""


def _ts_line(node: Any, attr: str) -> Optional[int]:
    point = getattr(node, attr, None)
    if isinstance(point, tuple) and len(point) >= 1:
        return int(point[0]) + 1
    return None


def _extract_python_ts_imports(root: Any, text_bytes: bytes) -> list[str]:
    imports: list[str] = []
    for child in getattr(root, "children", []):
        if child.type not in {"import_statement", "import_from_statement"}:
            continue
        raw = _ts_node_text(child, text_bytes).strip()
        if raw:
            imports.append(raw.replace("\n", " "))
    return imports[:12]


def _extract_python_ts_components(text: str, relative_path: str, parser: Any) -> list[ExtractedComponent]:
    text_bytes = text.encode("utf-8")
    tree = parser.parse(text_bytes)
    root = tree.root_node
    imports = _extract_python_ts_imports(root, text_bytes)
    components: list[ExtractedComponent] = []

    for child in getattr(root, "children", []):
        node = child
        decorators: list[str] = []
        if node.type == "decorated_definition":
            decorators = [
                _ts_node_text(grandchild, text_bytes).strip()
                for grandchild in getattr(node, "children", [])
                if grandchild.type == "decorator"
            ]
            node = next(
                (
                    grandchild
                    for grandchild in getattr(node, "children", [])
                    if grandchild.type in {"function_definition", "class_definition"}
                ),
                None,
            )
            if node is None:
                continue

        if node.type not in {"function_definition", "class_definition"}:
            continue

        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        symbol_name = _ts_node_text(name_node, text_bytes).strip()
        if not symbol_name:
            continue
        symbol_kind = "class" if node.type == "class_definition" else "function"
        is_async = bool(
            symbol_kind == "function"
            and any(grandchild.type == "async" for grandchild in getattr(node, "children", []))
        )
        component_type = _classify_component(
            symbol_name,
            symbol_kind=symbol_kind,
            relative_path=relative_path,
            decorators=decorators,
            is_async=is_async,
        )
        components.append(
            ExtractedComponent(
                title=symbol_name,
                component_type=component_type,
                file_path=relative_path,
                symbol_name=symbol_name,
                symbol_kind=symbol_kind,
                line_start=_ts_line(node, "start_point"),
                line_end=_ts_line(node, "end_point"),
                language="python",
                decorators=decorators,
                imports=imports,
                keywords=_keyword_tokens(symbol_name),
                ast_fingerprint=_fingerprint(
                    [relative_path, symbol_kind, symbol_name, *decorators, "tree_sitter"]
                ),
                note=f"python {symbol_kind} via tree-sitter",
            )
        )
    return components


def _extract_python_method_components(text: str, relative_path: str, parser: Any) -> list[ExtractedComponent]:
    text_bytes = text.encode("utf-8")
    tree = parser.parse(text_bytes)
    root = tree.root_node
    imports = _extract_python_ts_imports(root, text_bytes)
    components_by_name: dict[str, ExtractedComponent] = {}

    for child in getattr(root, "children", []):
        node = child
        if node.type != "class_definition":
            continue
        class_name_node = node.child_by_field_name("name")
        if class_name_node is None:
            continue
        class_name = _ts_node_text(class_name_node, text_bytes).strip()
        if not class_name:
            continue
        for nested in _walk_ts_nodes(node):
            decorators: list[str] = []
            current = nested
            if current.type == "decorated_definition":
                decorators = [
                    _ts_node_text(grandchild, text_bytes).strip()
                    for grandchild in getattr(current, "children", [])
                    if grandchild.type == "decorator"
                ]
                current = next(
                    (
                        grandchild
                        for grandchild in getattr(current, "children", [])
                        if grandchild.type == "function_definition"
                    ),
                    None,
                )
                if current is None:
                    continue
            if current.type != "function_definition":
                continue
            method_name_node = current.child_by_field_name("name")
            if method_name_node is None:
                continue
            method_name = _ts_node_text(method_name_node, text_bytes).strip()
            if not method_name:
                continue
            qualified_name = f"{class_name}.{method_name}"
            is_async = any(grandchild.type == "async" for grandchild in getattr(current, "children", []))
            component_type = _classify_component(
                method_name,
                symbol_kind="function",
                relative_path=relative_path,
                decorators=decorators,
                is_async=is_async,
            )
            component = ExtractedComponent(
                title=qualified_name,
                component_type=component_type,
                file_path=relative_path,
                symbol_name=qualified_name,
                symbol_kind="method",
                line_start=_ts_line(current, "start_point"),
                line_end=_ts_line(current, "end_point"),
                language="python",
                decorators=decorators,
                imports=imports,
                keywords=_keyword_tokens(f"{class_name}_{method_name}"),
                ast_fingerprint=_fingerprint(
                    [relative_path, "method", class_name, method_name, *decorators, "tree_sitter"]
                ),
                note="python class method via tree-sitter",
            )
            existing = components_by_name.get(qualified_name)
            if existing is None or (decorators and not existing.decorators):
                components_by_name[qualified_name] = component
    return list(components_by_name.values())


def _walk_ts_nodes(root: Any) -> list[Any]:
    stack = [root]
    out: list[Any] = []
    while stack:
        node = stack.pop()
        out.append(node)
        children = list(getattr(node, "children", []))
        stack.extend(reversed(children))
    return out


def _unwrap_js_statement(node: Any) -> Any:
    current = node
    while current is not None and current.type in {"export_statement", "statement_block"}:
        children = [
            child
            for child in getattr(current, "children", [])
            if child.type not in {"export", "default", "{", "}"}
        ]
        current = children[0] if children else None
    return current


def _extract_js_ts_imports(root: Any, text_bytes: bytes) -> list[str]:
    imports: list[str] = []
    for child in getattr(root, "children", []):
        if child.type != "import_statement":
            continue
        raw = _ts_node_text(child, text_bytes).strip()
        if raw:
            imports.append(raw.replace("\n", " "))
    return imports[:12]


def _extract_var_components(node: Any, text_bytes: bytes, relative_path: str, language: str, imports: list[str]) -> list[ExtractedComponent]:
    components: list[ExtractedComponent] = []
    for current in _walk_ts_nodes(node):
        if current.type != "variable_declarator":
            continue
        name_node = current.child_by_field_name("name")
        value_node = current.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        symbol_name = _ts_node_text(name_node, text_bytes).strip()
        if not symbol_name:
            continue
        value_type = value_node.type
        if value_type not in {"arrow_function", "function", "function_expression"}:
            continue
        is_async = any(grandchild.type == "async" for grandchild in getattr(value_node, "children", []))
        component_type = _classify_component(
            symbol_name,
            symbol_kind="function",
            relative_path=relative_path,
            decorators=[],
            is_async=is_async,
        )
        components.append(
            ExtractedComponent(
                title=symbol_name,
                component_type=component_type,
                file_path=relative_path,
                symbol_name=symbol_name,
                symbol_kind="function",
                line_start=_ts_line(current, "start_point"),
                line_end=_ts_line(current, "end_point"),
                language=language,
                imports=imports,
                keywords=_keyword_tokens(symbol_name),
                ast_fingerprint=_fingerprint(
                    [relative_path, "function", symbol_name, value_type, "tree_sitter"]
                ),
                note=f"{language} variable function via tree-sitter",
            )
        )
    return components


def _extract_object_literal_components(node: Any, text_bytes: bytes, relative_path: str, language: str, imports: list[str]) -> list[ExtractedComponent]:
    components: list[ExtractedComponent] = []
    for current in _walk_ts_nodes(node):
        if current.type != "variable_declarator":
            continue
        name_node = current.child_by_field_name("name")
        value_node = current.child_by_field_name("value")
        if name_node is None or value_node is None or value_node.type != "object":
            continue
        object_name = _ts_node_text(name_node, text_bytes).strip()
        if not object_name:
            continue
        for nested in _walk_ts_nodes(value_node):
            method_name = ""
            is_async = False
            if nested.type == "pair":
                key_node = nested.child_by_field_name("key")
                pair_value = nested.child_by_field_name("value")
                if key_node is None or pair_value is None:
                    continue
                method_name = _ts_node_text(key_node, text_bytes).strip().strip("\"'")
                if pair_value.type not in {"arrow_function", "function", "function_expression"}:
                    continue
                is_async = any(grandchild.type == "async" for grandchild in getattr(pair_value, "children", []))
            elif nested.type == "method_definition":
                key_node = nested.child_by_field_name("name")
                if key_node is None:
                    continue
                method_name = _ts_node_text(key_node, text_bytes).strip().strip("\"'")
                is_async = any(grandchild.type == "async" for grandchild in getattr(nested, "children", []))
            else:
                continue
            if not method_name:
                continue
            qualified_name = f"{object_name}.{method_name}"
            component_type = _classify_component(
                method_name,
                symbol_kind="function",
                relative_path=relative_path,
                decorators=[],
                is_async=is_async,
            )
            components.append(
                ExtractedComponent(
                    title=qualified_name,
                    component_type=component_type,
                    file_path=relative_path,
                    symbol_name=qualified_name,
                    symbol_kind="method",
                    line_start=_ts_line(nested, "start_point"),
                    line_end=_ts_line(nested, "end_point"),
                    language=language,
                    imports=imports,
                    keywords=_keyword_tokens(qualified_name.replace(".", "_")),
                    ast_fingerprint=_fingerprint(
                        [relative_path, "object_method", object_name, method_name, language, "tree_sitter"]
                    ),
                    note=f"{language} object method via tree-sitter",
                )
            )
    return components


def _extract_class_field_components(node: Any, text_bytes: bytes, relative_path: str, language: str, imports: list[str]) -> list[ExtractedComponent]:
    components: list[ExtractedComponent] = []
    class_name_node = node.child_by_field_name("name")
    class_name = _ts_node_text(class_name_node, text_bytes).strip() if class_name_node is not None else ""
    for nested in _walk_ts_nodes(node):
        if nested.type not in {"field_definition", "public_field_definition", "property_definition"}:
            continue
        name_node = nested.child_by_field_name("name")
        value_node = nested.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        method_name = _ts_node_text(name_node, text_bytes).strip()
        if not method_name or value_node.type not in {"arrow_function", "function", "function_expression"}:
            continue
        qualified_name = f"{class_name}.{method_name}" if class_name else method_name
        is_async = any(grandchild.type == "async" for grandchild in getattr(value_node, "children", []))
        component_type = _classify_component(
            method_name,
            symbol_kind="function",
            relative_path=relative_path,
            decorators=[],
            is_async=is_async,
        )
        components.append(
            ExtractedComponent(
                title=qualified_name,
                component_type=component_type,
                file_path=relative_path,
                symbol_name=qualified_name,
                symbol_kind="method",
                line_start=_ts_line(nested, "start_point"),
                line_end=_ts_line(nested, "end_point"),
                language=language,
                imports=imports,
                keywords=_keyword_tokens(qualified_name.replace(".", "_")),
                ast_fingerprint=_fingerprint(
                    [relative_path, "class_field_method", class_name, method_name, language, "tree_sitter"]
                ),
                note=f"{language} class field method via tree-sitter",
            )
        )
    return components


def _extract_js_like_ts_components(text: str, relative_path: str, language: str, parser: Any) -> list[ExtractedComponent]:
    text_bytes = text.encode("utf-8")
    tree = parser.parse(text_bytes)
    root = tree.root_node
    imports = _extract_js_ts_imports(root, text_bytes)
    components: list[ExtractedComponent] = []

    for child in getattr(root, "children", []):
        node = _unwrap_js_statement(child)
        if node is None:
            continue
        if node.type in _JS_FUNC_COMPONENT_TYPES | _JS_CLASS_COMPONENT_TYPES:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            symbol_name = _ts_node_text(name_node, text_bytes).strip()
            if not symbol_name:
                continue
            symbol_kind = "class" if node.type in _JS_CLASS_COMPONENT_TYPES else "function"
            is_async = bool(
                symbol_kind == "function"
                and any(grandchild.type == "async" for grandchild in getattr(node, "children", []))
            )
            component_type = _classify_component(
                symbol_name,
                symbol_kind=symbol_kind,
                relative_path=relative_path,
                decorators=[],
                is_async=is_async,
            )
            components.append(
                ExtractedComponent(
                    title=symbol_name,
                    component_type=component_type,
                    file_path=relative_path,
                    symbol_name=symbol_name,
                    symbol_kind=symbol_kind,
                    line_start=_ts_line(node, "start_point"),
                    line_end=_ts_line(node, "end_point"),
                    language=language,
                    imports=imports,
                    keywords=_keyword_tokens(symbol_name),
                    ast_fingerprint=_fingerprint(
                        [relative_path, symbol_kind, symbol_name, node.type, "tree_sitter"]
                    ),
                    note=f"{language} {symbol_kind} via tree-sitter",
                )
            )
            if node.type in _JS_CLASS_COMPONENT_TYPES:
                class_name = symbol_name
                for nested in _walk_ts_nodes(node):
                    if nested.type != "method_definition":
                        continue
                    method_name_node = nested.child_by_field_name("name")
                    if method_name_node is None:
                        continue
                    method_name = _ts_node_text(method_name_node, text_bytes).strip()
                    if not method_name:
                        continue
                    qualified_name = f"{class_name}.{method_name}" if class_name else method_name
                    component_type = _classify_component(
                        method_name,
                        symbol_kind="function",
                        relative_path=relative_path,
                        decorators=[],
                        is_async=any(grandchild.type == "async" for grandchild in getattr(nested, "children", [])),
                    )
                    components.append(
                        ExtractedComponent(
                            title=qualified_name,
                            component_type=component_type,
                            file_path=relative_path,
                            symbol_name=qualified_name,
                            symbol_kind="method",
                            line_start=_ts_line(nested, "start_point"),
                            line_end=_ts_line(nested, "end_point"),
                            language=language,
                            imports=imports,
                            keywords=_keyword_tokens(qualified_name.replace(".", "_")),
                            ast_fingerprint=_fingerprint(
                                [relative_path, "method", class_name, method_name, language, "tree_sitter"]
                            ),
                            note=f"{language} class method via tree-sitter",
                        )
                    )
                components.extend(
                    _extract_class_field_components(node, text_bytes, relative_path, language, imports)
                )
            continue
        if node.type in _TS_VAR_COMPONENT_TYPES:
            components.extend(
                _extract_var_components(node, text_bytes, relative_path, language, imports)
            )
            components.extend(
                _extract_object_literal_components(node, text_bytes, relative_path, language, imports)
            )
            continue

    deduped: list[ExtractedComponent] = []
    seen: set[tuple[str, str]] = set()
    for item in components:
        ident = (item.symbol_kind, item.symbol_name)
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append(item)
    return deduped


def _extract_tree_sitter_components(text: str, relative_path: str, language: str) -> list[ExtractedComponent]:
    parser = _build_parser(language)
    if parser is None:
        return []
    if language == "python":
        return _extract_python_ts_components(text, relative_path, parser) + _extract_python_method_components(text, relative_path, parser)
    if language in {"javascript", "typescript", "tsx"}:
        return _extract_js_like_ts_components(text, relative_path, language, parser)
    return []


def _extract_python_components(text: str, relative_path: str) -> list[ExtractedComponent]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    imports: list[str] = []
    components: list[ExtractedComponent] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}:{alias.name}" for alias in node.names)

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            decorators = [ast.unparse(d) for d in node.decorator_list]
            comp_type = _classify_component(
                node.name,
                symbol_kind="class",
                relative_path=relative_path,
                decorators=decorators,
            )
            components.append(
                ExtractedComponent(
                    title=node.name,
                    component_type=comp_type,
                    file_path=relative_path,
                    symbol_name=node.name,
                    symbol_kind="class",
                    line_start=getattr(node, "lineno", None),
                    line_end=getattr(node, "end_lineno", None),
                    language="python",
                    decorators=decorators,
                    imports=imports[:12],
                    keywords=_keyword_tokens(node.name),
                    ast_fingerprint=_fingerprint([relative_path, "class", node.name, *decorators]),
                    note="python top-level class",
                )
            )
            for nested in node.body:
                if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified_name = f"{node.name}.{nested.name}"
                    method_type = _classify_component(
                        nested.name,
                        symbol_kind="function",
                        relative_path=relative_path,
                        decorators=[ast.unparse(d) for d in nested.decorator_list],
                        is_async=isinstance(nested, ast.AsyncFunctionDef),
                    )
                    components.append(
                        ExtractedComponent(
                            title=qualified_name,
                            component_type=method_type,
                            file_path=relative_path,
                            symbol_name=qualified_name,
                            symbol_kind="method",
                            line_start=getattr(nested, "lineno", None),
                            line_end=getattr(nested, "end_lineno", None),
                            language="python",
                            decorators=[ast.unparse(d) for d in nested.decorator_list],
                            imports=imports[:12],
                            keywords=_keyword_tokens(f"{node.name}_{nested.name}"),
                            ast_fingerprint=_fingerprint([relative_path, "method", node.name, nested.name]),
                            note="python class method",
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [ast.unparse(d) for d in node.decorator_list]
            comp_type = _classify_component(
                node.name,
                symbol_kind="function",
                relative_path=relative_path,
                decorators=decorators,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )
            arg_names = [arg.arg for arg in node.args.args]
            components.append(
                ExtractedComponent(
                    title=node.name,
                    component_type=comp_type,
                    file_path=relative_path,
                    symbol_name=node.name,
                    symbol_kind="function",
                    line_start=getattr(node, "lineno", None),
                    line_end=getattr(node, "end_lineno", None),
                    language="python",
                    decorators=decorators,
                    imports=imports[:12],
                    keywords=_keyword_tokens(node.name),
                    ast_fingerprint=_fingerprint([relative_path, "function", node.name, *arg_names, *decorators]),
                    note="python top-level function",
                )
            )
    return components


_JS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "function"),
    (re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "class"),
    (re.compile(r"^(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\([^\)]*\)\s*=>", re.MULTILINE), "function"),
]


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _extract_js_like_components(text: str, relative_path: str, language: str) -> list[ExtractedComponent]:
    components: list[ExtractedComponent] = []
    for pattern, kind in _JS_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group(1)
            line_start = _line_number(text, match.start())
            comp_type = _classify_component(
                name,
                symbol_kind=kind,
                relative_path=relative_path,
                decorators=[],
                is_async="async" in match.group(0),
            )
            components.append(
                ExtractedComponent(
                    title=name,
                    component_type=comp_type,
                    file_path=relative_path,
                    symbol_name=name,
                    symbol_kind=kind,
                    line_start=line_start,
                    line_end=line_start,
                    language=language,
                    keywords=_keyword_tokens(name),
                    ast_fingerprint=_fingerprint([relative_path, kind, name, match.group(0)]),
                    note=f"{language} top-level {kind} heuristic",
                )
            )
    deduped: list[ExtractedComponent] = []
    seen: set[tuple[str, str]] = set()
    for item in components:
        ident = (item.symbol_kind, item.symbol_name)
        if ident in seen:
            continue
        seen.add(ident)
        deduped.append(item)
    return deduped


def extract_components_from_file(repo_path: Path, relative_path: str, max_components: int = 24) -> list[ExtractedComponent]:
    path = repo_path / relative_path
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    language = _detect_language(path)
    components = _extract_tree_sitter_components(text, relative_path, language or "")
    if not components:
        if language == "python":
            components = _extract_python_components(text, relative_path)
        elif language in {"javascript", "typescript", "tsx"}:
            components = _extract_js_like_components(text, relative_path, language)
        else:
            components = []

    if not components:
        module_name = path.stem
        components = [
            ExtractedComponent(
                title=module_name,
                component_type="module",
                file_path=relative_path,
                symbol_name=module_name,
                symbol_kind="module",
                line_start=1,
                line_end=1,
                language=language,
                keywords=_keyword_tokens(module_name),
                ast_fingerprint=_fingerprint([relative_path, "module", module_name]),
                note="module fallback",
            )
        ]

    return components[:max_components]
