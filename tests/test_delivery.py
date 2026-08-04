"""Regression tests for exact, transient delivery observation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from send_only_mac_messages.upstream_messages import (
    OBSERVATION_POLL_SECONDS,
    OBSERVATION_TIMEOUT_SECONDS,
    AttemptState,
    CorrelationConfidence,
    DeliveryService,
    OutcomeReason,
    _connect_sqlite_readonly,
    _verify_send_in_db,
)

TARGET = "+14155551234"
BODY = "fixture body"


def row(
    *,
    row_id: int = 41,
    body: str | None = BODY,
    attributed_body: bytes | None = None,
    service: str = "iMessage",
    send_error: int = 0,
    is_sent: int = 0,
    is_delivered: int = 0,
    handle: str = TARGET,
) -> dict[str, object]:
    return {
        "row_id": row_id,
        "guid": "fixture-guid",
        "send_error": send_error,
        "is_sent": is_sent,
        "is_delivered": is_delivered,
        "service": service,
        "text": body,
        "attributedBody": attributed_body,
        "handle": handle,
    }


def attributed_blob(text: str) -> bytes:
    encoded = text.encode("utf-8")
    assert len(encoded) < 0x80
    return b"NSString" + b"\x01\x00\x84\x01+" + bytes([len(encoded)]) + encoded


def observe_once(
    rows: list[dict[str, object]],
    *,
    service: DeliveryService = DeliveryService.IMESSAGE,
):
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=rows,
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[100.0, 100.0],
        ),
    ):
        return _verify_send_in_db(TARGET, 1_000.0, BODY, service)


def test_observation_window_is_ten_seconds_with_half_second_polling() -> None:
    assert OBSERVATION_TIMEOUT_SECONDS == 10.0
    assert OBSERVATION_POLL_SECONDS == 0.5

    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[100.0, 100.0, 100.0, 110.0],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep") as sleeper,
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.MESSAGE_NOT_CORRELATED
    sleeper.assert_called_once_with(0.5)


def test_exact_plain_text_row_can_prove_delivery() -> None:
    result = observe_once([row(is_sent=1, is_delivered=1)])

    assert result.state is AttemptState.DELIVERED
    assert result.correlation is CorrelationConfidence.EXACT


def test_decoded_attributed_body_is_an_exact_match() -> None:
    result = observe_once(
        [row(body=None, attributed_body=attributed_blob(BODY), is_delivered=1)]
    )

    assert result.state is AttemptState.DELIVERED


def test_body_mismatch_cannot_use_newest_recipient_row() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[row(body="different body", send_error=22)],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 10.0],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.MESSAGE_NOT_CORRELATED
    assert result.fallback_permitted is False


def test_multiple_exact_candidates_are_not_confidently_correlated() -> None:
    result = observe_once([row(row_id=41), row(row_id=42)])

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.MESSAGE_NOT_CORRELATED


def test_row_id_is_pinned_for_later_polls() -> None:
    sent = row(is_sent=1)
    delivered = row(is_sent=1, is_delivered=1)
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            side_effect=[[sent], [delivered]],
        ) as query,
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 0.0, 0.5],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.DELIVERED
    assert "m.ROWID = ?" in query.call_args_list[1].args[0]
    assert query.call_args_list[1].args[1] == (41,)


@pytest.mark.parametrize(
    ("service", "database_service"),
    [
        (DeliveryService.IMESSAGE, "SMS"),
        (DeliveryService.SMS, "iMessage"),
    ],
)
def test_transport_mismatch_cannot_resolve_attempt(
    service: DeliveryService, database_service: str
) -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[row(service=database_service, send_error=22)],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 10.0],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, service)

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.MESSAGE_NOT_CORRELATED


def test_database_failure_is_status_unknown_and_redacted() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[{"error": "private path and SQLite details"}],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0],
        ),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.DATABASE_UNAVAILABLE
    assert "private" not in repr(result)


def test_exact_pending_row_times_out_without_claiming_sent() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[row()],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 10.0],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.UNKNOWN
    assert result.reason is OutcomeReason.SEND_STATE_TIMEOUT
    assert result.correlation is CorrelationConfidence.EXACT


def test_exact_sent_row_has_distinct_delivery_timeout() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[row(is_sent=1)],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 10.0],
        ),
        patch("send_only_mac_messages.upstream_messages.time.sleep"),
    ):
        result = _verify_send_in_db(TARGET, 1_000.0, BODY, DeliveryService.IMESSAGE)

    assert result.state is AttemptState.SENT_UNCONFIRMED
    assert result.reason is OutcomeReason.DELIVERY_TIMEOUT


@pytest.mark.parametrize(
    ("service", "database_service", "fallback"),
    [
        (DeliveryService.IMESSAGE, "iMessage", True),
        (DeliveryService.SMS, "RCS", False),
    ],
)
def test_only_exact_imessage_failure_permits_fallback(
    service: DeliveryService, database_service: str, fallback: bool
) -> None:
    result = observe_once(
        [row(service=database_service, send_error=22)], service=service
    )

    assert result.state is AttemptState.FAILED
    assert result.fallback_permitted is fallback


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
