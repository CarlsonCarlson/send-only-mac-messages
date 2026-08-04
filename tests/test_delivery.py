"""Regression tests for the cherry-picked upstream delivery verifier."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from send_only_mac_messages.upstream_messages import (
    AttemptState,
    CorrelationConfidence,
    MessageTransport,
    ObservationReason,
    _connect_sqlite_readonly,
    _verify_send_in_db,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration


@pytest.fixture
def messages_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT NOT NULL);
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY,
            guid TEXT NOT NULL,
            error INTEGER NOT NULL,
            is_sent INTEGER NOT NULL,
            is_delivered INTEGER NOT NULL,
            service TEXT NOT NULL,
            text TEXT,
            attributedBody BLOB,
            handle_id INTEGER NOT NULL,
            date INTEGER NOT NULL,
            is_from_me INTEGER NOT NULL
        );
        INSERT INTO handle (ROWID, id) VALUES (1, '+14155551234');
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(
        "send_only_mac_messages.upstream_messages.get_messages_db_path",
        lambda: str(database),
    )
    return database


def _insert_message(
    database: Path,
    *,
    sent_at: float,
    body: str | None,
    service: str,
    is_sent: int = 0,
    is_delivered: int = 0,
    send_error: int = 0,
    attributed_body: bytes | None = None,
) -> None:
    apple_ns = int((sent_at - 978_307_200) * 1_000_000_000)
    connection = sqlite3.connect(database)
    connection.execute(
        """
        INSERT INTO message (
            guid, error, is_sent, is_delivered, service, text,
            attributedBody, handle_id, date, is_from_me
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1)
        """,
        (
            "fixture-guid",
            send_error,
            is_sent,
            is_delivered,
            service,
            body,
            attributed_body,
            apple_ns,
        ),
    )
    connection.commit()
    connection.close()


def test_observer_uses_ten_second_window_and_half_second_polling() -> None:
    fake_time = FakeTime()

    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=fake_time.time,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.sleep",
            side_effect=fake_time.sleep,
        ),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            0.0,
            message_text="hello",
            service=MessageTransport.IMESSAGE,
        )

    assert outcome.state is AttemptState.UNKNOWN
    assert outcome.reason is ObservationReason.MESSAGE_NOT_CORRELATED
    assert fake_time.now == 10.0
    assert fake_time.sleeps == [0.5] * 20


def test_matches_own_message_among_concurrent_sends() -> None:
    rows = [
        {
            "row_id": 2,
            "guid": "guid-2",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
            "text": "second message",
            "attributedBody": None,
        },
        {
            "row_id": 1,
            "guid": "guid-1",
            "send_error": 0,
            "is_sent": 1,
            "is_delivered": 0,
            "service": "iMessage",
            "text": "first message",
            "attributedBody": None,
        },
    ]
    fake_time = FakeTime()
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            side_effect=[rows, [rows[1]]],
        ) as query,
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=fake_time.time,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.sleep",
            side_effect=fake_time.sleep,
        ),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            0.0,
            message_text="first message",
            service=MessageTransport.IMESSAGE,
            timeout=1.0,
        )

    assert outcome.state is AttemptState.SENT_UNCONFIRMED
    assert outcome.actual_transport is MessageTransport.IMESSAGE
    assert outcome.correlation_confidence is CorrelationConfidence.EXACT
    assert outcome.reason is ObservationReason.DELIVERY_TIMEOUT
    assert query.call_args_list[1].args[1] == (1,)


def test_newest_recipient_row_is_not_authoritative_without_exact_body() -> None:
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
    fake_time = FakeTime()
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=rows,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=fake_time.time,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.sleep",
            side_effect=fake_time.sleep,
        ),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            0.0,
            message_text="hello",
            service=MessageTransport.IMESSAGE,
            timeout=0.5,
        )

    assert outcome.state is AttemptState.UNKNOWN
    assert outcome.correlation_confidence is CorrelationConfidence.NONE
    assert outcome.reason is ObservationReason.MESSAGE_NOT_CORRELATED
    assert outcome.fallback_permitted is False


def test_exact_failure_returns_structured_fallback_permission() -> None:
    row = {
        "row_id": 1,
        "guid": "guid-1",
        "send_error": 22,
        "is_sent": 0,
        "is_delivered": 0,
        "service": "iMessage",
        "text": "hello",
        "attributedBody": None,
    }
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[row],
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            0.0,
            message_text="hello",
            service=MessageTransport.IMESSAGE,
        )

    assert outcome.state is AttemptState.FAILED
    assert outcome.actual_transport is MessageTransport.IMESSAGE
    assert outcome.correlation_confidence is CorrelationConfidence.EXACT
    assert outcome.reason is None
    assert outcome.fallback_permitted is True


def test_sms_observer_cannot_resolve_failed_imessage_row(messages_db: Path) -> None:
    sent_at = 2_000_000_000.0
    _insert_message(
        messages_db,
        sent_at=sent_at + 0.1,
        body="hello",
        service="iMessage",
        send_error=22,
    )
    fake_time = FakeTime()

    with (
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=fake_time.time,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.sleep",
            side_effect=fake_time.sleep,
        ),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            sent_at,
            message_text="hello",
            service=MessageTransport.SMS,
            timeout=0.5,
        )

    assert outcome.state is AttemptState.UNKNOWN
    assert outcome.actual_transport is MessageTransport.SMS
    assert outcome.reason is ObservationReason.MESSAGE_NOT_CORRELATED
    assert outcome.fallback_permitted is False


def test_pre_attempt_identical_failure_cannot_authorize_fallback(
    messages_db: Path,
) -> None:
    sent_at = 2_000_000_000.0
    _insert_message(
        messages_db,
        sent_at=sent_at - 0.1,
        body="hello",
        service="iMessage",
        send_error=22,
    )
    fake_time = FakeTime()

    with (
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=fake_time.time,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.sleep",
            side_effect=fake_time.sleep,
        ),
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            sent_at,
            message_text="hello",
            service=MessageTransport.IMESSAGE,
            timeout=0.5,
        )

    assert outcome.state is AttemptState.UNKNOWN
    assert outcome.reason is ObservationReason.MESSAGE_NOT_CORRELATED
    assert outcome.fallback_permitted is False


def test_rcs_row_is_an_exact_sms_attempt_match(messages_db: Path) -> None:
    sent_at = 2_000_000_000.0
    _insert_message(
        messages_db,
        sent_at=sent_at + 0.1,
        body="hello",
        service="RCS",
        is_delivered=1,
    )

    with patch(
        "send_only_mac_messages.upstream_messages.time.time",
        return_value=sent_at,
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            sent_at,
            message_text="hello",
            service=MessageTransport.SMS,
        )

    assert outcome.state is AttemptState.DELIVERED
    assert outcome.actual_transport is MessageTransport.RCS
    assert outcome.correlation_confidence is CorrelationConfidence.EXACT


def test_decoded_attributed_body_can_correlate_exact_attempt(messages_db: Path) -> None:
    sent_at = 2_000_000_000.0
    body = "hello"
    attributed_body = (
        b"NSString" + b"\x01\x00\x84\x01+" + bytes([len(body)]) + body.encode()
    )
    _insert_message(
        messages_db,
        sent_at=sent_at + 0.1,
        body=None,
        attributed_body=attributed_body,
        service="iMessage",
        is_delivered=1,
    )

    with patch(
        "send_only_mac_messages.upstream_messages.time.time",
        return_value=sent_at,
    ):
        outcome = _verify_send_in_db(
            "+14155551234",
            sent_at,
            message_text=body,
            service=MessageTransport.IMESSAGE,
        )

    assert outcome.state is AttemptState.DELIVERED
    assert outcome.correlation_confidence is CorrelationConfidence.EXACT


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
