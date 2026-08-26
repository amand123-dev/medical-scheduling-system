"""
Contract tests for the MCP server.

The MCP server is a thin HTTP adapter, so the thing that actually breaks is
drift: a route gets renamed or re-prefixed in the API and the tool keeps
calling the old path. Nothing in the type system catches that.

These tests parse the tool bodies for their request paths and assert each one
resolves against the real FastAPI route table. They read the source rather than
importing it, so the API test suite never depends on the MCP SDK being
installed (it lives in a separate environment — see mcp_server/requirements.txt).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.main import app

SERVER_PY = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"


def _tool_paths() -> list[str]:
    """Every path literal passed to _get() in server.py, as a route template."""
    tree = ast.parse(SERVER_PY.read_text())
    paths: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_get"):
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant):
            paths.append(arg.value)
        elif isinstance(arg, ast.JoinedStr):
            # f"/scorer/risk/{patient_uuid}" -> /scorer/risk/{patient_uuid}
            parts = []
            for v in arg.values:
                if isinstance(v, ast.Constant):
                    parts.append(v.value)
                else:
                    parts.append(f"{{{ast.unparse(v.value)}}}")
            paths.append("".join(parts))
    return paths


def _route_matches(tool_path: str, route_path: str) -> bool:
    """A tool path matches a route if they agree once path params are wildcarded."""
    pattern = re.sub(
        r"\{[^}]+\}", "[^/]+", re.escape(route_path).replace(r"\{", "{").replace(r"\}", "}")
    )
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", pattern)
    return re.fullmatch(pattern, tool_path) is not None


@pytest.fixture(scope="module")
def api_paths() -> list[str]:
    return [r.path for r in app.routes if hasattr(r, "path")]


def test_server_module_exists():
    assert SERVER_PY.exists(), "mcp_server/server.py is missing"


def test_tools_are_discovered():
    paths = _tool_paths()
    assert len(paths) >= 8, f"expected the full tool set, found {len(paths)}"


@pytest.mark.parametrize("tool_path", _tool_paths())
def test_every_tool_path_exists_in_the_api(tool_path: str, api_paths: list[str]):
    """Catches route renames and prefix drift between the API and the MCP adapter."""
    assert any(_route_matches(tool_path, rp) for rp in api_paths), (
        f"MCP tool calls {tool_path!r}, which is not a route in the FastAPI app. "
        f"Closest routes: {sorted(api_paths, key=lambda p: -len(set(p) & set(tool_path)))[:3]}"
    )


def test_no_tool_reaches_the_database_directly():
    """The MCP server must go through the API so role checks and audit logging apply."""
    src = SERVER_PY.read_text()
    for forbidden in ("sqlalchemy", "asyncpg", "get_session", "app.identity", "app.rag.retrieval"):
        assert forbidden not in src, (
            f"mcp_server/server.py references {forbidden!r}. The MCP server must call the "
            "HTTP API, not the database, so that role gating and identity_access_log apply."
        )


def test_patient_tool_is_documented_as_audited():
    """A tool that reads patient documents must say so in its description."""
    src = SERVER_PY.read_text()
    block = src.split("async def get_patient_context")[0].split("@mcp.tool")[-1]
    assert "AUDITED" in block.upper(), "get_patient_context must declare that it is audited"


def test_no_pii_terms_in_tool_surface():
    """Tool descriptions must not invite name-based lookup."""
    src = SERVER_PY.read_text().lower()
    assert "hipaa compliant" not in src, 'use "HIPAA-aware", never "HIPAA compliant"'
