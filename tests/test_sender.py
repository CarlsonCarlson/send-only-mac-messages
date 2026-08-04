"""Behavioral tests for the send-only transport state machine."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from send_only_mac_messages.sender import (
    MAX_MESSAGE_CHARS,
    escape_applescript,
    normalize_phone_number,
    run_applescript,
    send_message,
)
from send_only_mac_messages.upstream_messages import (
    APPLE_EPOCH_OFFSET,
    AttemptOutcome,
    AttemptState,
    CorrelationConfidence,
    DeliveryService,
    OutcomeReason,
)

TARGET = "+14155551234"
BODY = "hello"


def outcome(
    state: AttemptState,
    service: DeliveryService,
    *,
    correlation: CorrelationConfidence = CorrelationConfidence.EXACT,
    reason: OutcomeReason | None = None,
    fallback_permitted: bool = False,
) -> AttemptOutcome:
    return AttemptOutcome(
        state=state,
        service=service,
        correlation=correlation,
        reason=reason,
        fallback_permitted=fallback_permitted,
    )


def database_row(
    *,
    service: str,
    send_error: int = 0,
    is_sent: int = 1,
    is_delivered: int = 0,
) -> dict[str, object]:
    return {
        "row_id": 41,
        "guid": "fixture-guid",
        "send_error": send_error,
        "is_sent": is_sent,
        "is_delivered": is_delivered,
        "service": service,
        "text": BODY,
        "attributedBody": None,
        "handle": TARGET,
    }


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("4155551234", TARGET),
        ("(415) 555-1234", TARGET),
        ("14155551234", TARGET),
        ("+44 20 7946 0958", "+442079460958"),
    ],
)
def test_normalizes_raw_phone_numbers(raw: str, normalized: str) -> None:
    assert normalize_phone_number(raw) == normalized


@pytest.mark.parametrize(
    "recipient",
    ["Carlson Cheng", "carlson@example.com", "contact:1", "12345", "+1234567890123456"],
)
def test_rejects_every_recipient_form_except_phone_numbers(recipient: str) -> None:
    sender = Mock()
    assert send_message(recipient, BODY, upstream_sender=sender) == (
        "rejected:invalid_recipient"
    )
    sender.assert_not_called()


def test_rejects_empty_and_oversized_messages_without_invoking_messages() -> None:
    sender = Mock()

    assert send_message(TARGET, "   ", upstream_sender=sender) == (
        "rejected:empty_message"
    )
    assert (
        send_message(
            TARGET,
            "x" * (MAX_MESSAGE_CHARS + 1),
            upstream_sender=sender,
        )
        == "rejected:message_too_long"
    )
    sender.assert_not_called()


def test_exact_imessage_failure_triggers_one_fresh_sms_attempt() -> None:
    imessage_failure = database_row(service="iMessage", send_error=22, is_sent=0)
    sms_delivery = database_row(service="RCS", is_delivered=1)

    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            side_effect=["success:iMessage", "success"],
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            side_effect=[[imessage_failure], [sms_delivery]],
        ) as query,
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=[100.0, 200.0],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0, 20.0, 20.0],
        ),
    ):
        result = send_message(TARGET, BODY)

    assert result == "delivered:SMS"
    assert runner.call_count == 2
    first_script, second_script = (call.args[0] for call in runner.call_args_list)
    assert "service type = iMessage" in first_script
    assert "service type = SMS" not in first_script
    assert "service type = SMS" in second_script
    assert "service type = iMessage" not in second_script
    assert query.call_args_list[0].args[1][-1] == int(
        (100.0 - APPLE_EPOCH_OFFSET - 1) * 1_000_000_000
    )
    assert query.call_args_list[1].args[1][-1] == int(
        (200.0 - APPLE_EPOCH_OFFSET - 1) * 1_000_000_000
    )


def test_synchronous_imessage_error_keeps_immediate_sms_fallback() -> None:
    sms_delivery = database_row(service="SMS", is_delivered=1)
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            side_effect=["error:send_failed:iMessage", "success"],
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[sms_delivery],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=[100.0, 200.0],
        ),
        patch(
            "send_only_mac_messages.upstream_messages.time.monotonic",
            side_effect=[0.0, 0.0],
        ),
    ):
        result = send_message(TARGET, BODY)

    assert result == "delivered:SMS"
    assert runner.call_count == 2


@pytest.mark.parametrize(
    ("reason", "correlation"),
    [
        (OutcomeReason.DATABASE_UNAVAILABLE, CorrelationConfidence.NONE),
        (OutcomeReason.MESSAGE_NOT_CORRELATED, CorrelationConfidence.NONE),
        (OutcomeReason.SEND_STATE_TIMEOUT, CorrelationConfidence.EXACT),
    ],
)
@pytest.mark.parametrize("service", [DeliveryService.IMESSAGE, DeliveryService.SMS])
def test_unknown_outcome_for_either_service_never_triggers_fallback(
    reason: OutcomeReason,
    correlation: CorrelationConfidence,
    service: DeliveryService,
) -> None:
    first = Mock(
        return_value=outcome(
            AttemptState.UNKNOWN,
            service,
            correlation=correlation,
            reason=reason,
        )
    )
    sms = Mock()

    result = send_message(TARGET, BODY, upstream_sender=first, sms_sender=sms)

    assert result == f"error:send_status_unknown:{service.value}:{reason.value}"
    sms.assert_not_called()


@pytest.mark.parametrize("service", [DeliveryService.IMESSAGE, DeliveryService.SMS])
def test_sent_without_delivery_never_triggers_fallback(
    service: DeliveryService,
) -> None:
    first = Mock(
        return_value=outcome(
            AttemptState.SENT_UNCONFIRMED,
            service,
            reason=OutcomeReason.DELIVERY_TIMEOUT,
        )
    )
    sms = Mock()

    assert send_message(TARGET, BODY, upstream_sender=first, sms_sender=sms) == (
        f"sent-unconfirmed:{service.value}:delivery-timeout"
    )
    sms.assert_not_called()


def test_sms_failure_stops_without_a_loop_or_retry() -> None:
    imessage_failure = outcome(
        AttemptState.FAILED,
        DeliveryService.IMESSAGE,
        fallback_permitted=True,
    )
    sms_failure = outcome(
        AttemptState.FAILED,
        DeliveryService.SMS,
        correlation=CorrelationConfidence.EXACT,
    )
    first = Mock(return_value=imessage_failure)
    sms = Mock(return_value=sms_failure)

    assert send_message(TARGET, BODY, upstream_sender=first, sms_sender=sms) == (
        "error:send_failed:SMS"
    )
    first.assert_called_once()
    sms.assert_called_once()


@pytest.mark.parametrize(
    ("internal", "public"),
    [
        ("Error: AppleScript timed out after 30 seconds", "error:timeout"),
        ("Error: AppleScript automation failed", "error:automation_failed"),
        (None, "error:unexpected_result"),
    ],
)
def test_ambiguous_or_missing_dispatch_result_never_triggers_fallback(
    internal: object, public: str
) -> None:
    first = Mock(return_value=internal)
    sms = Mock()

    assert send_message(TARGET, BODY, upstream_sender=first, sms_sender=sms) == public
    sms.assert_not_called()


def test_tool_interruption_propagates_without_fallback() -> None:
    first = Mock(side_effect=InterruptedError("fixture interruption"))
    sms = Mock()

    with pytest.raises(InterruptedError):
        send_message(TARGET, BODY, upstream_sender=first, sms_sender=sms)
    sms.assert_not_called()


def test_invalid_structured_fallback_state_is_rejected() -> None:
    with pytest.raises(ValueError):
        outcome(
            AttemptState.UNKNOWN,
            DeliveryService.IMESSAGE,
            fallback_permitted=True,
        )


def test_exact_message_is_escaped_before_submission() -> None:
    assert escape_applescript('first "line"\\path\nsecond\tline') == (
        'first \\"line\\"\\\\path\\nsecond\\tline'
    )


def test_osascript_receives_payload_only_over_stdin() -> None:
    completed = subprocess.CompletedProcess(
        args=["osascript", "-"],
        returncode=0,
        stdout="success:iMessage\n",
        stderr="",
    )
    script = f'send "private body" to participant "{TARGET}"'

    with patch("subprocess.run", return_value=completed) as mocked_run:
        assert run_applescript(script) == "success:iMessage"

    assert mocked_run.call_args.args[0] == ["osascript", "-"]
    assert TARGET not in mocked_run.call_args.args[0]
    assert "private body" not in mocked_run.call_args.args[0]
    assert mocked_run.call_args.kwargs["input"] == script
    assert "env" not in mocked_run.call_args.kwargs


def test_platform_errors_are_redacted() -> None:
    completed = subprocess.CompletedProcess(
        args=["osascript", "-"],
        returncode=1,
        stdout="",
        stderr="private recipient and body appeared here",
    )

    with patch("subprocess.run", return_value=completed):
        assert run_applescript("private script") == (
            "Error: AppleScript automation failed"
        )


def test_apple_script_process_timeout_remains_thirty_seconds() -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["osascript", "-"], timeout=30),
    ) as mocked_run:
        assert run_applescript("private script") == (
            "Error: AppleScript timed out after 30 seconds"
        )

    mocked_run.assert_called_once()
