"""Regression tests for the cherry-picked upstream delivery verifier."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from send_only_mac_messages.upstream_messages import (
    _connect_sqlite_readonly,
    _report_send_outcome,
    _verify_send_in_db,
)


def test_matches_own_message_among_concurrent_sends() -> None:
    rows = [
        {
            "guid": "guid-2",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
            "text": "second message",
            "attributedBody": None,
        },
        {
            "guid": "guid-1",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
            "text": "first message",
            "attributedBody": None,
        },
    ]
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=rows,
        ),
        patch("send_only_mac_messages.upstream_messages.time") as mock_time,
    ):
        mock_time.time.side_effect = [0.0, 0.0]
        row = _verify_send_in_db("+14155551234", 0.0, message_text="first message")

    assert row is not None
    assert row["guid"] == "guid-1"


def test_falls_back_to_latest_row_when_no_body_matches() -> None:
    rows = [
        {
            "guid": "guid-1",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
            "text": None,
            "attributedBody": None,
        }
    ]
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=rows,
        ),
        patch("send_only_mac_messages.upstream_messages.time") as mock_time,
    ):
        mock_time.time.side_effect = [0.0, 0.0]
        row = _verify_send_in_db("+14155551234", 0.0, message_text="hello")

    assert row is not None
    assert row["guid"] == "guid-1"


def test_report_send_outcome_preserves_upstream_failure_behavior() -> None:
    row = {
        "guid": "guid-1",
        "send_error": 22,
        "is_sent": 0,
        "is_delivered": 0,
        "service": "iMessage",
        "text": "hello",
        "attributedBody": None,
    }
    with patch(
        "send_only_mac_messages.upstream_messages._verify_send_in_db",
        return_value=row,
    ):
        result = _report_send_outcome(
            "+14155551234", "recipient", "iMessage", 0.0, "hello"
        )

    assert "failed to send" in result
    assert "error code 22" in result


def test_database_connection_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    writable = sqlite3.connect(database)
    writable.execute("CREATE TABLE message (id INTEGER)")
    writable.commit()
    writable.close()

    connection = _connect_sqlite_readonly(str(database))
    with pytest.raises(sqlite3.OperationalError):
        connection.execute("INSERT INTO message VALUES (1)")
    connection.close()
