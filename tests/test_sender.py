"""Behavioral tests for the send-only adapter around upstream Messages code."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from send_only_mac_messages.sender import (
    IMESSAGE_ONLY,
    IMESSAGE_WITH_SMS_FALLBACK,
    MAX_MESSAGE_CHARS,
    escape_applescript,
    normalize_phone_number,
    run_applescript,
    send_message,
)
from send_only_mac_messages.upstream_messages import (
    AttemptState,
    CorrelationConfidence,
    MessageTransport,
    ObservationReason,
    SendAttemptOutcome,
    _send_message_group_chat,
    _send_message_sms,
)

GROUP_CHAT_ID = "any;+;chat123456789012345678"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("4155551234", "+14155551234"),
        ("(415) 555-1234", "+14155551234"),
        ("14155551234", "+14155551234"),
        ("+44 20 7946 0958", "+442079460958"),
    ],
)
def test_normalizes_raw_phone_numbers(raw: str, normalized: str) -> None:
    assert normalize_phone_number(raw) == normalized


@pytest.mark.parametrize(
    "recipient",
    [
        "Carlson Cheng",
        "carlson@example.com",
        "contact:1",
        "12345",
        "+1234567890123456",
        "chat123456789012345678",
        "any;-;+14155551234",
        "any;+;chat",
        "group:Buyers",
    ],
)
def test_rejects_every_recipient_form_except_phone_numbers_and_chat_ids(
    recipient: str,
) -> None:
    sender = Mock()
    group_sender = Mock()
    assert (
        send_message(
            recipient, "hello", upstream_sender=sender, group_sender=group_sender
        )
        == "rejected:invalid_recipient"
    )
    sender.assert_not_called()
    group_sender.assert_not_called()


@pytest.mark.parametrize("chat_id", [GROUP_CHAT_ID, "iMessage;+;chat12345"])
def test_chat_id_recipient_routes_to_the_group_sender(chat_id: str) -> None:
    sender = Mock()
    group_sender = Mock(
        return_value=SendAttemptOutcome(
            state=AttemptState.SENT_UNCONFIRMED,
            actual_transport=MessageTransport.IMESSAGE,
            correlation_confidence=CorrelationConfidence.EXACT,
            reason=ObservationReason.GROUP_DELIVERY_NOT_REPORTED,
        )
    )

    result = send_message(
        f"  {chat_id} ",
        "hello",
        IMESSAGE_ONLY,
        upstream_sender=sender,
        group_sender=group_sender,
    )

    assert result == "sent:iMessage:group-delivery-not-reported"
    group_sender.assert_called_once_with(chat_id, "hello")
    sender.assert_not_called()


def test_chat_id_recipient_rejects_sms_fallback_mode_before_messages() -> None:
    sender = Mock()
    group_sender = Mock()

    result = send_message(
        GROUP_CHAT_ID,
        "hello",
        IMESSAGE_WITH_SMS_FALLBACK,
        upstream_sender=sender,
        group_sender=group_sender,
    )

    assert result == "rejected:group_requires_imessage_only"
    sender.assert_not_called()
    group_sender.assert_not_called()


def test_group_chat_applescript_targets_the_chat_id_without_a_participant() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            side_effect=["iMessage", "success"],
        ) as script,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=SendAttemptOutcome(
                state=AttemptState.SENT_UNCONFIRMED,
                actual_transport=MessageTransport.IMESSAGE,
                correlation_confidence=CorrelationConfidence.EXACT,
                reason=ObservationReason.GROUP_DELIVERY_NOT_REPORTED,
            ),
        ) as observer,
    ):
        outcome = _send_message_group_chat(GROUP_CHAT_ID, 'hi "all"')

    preflight_script, sent_script = (call.args[0] for call in script.call_args_list)
    assert f'chat id "{GROUP_CHAT_ID}"' in preflight_script
    assert "send " not in preflight_script
    assert f'to chat id "{GROUP_CHAT_ID}"' in sent_script
    assert "participant" not in sent_script
    assert 'hi \\"all\\"' in sent_script
    assert "service type = SMS" not in sent_script
    assert observer.call_args.kwargs["chat_guid"] == GROUP_CHAT_ID
    assert outcome.reason is ObservationReason.GROUP_DELIVERY_NOT_REPORTED


@pytest.mark.parametrize(
    ("preflight", "token"),
    [
        ("rejected:unknown_chat_id", "rejected:unknown_chat_id"),
        ("rejected:chat_not_imessage", "rejected:group_not_imessage"),
    ],
)
def test_group_preflight_rejects_unknown_or_non_imessage_chats_without_sending(
    preflight: str, token: str
) -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value=preflight,
        ) as script,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db"
        ) as observer,
    ):
        result = send_message(GROUP_CHAT_ID, "hello", IMESSAGE_ONLY)

    assert result == token
    assert script.call_count == 1
    assert "send " not in script.call_args.args[0]
    observer.assert_not_called()


def test_group_preflight_timeout_is_reported_without_sending() -> None:
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="Error: AppleScript timed out after 30 seconds",
        ) as script,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db"
        ) as observer,
    ):
        result = send_message(GROUP_CHAT_ID, "hello", IMESSAGE_ONLY)

    assert result == "error:timeout"
    assert script.call_count == 1
    observer.assert_not_called()


def test_rejects_empty_and_oversized_messages_without_invoking_upstream() -> None:
    sender = Mock()

    assert (
        send_message("+14155551234", "   ", upstream_sender=sender)
        == "rejected:empty_message"
    )
    assert (
        send_message(
            "+14155551234",
            "x" * (MAX_MESSAGE_CHARS + 1),
            upstream_sender=sender,
        )
        == "rejected:message_too_long"
    )
    sender.assert_not_called()


def test_rejects_invalid_delivery_mode_without_invoking_upstream() -> None:
    sender = Mock()

    result = send_message(  # type: ignore[arg-type]
        "+14155551234",
        "hello",
        "automatic",
        upstream_sender=sender,
    )

    assert result == "rejected:invalid_delivery_mode"
    sender.assert_not_called()


def test_imessage_only_exact_observed_failure_does_not_submit_sms() -> None:
    imessage_sender = Mock(
        return_value=SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=MessageTransport.IMESSAGE,
            correlation_confidence=CorrelationConfidence.EXACT,
            fallback_permitted=True,
        )
    )
    sms_sender = Mock()

    result = send_message(
        "+14155551234",
        "hello",
        upstream_sender=imessage_sender,
        sms_sender=sms_sender,
    )

    imessage_sender.assert_called_once_with("+14155551234", "hello")
    sms_sender.assert_not_called()
    assert result == "error:send_failed:iMessage"


def test_fallback_mode_exact_observed_failure_submits_sms_once() -> None:
    imessage_sender = Mock(
        return_value=SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=MessageTransport.IMESSAGE,
            correlation_confidence=CorrelationConfidence.EXACT,
        )
    )
    sms_sender = Mock(
        return_value=SendAttemptOutcome(
            state=AttemptState.DELIVERED,
            actual_transport=MessageTransport.RCS,
            correlation_confidence=CorrelationConfidence.EXACT,
        )
    )

    result = send_message(
        "+14155551234",
        "hello",
        IMESSAGE_WITH_SMS_FALLBACK,
        upstream_sender=imessage_sender,
        sms_sender=sms_sender,
    )

    imessage_sender.assert_called_once_with("+14155551234", "hello")
    sms_sender.assert_called_once_with("+14155551234", "hello")
    assert result == "delivered:SMS"


def test_immediate_imessage_error_starts_a_fresh_sms_attempt() -> None:
    sms_delivered = SendAttemptOutcome(
        state=AttemptState.DELIVERED,
        actual_transport=MessageTransport.SMS,
        correlation_confidence=CorrelationConfidence.EXACT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            side_effect=["error:iMessage unavailable", "success"],
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=sms_delivered,
        ) as observer,
        patch(
            "send_only_mac_messages.upstream_messages.time.time",
            side_effect=[100.0, 200.0],
        ),
    ):
        result = send_message(
            "+14155551234",
            "hello",
            IMESSAGE_WITH_SMS_FALLBACK,
        )

    assert result == "delivered:SMS"
    assert runner.call_count == 2
    imessage_script = runner.call_args_list[0].args[0]
    sms_script = runner.call_args_list[1].args[0]
    assert "service type = iMessage" in imessage_script
    assert "service type = SMS" not in imessage_script
    assert "service type = SMS" in sms_script
    observer.assert_called_once_with(
        "+14155551234",
        200.0,
        "hello",
        service=MessageTransport.SMS,
    )


def test_imessage_only_observed_failure_does_not_start_an_sms_window() -> None:
    imessage_failed = SendAttemptOutcome(
        state=AttemptState.FAILED,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.EXACT,
        fallback_permitted=True,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=imessage_failed,
        ) as observer,
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=100.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "error:send_failed:iMessage"
    runner.assert_called_once()
    observer.assert_called_once_with(
        "+14155551234",
        100.0,
        "hello",
        service=MessageTransport.IMESSAGE,
    )


def test_imessage_only_immediate_failure_does_not_submit_sms() -> None:
    imessage_sender = Mock(
        return_value=SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=MessageTransport.IMESSAGE,
            correlation_confidence=CorrelationConfidence.NONE,
            fallback_permitted=True,
        )
    )
    sms_sender = Mock()

    result = send_message(
        "+14155551234",
        "hello",
        IMESSAGE_ONLY,
        upstream_sender=imessage_sender,
        sms_sender=sms_sender,
    )

    assert result == "error:send_failed:iMessage"
    imessage_sender.assert_called_once_with("+14155551234", "hello")
    sms_sender.assert_not_called()


@pytest.mark.parametrize(
    ("service", "reason", "expected"),
    [
        (
            MessageTransport.IMESSAGE,
            ObservationReason.DATABASE_UNAVAILABLE,
            "error:send_status_unknown:iMessage:database-unavailable",
        ),
        (
            MessageTransport.IMESSAGE,
            ObservationReason.MESSAGE_NOT_CORRELATED,
            "error:send_status_unknown:iMessage:message-not-correlated",
        ),
        (
            MessageTransport.IMESSAGE,
            ObservationReason.SEND_STATE_TIMEOUT,
            "error:send_status_unknown:iMessage:send-state-timeout",
        ),
        (
            MessageTransport.SMS,
            ObservationReason.DATABASE_UNAVAILABLE,
            "error:send_status_unknown:SMS:database-unavailable",
        ),
        (
            MessageTransport.SMS,
            ObservationReason.MESSAGE_NOT_CORRELATED,
            "error:send_status_unknown:SMS:message-not-correlated",
        ),
        (
            MessageTransport.SMS,
            ObservationReason.SEND_STATE_TIMEOUT,
            "error:send_status_unknown:SMS:send-state-timeout",
        ),
    ],
)
def test_all_unknown_reasons_are_fixed_for_both_public_services(
    service: MessageTransport,
    reason: ObservationReason,
    expected: str,
) -> None:
    unknown = SendAttemptOutcome(
        state=AttemptState.UNKNOWN,
        actual_transport=service,
        correlation_confidence=CorrelationConfidence.NONE,
        reason=reason,
    )
    if service is MessageTransport.IMESSAGE:
        imessage_outcome = unknown
    else:
        imessage_outcome = SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=MessageTransport.IMESSAGE,
            correlation_confidence=CorrelationConfidence.NONE,
            fallback_permitted=True,
        )
    sms_sender = Mock(return_value=unknown)

    result = send_message(
        "+14155551234",
        "hello",
        IMESSAGE_WITH_SMS_FALLBACK,
        upstream_sender=Mock(return_value=imessage_outcome),
        sms_sender=sms_sender,
    )

    assert result == expected
    if service is MessageTransport.IMESSAGE:
        sms_sender.assert_not_called()
    else:
        sms_sender.assert_called_once()


@pytest.mark.parametrize(
    ("sms_outcome", "expected"),
    [
        (
            SendAttemptOutcome(
                AttemptState.DELIVERED,
                MessageTransport.RCS,
                CorrelationConfidence.EXACT,
            ),
            "delivered:SMS",
        ),
        (
            SendAttemptOutcome(
                AttemptState.SENT_UNCONFIRMED,
                MessageTransport.SMS,
                CorrelationConfidence.EXACT,
                ObservationReason.DELIVERY_TIMEOUT,
            ),
            "sent-unconfirmed:SMS:delivery-timeout",
        ),
        (
            SendAttemptOutcome(
                AttemptState.UNKNOWN,
                MessageTransport.SMS,
                CorrelationConfidence.NONE,
                ObservationReason.MESSAGE_NOT_CORRELATED,
            ),
            "error:send_status_unknown:SMS:message-not-correlated",
        ),
        (
            SendAttemptOutcome(
                AttemptState.FAILED,
                MessageTransport.SMS,
                CorrelationConfidence.EXACT,
            ),
            "error:send_failed:SMS",
        ),
    ],
)
def test_sms_fallback_returns_its_final_outcome_without_a_loop(
    sms_outcome: SendAttemptOutcome,
    expected: str,
) -> None:
    imessage_failed = SendAttemptOutcome(
        state=AttemptState.FAILED,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.NONE,
        fallback_permitted=True,
    )
    sms_sender = Mock(return_value=sms_outcome)

    result = send_message(
        "+14155551234",
        "hello",
        IMESSAGE_WITH_SMS_FALLBACK,
        upstream_sender=Mock(return_value=imessage_failed),
        sms_sender=sms_sender,
    )

    assert result == expected
    sms_sender.assert_called_once_with("+14155551234", "hello")


def test_applescript_timeout_never_triggers_sms_fallback() -> None:
    sms_sender = Mock()
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="Error: AppleScript timed out after 30 seconds",
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message(
            "+14155551234",
            "hello",
            IMESSAGE_WITH_SMS_FALLBACK,
            sms_sender=sms_sender,
        )

    assert result == "error:timeout"
    sms_sender.assert_not_called()


def test_missing_sender_result_never_triggers_sms_fallback() -> None:
    sms_sender = Mock()

    result = send_message(
        "+14155551234",
        "hello",
        IMESSAGE_WITH_SMS_FALLBACK,
        upstream_sender=Mock(return_value=None),
        sms_sender=sms_sender,
    )

    assert result == "error:unexpected_result"
    sms_sender.assert_not_called()


def test_tool_interruption_propagates_without_sms_fallback() -> None:
    sms_sender = Mock()

    with pytest.raises(KeyboardInterrupt):
        send_message(
            "+14155551234",
            "hello",
            IMESSAGE_WITH_SMS_FALLBACK,
            upstream_sender=Mock(side_effect=KeyboardInterrupt),
            sms_sender=sms_sender,
        )

    sms_sender.assert_not_called()


def test_imessage_attempt_does_not_embed_a_second_transport() -> None:
    sent_outcome = SendAttemptOutcome(
        state=AttemptState.SENT_UNCONFIRMED,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.EXACT,
        reason=ObservationReason.DELIVERY_TIMEOUT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=sent_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "sent-unconfirmed:iMessage:delivery-timeout"
    script = runner.call_args.args[0]
    assert "service type = iMessage" in script
    assert "service type = SMS" not in script


def test_send_waits_for_delivery_after_message_is_marked_sent() -> None:
    delivered_outcome = SendAttemptOutcome(
        state=AttemptState.DELIVERED,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.EXACT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=delivered_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "delivered:iMessage"


def test_send_reports_database_unavailable_when_observation_query_fails() -> None:
    unknown_outcome = SendAttemptOutcome(
        state=AttemptState.UNKNOWN,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.NONE,
        reason=ObservationReason.DATABASE_UNAVAILABLE,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=unknown_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "error:send_status_unknown:iMessage:database-unavailable"


def test_send_reports_message_not_correlated_when_no_row_appears() -> None:
    unknown_outcome = SendAttemptOutcome(
        state=AttemptState.UNKNOWN,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.NONE,
        reason=ObservationReason.MESSAGE_NOT_CORRELATED,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=unknown_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "error:send_status_unknown:iMessage:message-not-correlated"


def test_send_reports_delivery_timeout_when_sent_never_becomes_delivered() -> None:
    sent_outcome = SendAttemptOutcome(
        state=AttemptState.SENT_UNCONFIRMED,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.EXACT,
        reason=ObservationReason.DELIVERY_TIMEOUT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=sent_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "sent-unconfirmed:iMessage:delivery-timeout"


def test_send_state_timeout_is_unknown_and_does_not_claim_sent() -> None:
    pending_outcome = SendAttemptOutcome(
        state=AttemptState.UNKNOWN,
        actual_transport=MessageTransport.IMESSAGE,
        correlation_confidence=CorrelationConfidence.EXACT,
        reason=ObservationReason.SEND_STATE_TIMEOUT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ),
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=pending_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "error:send_status_unknown:iMessage:send-state-timeout"


def test_cherry_picked_direct_sms_helper_uses_sms_service() -> None:
    sent_outcome = SendAttemptOutcome(
        state=AttemptState.SENT_UNCONFIRMED,
        actual_transport=MessageTransport.SMS,
        correlation_confidence=CorrelationConfidence.EXACT,
        reason=ObservationReason.DELIVERY_TIMEOUT,
    )
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages._verify_send_in_db",
            return_value=sent_outcome,
        ),
        patch("send_only_mac_messages.upstream_messages.time.time", return_value=0.0),
    ):
        result = _send_message_sms("+14155551234", "hello")

    assert result == sent_outcome
    script = runner.call_args.args[0]
    assert "service type = SMS" in script
    assert "service type = iMessage" not in script


def test_structured_outcomes_are_mapped_to_fixed_redacted_tokens() -> None:
    cases = [
        (
            SendAttemptOutcome(
                AttemptState.DELIVERED,
                MessageTransport.IMESSAGE_LITE,
                CorrelationConfidence.EXACT,
            ),
            "delivered:iMessage",
        ),
        (
            SendAttemptOutcome(
                AttemptState.SENT_UNCONFIRMED,
                MessageTransport.RCS,
                CorrelationConfidence.EXACT,
                ObservationReason.DELIVERY_TIMEOUT,
            ),
            "sent-unconfirmed:SMS:delivery-timeout",
        ),
        (
            SendAttemptOutcome(
                AttemptState.UNKNOWN,
                MessageTransport.IMESSAGE,
                CorrelationConfidence.NONE,
                ObservationReason.DATABASE_UNAVAILABLE,
            ),
            "error:send_status_unknown:iMessage:database-unavailable",
        ),
        (
            SendAttemptOutcome(
                AttemptState.FAILED,
                MessageTransport.SMS,
                CorrelationConfidence.EXACT,
            ),
            "error:send_failed:SMS",
        ),
        (
            SendAttemptOutcome(
                AttemptState.SENT_UNCONFIRMED,
                MessageTransport.IMESSAGE,
                CorrelationConfidence.EXACT,
                ObservationReason.GROUP_DELIVERY_NOT_REPORTED,
            ),
            "sent:iMessage:group-delivery-not-reported",
        ),
    ]

    for structured_outcome, expected in cases:
        sender = Mock(return_value=structured_outcome)
        assert (
            send_message("+14155551234", "private body", upstream_sender=sender)
            == expected
        )
        sender.assert_called_once_with("+14155551234", "private body")


def test_legacy_unreasoned_observation_result_is_rejected() -> None:
    sender = Mock(
        return_value=(
            "Message to recipient was handed to Messages.app via iMessage, "
            "but delivery could not be verified in the Messages database."
        )
    )

    assert (
        send_message("+14155551234", "private body", upstream_sender=sender)
        == "error:unexpected_result"
    )


def test_exact_message_is_escaped_by_cherry_picked_helper() -> None:
    message = 'first "line"\\path\nsecond\tline'
    escaped = escape_applescript(message)

    assert escaped == 'first \\"line\\"\\\\path\\nsecond\\tline'


def test_osascript_receives_payload_only_over_stdin() -> None:
    completed = subprocess.CompletedProcess(
        args=["osascript", "-"],
        returncode=0,
        stdout="success:iMessage\n",
        stderr="",
    )
    script = 'send "private body" to participant "+14155551234"'

    with patch("subprocess.run", return_value=completed) as mocked_run:
        assert run_applescript(script) == "success:iMessage"

    assert mocked_run.call_args.args[0] == ["osascript", "-"]
    assert "+14155551234" not in mocked_run.call_args.args[0]
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
        assert (
            run_applescript("private script") == "Error: AppleScript automation failed"
        )


def test_timeout_is_reported_without_retrying() -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["osascript", "-"], timeout=30),
    ) as mocked_run:
        assert run_applescript("private script") == (
            "Error: AppleScript timed out after 30 seconds"
        )

    mocked_run.assert_called_once()
