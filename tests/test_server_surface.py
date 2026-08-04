"""Contract tests proving the MCP has one send tool and one narrow observer."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from send_only_mac_messages.server import mcp, tool_send_message

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "send_only_mac_messages"


def test_mcp_exposes_exactly_one_send_tool() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["tool_send_message"]
    assert tools[0].description is not None
    assert "immediate SMS fallback" in tools[0].description
    assert set(tools[0].inputSchema["properties"]) == {"recipient", "message"}
    assert tools[0].annotations is not None
    assert tools[0].annotations.readOnlyHint is False
    assert tools[0].annotations.destructiveHint is True
    assert tools[0].annotations.idempotentHint is False
    assert tools[0].annotations.openWorldHint is True


def test_mcp_exposes_no_resources_or_prompts() -> None:
    assert asyncio.run(mcp.list_resources()) == []
    assert asyncio.run(mcp.list_prompts()) == []


def test_only_upstream_subset_contains_local_messages_database_access() -> None:
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
    }
    reader_markers = ("sqlite3", "chat.db", "Library/Messages")

    assert {
        name
        for name, source in sources.items()
        if any(marker in source for marker in reader_markers)
    } == {"upstream_messages.py"}

    observer = sources["upstream_messages.py"]
    assert "FROM message" in observer
    assert "JOIN handle" in observer
    assert "m.is_from_me = 1" in observer
    assert "LIMIT 10" in observer
    for forbidden in (
        "FROM chat",
        "FROM attachment",
        "AddressBook",
        "SELECT *",
        "INSERT INTO",
        "UPDATE ",
        "DELETE ",
    ):
        assert forbidden not in observer


def test_manifest_declares_only_the_send_tool() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert [tool["name"] for tool in manifest["tools"]] == ["tool_send_message"]


def test_tool_logs_and_result_do_not_echo_send_data(caplog) -> None:
    recipient = "+14155551234"
    message = "private body"

    with patch(
        "send_only_mac_messages.server.send_message",
        return_value="accepted-unverified:iMessage",
    ):
        result = tool_send_message(recipient, message)

    assert result == "accepted-unverified:iMessage"
    assert recipient not in caplog.text
    assert message not in caplog.text
