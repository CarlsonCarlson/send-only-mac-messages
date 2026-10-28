"""Contract tests proving the MCP has one send tool and one narrow observer."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from unittest.mock import patch

from send_only_mac_messages.remote import (
    REMOTE_RESULT_BUSY,
    REMOTE_RESULT_SENDER_MISMATCH,
)
from send_only_mac_messages.sender import RESULT_TOKENS
from send_only_mac_messages.server import mcp, tool_send_message

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "send_only_mac_messages"


def test_mcp_exposes_exactly_one_send_tool() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["tool_send_message"]
    assert "chat id" in tools[0].inputSchema["properties"]["recipient"]["description"]
    assert set(tools[0].inputSchema["properties"]) == {
        "recipient",
        "message",
        "delivery_mode",
    }
    assert set(tools[0].inputSchema["required"]) == {
        "recipient",
        "message",
        "delivery_mode",
    }
    assert tools[0].inputSchema["properties"]["delivery_mode"]["enum"] == [
        "imessage_only",
        "imessage_with_sms_fallback",
        "sms_only",
    ]
    assert tools[0].annotations is not None
    assert tools[0].annotations.readOnlyHint is False
    assert tools[0].annotations.destructiveHint is True
    assert tools[0].annotations.idempotentHint is False
    assert tools[0].annotations.openWorldHint is True


def test_tool_description_explains_every_result_token() -> None:
    description = asyncio.run(mcp.list_tools())[0].description or ""

    for token in (*RESULT_TOKENS, REMOTE_RESULT_SENDER_MISMATCH, REMOTE_RESULT_BUSY):
        generic = re.sub(r":(iMessage|SMS)\b", ":<service>", token)
        assert token in description or generic in description, token
    for mode in ("imessage_only", "imessage_with_sms_fallback", "sms_only"):
        assert mode in description
    assert "two bubbles" in description
    assert "twice" in description


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
    # The chat table may appear only as a JOIN filtered to the exact chat guid.
    assert observer.count("JOIN chat c ON") == 1
    assert observer.count("c.guid = ?") == 1
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
    description = manifest["tools"][0]["description"]
    for mode in ("imessage_only", "imessage_with_sms_fallback", "sms_only"):
        assert mode in description
    assert "group" in description


def test_tool_logs_and_result_do_not_echo_send_data(caplog) -> None:
    recipient = "+14155551234"
    message = "private body"

    with patch(
        "send_only_mac_messages.server.send_message",
        return_value="error:send_status_unknown:iMessage:message-not-correlated",
    ) as sender:
        result = tool_send_message(recipient, message, "imessage_only")

    assert result == "error:send_status_unknown:iMessage:message-not-correlated"
    sender.assert_called_once_with(recipient, message, "imessage_only")
    assert recipient not in caplog.text
    assert message not in caplog.text


def test_database_error_details_are_redacted_from_mcp_result_and_logs(caplog) -> None:
    recipient = "+14155551234"
    message = "private body"
    private_database_error = "private database path and permission detail"

    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[{"error": private_database_error}],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=[0.0, 0.0, 0.0, 11.0],
        ),
    ):
        result = tool_send_message(
            recipient,
            message,
            "imessage_with_sms_fallback",
        )

    assert result == "error:send_status_unknown:iMessage:database-unavailable"
    assert private_database_error not in result
    assert private_database_error not in caplog.text
    assert recipient not in caplog.text
    assert message not in caplog.text


def test_candidate_details_and_messages_error_code_are_redacted(caplog) -> None:
    recipient = "+14155551234"
    message = "private body"
    private_guid = "private-guid"
    private_candidate_state = "private-candidate-state"
    failed_row = {
        "row_id": 987654,
        "guid": private_guid,
        "send_error": 22,
        "is_sent": 0,
        "is_delivered": 0,
        "service": "iMessage",
        "text": message,
        "attributedBody": None,
        "candidate_state": private_candidate_state,
    }

    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            side_effect=["success", "error:private SMS error"],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[failed_row],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=[100.0, 100.0, 100.0, 200.0],
        ),
    ):
        result = tool_send_message(recipient, message, "imessage_only")

    assert result == "error:send_failed:iMessage"
    combined_output = f"{result}\n{caplog.text}"
    for private_value in (
        recipient,
        message,
        private_guid,
        private_candidate_state,
        "987654",
        "22",
        "private SMS error",
    ):
        assert private_value not in combined_output
