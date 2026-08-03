"""Contract tests proving that the MCP surface is physically send-only."""

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
    assert set(tools[0].inputSchema["properties"]) == {"recipient", "message"}


def test_mcp_exposes_no_resources_or_prompts() -> None:
    assert asyncio.run(mcp.list_resources()) == []
    assert asyncio.run(mcp.list_prompts()) == []


def test_package_contains_no_local_data_reader() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py"))
    )

    for forbidden in (
        "sqlite3",
        "chat.db",
        "AddressBook",
        "Library/Messages",
        "Full Disk Access",
    ):
        assert forbidden not in source


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
