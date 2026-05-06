from __future__ import annotations

from types import SimpleNamespace

import pytest

import claw.mining.component_extractor as component_extractor
from claw.mining.component_extractor import extract_components_from_file


def test_extract_python_components(tmp_path):
    repo = tmp_path
    (repo / "service.py").write_text(
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def db_fixture():\n    return 1\n\n"
        "class TokenManager:\n    pass\n\n"
        "async def queue_worker(job):\n    return job\n\n"
        "def validate_payload(data):\n    return data\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "db_fixture" in by_name
    assert by_name["db_fixture"].component_type == "test_fixture"
    assert "TokenManager" in by_name
    assert by_name["TokenManager"].symbol_kind == "class"
    assert "queue_worker" in by_name
    assert by_name["queue_worker"].component_type == "worker"
    assert "validate_payload" in by_name
    assert by_name["validate_payload"].component_type == "validator"
    assert "TokenManager" in by_name


def test_extract_python_class_methods(tmp_path):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class TokenManager:\n"
        "    async def refresh_session(self, token):\n"
        "        return token\n\n"
        "    def validate_payload(self, data):\n"
        "        return data\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "TokenManager.refresh_session" in by_name
    assert by_name["TokenManager.refresh_session"].symbol_kind == "method"
    assert by_name["TokenManager.refresh_session"].component_type == "helper"
    assert "TokenManager.validate_payload" in by_name
    assert by_name["TokenManager.validate_payload"].component_type == "validator"


def test_extract_python_decorated_class_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class TokenManager:\n"
        "    @pytest.fixture\n"
        "    async def db_fixture(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )

    class_name = _FakeNode("identifier", "TokenManager", start_line=0, end_line=0)
    method_name = _FakeNode("identifier", "db_fixture", start_line=2, end_line=2)
    decorator = _FakeNode("decorator", "@pytest.fixture", start_line=1, end_line=1)
    method_def = _FakeNode(
        "function_definition",
        "async def db_fixture(self): return 1",
        fields={"name": method_name},
        children=[_FakeNode("async", "async"), method_name],
        start_line=2,
        end_line=3,
    )
    decorated_method = _FakeNode(
        "decorated_definition",
        children=[decorator, method_def],
        start_line=1,
        end_line=3,
    )
    class_def = _FakeNode(
        "class_definition",
        "class TokenManager: ...",
        fields={"name": class_name},
        children=[class_name, decorated_method],
        start_line=0,
        end_line=3,
    )
    root = _FakeNode("module", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "python" else None,
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "TokenManager.db_fixture" in by_name
    assert by_name["TokenManager.db_fixture"].symbol_kind == "method"
    assert by_name["TokenManager.db_fixture"].component_type == "test_fixture"
    assert "@pytest.fixture" in by_name["TokenManager.db_fixture"].decorators


def test_extract_python_property_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class TokenManager:\n"
        "    @property\n"
        "    def access_token(self):\n"
        "        return 'x'\n",
        encoding="utf-8",
    )

    class_name = _FakeNode("identifier", "TokenManager", start_line=0, end_line=0)
    method_name = _FakeNode("identifier", "access_token", start_line=2, end_line=2)
    decorator = _FakeNode("decorator", "@property", start_line=1, end_line=1)
    method_def = _FakeNode(
        "function_definition",
        "def access_token(self): return 'x'",
        fields={"name": method_name},
        children=[method_name],
        start_line=2,
        end_line=3,
    )
    decorated_method = _FakeNode(
        "decorated_definition",
        children=[decorator, method_def],
        start_line=1,
        end_line=3,
    )
    class_def = _FakeNode(
        "class_definition",
        "class TokenManager: ...",
        fields={"name": class_name},
        children=[class_name, decorated_method],
        start_line=0,
        end_line=3,
    )
    root = _FakeNode("module", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "python" else None,
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "TokenManager.access_token" in by_name
    assert by_name["TokenManager.access_token"].symbol_kind == "method"
    assert "@property" in by_name["TokenManager.access_token"].decorators


def test_extract_python_classmethod_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class TokenManager:\n"
        "    @classmethod\n"
        "    def build(cls):\n"
        "        return cls()\n",
        encoding="utf-8",
    )

    class_name = _FakeNode("identifier", "TokenManager", start_line=0, end_line=0)
    method_name = _FakeNode("identifier", "build", start_line=2, end_line=2)
    decorator = _FakeNode("decorator", "@classmethod", start_line=1, end_line=1)
    method_def = _FakeNode(
        "function_definition",
        "def build(cls): return cls()",
        fields={"name": method_name},
        children=[method_name],
        start_line=2,
        end_line=3,
    )
    decorated_method = _FakeNode(
        "decorated_definition",
        children=[decorator, method_def],
        start_line=1,
        end_line=3,
    )
    class_def = _FakeNode(
        "class_definition",
        "class TokenManager: ...",
        fields={"name": class_name},
        children=[class_name, decorated_method],
        start_line=0,
        end_line=3,
    )
    root = _FakeNode("module", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "python" else None,
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "TokenManager.build" in by_name
    assert by_name["TokenManager.build"].symbol_kind == "method"
    assert "@classmethod" in by_name["TokenManager.build"].decorators


def test_extract_python_staticmethod_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class TokenManager:\n"
        "    @staticmethod\n"
        "    def normalize(token):\n"
        "        return token.strip()\n",
        encoding="utf-8",
    )

    class_name = _FakeNode("identifier", "TokenManager", start_line=0, end_line=0)
    method_name = _FakeNode("identifier", "normalize", start_line=2, end_line=2)
    decorator = _FakeNode("decorator", "@staticmethod", start_line=1, end_line=1)
    method_def = _FakeNode(
        "function_definition",
        "def normalize(token): return token.strip()",
        fields={"name": method_name},
        children=[method_name],
        start_line=2,
        end_line=3,
    )
    decorated_method = _FakeNode(
        "decorated_definition",
        children=[decorator, method_def],
        start_line=1,
        end_line=3,
    )
    class_def = _FakeNode(
        "class_definition",
        "class TokenManager: ...",
        fields={"name": class_name},
        children=[class_name, decorated_method],
        start_line=0,
        end_line=3,
    )
    root = _FakeNode("module", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "python" else None,
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "TokenManager.normalize" in by_name
    assert by_name["TokenManager.normalize"].symbol_kind == "method"
    assert "@staticmethod" in by_name["TokenManager.normalize"].decorators


def test_extract_typescript_components(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "export async function tokenRefreshWorker() { return true }\n"
        "export class AuthClient {}\n"
        "export const validateToken = (token) => !!token\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert by_name["tokenRefreshWorker"].component_type == "worker"
    assert by_name["AuthClient"].symbol_kind == "class"
    assert by_name["validateToken"].component_type == "validator"


def test_extract_typescript_class_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { refreshSession() { return true } }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    method_name = _FakeNode("property_identifier", "refreshSession", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "refreshSession() { return true }",
        fields={"name": method_name},
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { refreshSession() { return true } }",
        fields={"name": class_name},
        children=[method_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.refreshSession" in by_name
    assert by_name["AuthClient.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.refreshSession"].note


def test_extract_typescript_object_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export const authApi = { refreshSession() { return true } }\n", encoding="utf-8")

    object_name = _FakeNode("identifier", "authApi", start_line=0, end_line=0)
    method_name = _FakeNode("property_identifier", "refreshSession", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "refreshSession() { return true }",
        fields={"name": method_name},
        start_line=0,
        end_line=1,
    )
    object_value = _FakeNode("object", children=[method_def], start_line=0, end_line=1)
    declarator = _FakeNode(
        "variable_declarator",
        "authApi = { refreshSession() { return true } }",
        fields={"name": object_name, "value": object_value},
        children=[object_name, object_value],
        start_line=0,
        end_line=1,
    )
    lexical = _FakeNode("lexical_declaration", children=[declarator], start_line=0, end_line=1)
    root = _FakeNode("program", children=[lexical])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "authApi.refreshSession" in by_name
    assert by_name["authApi.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["authApi.refreshSession"].note


def test_extract_typescript_string_key_object_functions_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text('export const authApi = { "refresh-session": async () => true }\n', encoding="utf-8")

    object_name = _FakeNode("identifier", "authApi", start_line=0, end_line=0)
    key_name = _FakeNode("string", '"refresh-session"', start_line=0, end_line=0)
    pair_value = _FakeNode("arrow_function", "async () => true", children=[_FakeNode("async", "async")], start_line=0, end_line=0)
    pair = _FakeNode(
        "pair",
        '"refresh-session": async () => true',
        fields={"key": key_name, "value": pair_value},
        children=[key_name, pair_value],
        start_line=0,
        end_line=1,
    )
    object_value = _FakeNode("object", children=[pair], start_line=0, end_line=1)
    declarator = _FakeNode(
        "variable_declarator",
        'authApi = { "refresh-session": async () => true }',
        fields={"name": object_name, "value": object_value},
        children=[object_name, object_value],
        start_line=0,
        end_line=1,
    )
    lexical = _FakeNode("lexical_declaration", children=[declarator], start_line=0, end_line=1)
    root = _FakeNode("program", children=[lexical])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "authApi.refresh-session" in by_name
    assert by_name["authApi.refresh-session"].symbol_kind == "method"
    assert "tree-sitter" in by_name["authApi.refresh-session"].note


def test_extract_typescript_class_field_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { refreshSession = async () => true }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    field_name = _FakeNode("property_identifier", "refreshSession", start_line=0, end_line=0)
    field_value = _FakeNode("arrow_function", "async () => true", children=[_FakeNode("async", "async")], start_line=0, end_line=0)
    field_def = _FakeNode(
        "field_definition",
        "refreshSession = async () => true",
        fields={"name": field_name, "value": field_value},
        children=[field_name, field_value],
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { refreshSession = async () => true }",
        fields={"name": class_name},
        children=[field_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.refreshSession" in by_name
    assert by_name["AuthClient.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.refreshSession"].note


def test_extract_typescript_private_class_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { #refreshSession() { return true } }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    method_name = _FakeNode("private_property_identifier", "#refreshSession", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "#refreshSession() { return true }",
        fields={"name": method_name},
        children=[method_name],
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { #refreshSession() { return true } }",
        fields={"name": class_name},
        children=[method_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.#refreshSession" in by_name
    assert by_name["AuthClient.#refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.#refreshSession"].note


def test_extract_typescript_getter_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { get token() { return 'x' } }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    method_name = _FakeNode("property_identifier", "token", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "get token() { return 'x' }",
        fields={"name": method_name},
        children=[_FakeNode("get", "get"), method_name],
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { get token() { return 'x' } }",
        fields={"name": class_name},
        children=[method_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.token" in by_name
    assert by_name["AuthClient.token"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.token"].note


def test_extract_typescript_static_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { static build() { return new AuthClient() } }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    method_name = _FakeNode("property_identifier", "build", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "static build() { return new AuthClient() }",
        fields={"name": method_name},
        children=[_FakeNode("static", "static"), method_name],
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { static build() { return new AuthClient() } }",
        fields={"name": class_name},
        children=[method_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.build" in by_name
    assert by_name["AuthClient.build"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.build"].note


def test_extract_typescript_setter_methods_with_tree_sitter_stub(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export class AuthClient { set token(value) { this._token = value } }\n", encoding="utf-8")

    class_name = _FakeNode("identifier", "AuthClient", start_line=0, end_line=0)
    method_name = _FakeNode("property_identifier", "token", start_line=0, end_line=0)
    method_def = _FakeNode(
        "method_definition",
        "set token(value) { this._token = value }",
        fields={"name": method_name},
        children=[_FakeNode("set", "set"), method_name],
        start_line=0,
        end_line=1,
    )
    class_def = _FakeNode(
        "class_declaration",
        "class AuthClient { set token(value) { this._token = value } }",
        fields={"name": class_name},
        children=[method_def],
        start_line=0,
        end_line=1,
    )
    root = _FakeNode("program", children=[class_def])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.token" in by_name
    assert by_name["AuthClient.token"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.token"].note


class _FakeNode:
    def __init__(
        self,
        node_type,
        text="",
        *,
        children=None,
        fields=None,
        start_line=0,
        end_line=0,
        start_byte=0,
        end_byte=0,
    ):
        self.type = node_type
        self.text = text.encode("utf-8")
        self.children = children or []
        self._fields = fields or {}
        self.start_point = (start_line, 0)
        self.end_point = (end_line, 0)
        self.start_byte = start_byte
        self.end_byte = end_byte

    def child_by_field_name(self, name):
        return self._fields.get(name)


class _FakeTree:
    def __init__(self, root_node):
        self.root_node = root_node


class _FakeParser:
    def __init__(self, root_node):
        self._root_node = root_node

    def parse(self, _text):
        return _FakeTree(self._root_node)


def test_extract_python_components_uses_tree_sitter_when_available(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "service.py").write_text("def ignored():\n    pass\n", encoding="utf-8")

    name_node = _FakeNode("identifier", "ts_worker", start_line=0, end_line=0)
    func_node = _FakeNode(
        "function_definition",
        "def ts_worker(): pass",
        fields={"name": name_node},
        start_line=0,
        end_line=2,
    )
    import_node = _FakeNode("import_statement", "import requests", start_line=0, end_line=0)
    root = _FakeNode("module", children=[import_node, func_node])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "python" else None,
    )

    comps = extract_components_from_file(repo, "service.py")

    assert len(comps) == 1
    assert comps[0].symbol_name == "ts_worker"
    assert comps[0].note == "python function via tree-sitter"
    assert comps[0].imports == ["import requests"]


def test_extract_typescript_components_uses_tree_sitter_when_available(tmp_path, monkeypatch):
    repo = tmp_path
    (repo / "api.ts").write_text("export const ignored = () => true\n", encoding="utf-8")

    name_node = _FakeNode("identifier", "validateToken", start_line=0, end_line=0)
    value_node = _FakeNode("arrow_function", "() => true", start_line=0, end_line=0)
    declarator = _FakeNode(
        "variable_declarator",
        "validateToken = () => true",
        fields={"name": name_node, "value": value_node},
        start_line=0,
        end_line=1,
    )
    lexical = _FakeNode("lexical_declaration", children=[declarator], start_line=0, end_line=1)
    root = _FakeNode("program", children=[lexical])

    monkeypatch.setattr(
        component_extractor,
        "_build_parser",
        lambda language: _FakeParser(root) if language == "typescript" else None,
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "validateToken" in by_name
    assert by_name["validateToken"].note == "typescript variable function via tree-sitter"
    assert by_name["validateToken"].component_type == "validator"


def _has_real_tree_sitter(language: str) -> bool:
    return component_extractor._build_parser(language) is not None


def test_declared_typescript_tree_sitter_parser_loads():
    assert component_extractor._build_parser("typescript") is not None


@pytest.mark.skipif(not _has_real_tree_sitter("python"), reason="tree-sitter python parser not installed")
def test_real_tree_sitter_extracts_python_decorated_async_shapes(tmp_path):
    repo = tmp_path
    (repo / "service.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.post('/refresh')\n"
        "async def refresh_session(token: str):\n"
        "    return token\n\n"
        "@router.get('/health')\n"
        "def health_check():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert by_name["refresh_session"].component_type == "route_handler"
    assert "tree-sitter" in by_name["refresh_session"].note
    assert by_name["health_check"].component_type == "route_handler"
    assert by_name["refresh_session"].imports


@pytest.mark.skipif(not _has_real_tree_sitter("python"), reason="tree-sitter python parser not installed")
def test_real_tree_sitter_extracts_python_class_methods(tmp_path):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class AuthClient:\n"
        "    async def refresh_session(self, token: str):\n"
        "        return token\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.refresh_session" in by_name
    assert by_name["AuthClient.refresh_session"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.refresh_session"].note


@pytest.mark.skipif(not _has_real_tree_sitter("python"), reason="tree-sitter python parser not installed")
def test_real_tree_sitter_extracts_python_staticmethod_methods(tmp_path):
    repo = tmp_path
    (repo / "service.py").write_text(
        "class AuthClient:\n"
        "    @staticmethod\n"
        "    def normalize(token: str):\n"
        "        return token.strip()\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "service.py")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.normalize" in by_name
    assert by_name["AuthClient.normalize"].symbol_kind == "method"
    assert "@staticmethod" in by_name["AuthClient.normalize"].decorators
    assert "tree-sitter" in by_name["AuthClient.normalize"].note


@pytest.mark.skipif(not _has_real_tree_sitter("typescript"), reason="tree-sitter typescript parser not installed")
def test_real_tree_sitter_extracts_typescript_function_class_and_arrow_shapes(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "import { client } from './client'\n"
        "export async function tokenRefreshWorker() { return client }\n"
        "export class AuthClient {}\n"
        "export const validateToken = (token: string) => !!token\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert by_name["tokenRefreshWorker"].component_type == "worker"
    assert "tree-sitter" in by_name["tokenRefreshWorker"].note
    assert by_name["AuthClient"].symbol_kind == "class"
    assert "tree-sitter" in by_name["AuthClient"].note
    assert by_name["validateToken"].component_type == "validator"
    assert by_name["validateToken"].imports


@pytest.mark.skipif(not _has_real_tree_sitter("typescript"), reason="tree-sitter typescript parser not installed")
def test_real_tree_sitter_extracts_typescript_class_methods(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "export class AuthClient {\n"
        "  async refreshSession(token: string) { return token }\n"
        "}\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.refreshSession" in by_name
    assert by_name["AuthClient.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.refreshSession"].note


@pytest.mark.skipif(not _has_real_tree_sitter("typescript"), reason="tree-sitter typescript parser not installed")
def test_real_tree_sitter_extracts_typescript_setter_methods(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "export class AuthClient {\n"
        "  set token(value: string) { this._token = value }\n"
        "}\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.token" in by_name
    assert by_name["AuthClient.token"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.token"].note


@pytest.mark.skipif(not _has_real_tree_sitter("typescript"), reason="tree-sitter typescript parser not installed")
def test_real_tree_sitter_extracts_typescript_object_methods(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "export const authApi = {\n"
        "  async refreshSession(token: string) { return token },\n"
        "  validateToken: (token: string) => !!token,\n"
        "}\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "authApi.refreshSession" in by_name
    assert by_name["authApi.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["authApi.refreshSession"].note
    assert "authApi.validateToken" in by_name


@pytest.mark.skipif(not _has_real_tree_sitter("typescript"), reason="tree-sitter typescript parser not installed")
def test_real_tree_sitter_extracts_typescript_class_field_methods(tmp_path):
    repo = tmp_path
    (repo / "api.ts").write_text(
        "export class AuthClient {\n"
        "  refreshSession = async (token: string) => token\n"
        "}\n",
        encoding="utf-8",
    )

    comps = extract_components_from_file(repo, "api.ts")
    by_name = {c.symbol_name: c for c in comps}

    assert "AuthClient.refreshSession" in by_name
    assert by_name["AuthClient.refreshSession"].symbol_kind == "method"
    assert "tree-sitter" in by_name["AuthClient.refreshSession"].note
