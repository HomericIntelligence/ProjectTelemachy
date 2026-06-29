"""Tests for the read-only MCP server (issue #173)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from telemachy.mcp_server import _TOOLS, Dispatcher, MissingArgumentError, UnknownToolError


def test_list_tools_exposes_only_read_only_tool_names() -> None:
    dispatcher = Dispatcher(AsyncMock())
    names = {t.name for t in dispatcher.list_tools()}
    assert names == {"agamemnon_list_agents", "agamemnon_list_team_tasks"}


def test_tool_descriptors_have_object_input_schemas() -> None:
    for tool in _TOOLS:
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_call_tool_list_agents_delegates_to_client() -> None:
    client = AsyncMock()
    client.list_agents.return_value = [{"id": "a1"}, {"id": "a2"}]
    dispatcher = Dispatcher(client)
    text = await dispatcher.call_tool("agamemnon_list_agents", {})
    assert json.loads(text) == [{"id": "a1"}, {"id": "a2"}]
    client.list_agents.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_call_tool_list_team_tasks_passes_team_id() -> None:
    client = AsyncMock()
    client.get_tasks.return_value = [{"subject": "build"}]
    dispatcher = Dispatcher(client)
    text = await dispatcher.call_tool("agamemnon_list_team_tasks", {"team_id": "t-42"})
    assert json.loads(text) == [{"subject": "build"}]
    client.get_tasks.assert_awaited_once_with("t-42")


@pytest.mark.asyncio
async def test_call_tool_unknown_name_raises() -> None:
    dispatcher = Dispatcher(AsyncMock())
    with pytest.raises(UnknownToolError):
        await dispatcher.call_tool("agamemnon_delete_agent", {})


@pytest.mark.asyncio
async def test_call_tool_missing_team_id_raises_descriptive_error() -> None:
    """Omitting the required team_id must raise a descriptive ValueError,
    not a bare KeyError that would crash the stdio server."""
    client = AsyncMock()
    dispatcher = Dispatcher(client)
    with pytest.raises(MissingArgumentError, match="team_id"):
        await dispatcher.call_tool("agamemnon_list_team_tasks", {})
    client.get_tasks.assert_not_awaited()


def test_missing_argument_error_is_value_error() -> None:
    """MissingArgumentError stays a ValueError so the SDK/_call_tool surfaces
    it as a structured bad-request, consistent with UnknownToolError."""
    assert issubclass(MissingArgumentError, ValueError)


def test_module_has_no_write_method_references() -> None:
    """Belt-and-suspenders: forbid write methods from appearing in the module text."""
    src = Path("src/telemachy/mcp_server.py").read_text()
    forbidden = [
        "create_agent",
        "start_agent",
        "delete_agent",
        "create_team",
        "create_task",
        "create_tasks",
        "assign_task",
        "teardown",
    ]
    for name in forbidden:
        assert name not in src, f"write-path symbol leaked into MCP server: {name}"


def test_build_server_is_thin_adapter_that_delegates_to_dispatcher() -> None:
    """build_server() must not duplicate dispatcher logic — verify by source inspection.

    The dispatcher is the unit-tested seam; build_server() should only wire
    decorators into the SDK. Keeps the read-only invariant single-sourced.
    """
    src = Path("src/telemachy/mcp_server.py").read_text()
    # build_server must reference dispatcher.list_tools and dispatcher.call_tool
    assert "dispatcher.list_tools()" in src
    assert "dispatcher.call_tool(" in src
