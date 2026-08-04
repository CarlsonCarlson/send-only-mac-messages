"""Behavioral tests for the send-only adapter around upstream Messages code."""

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
from send_only_mac_messages.upstream_messages import _send_message_sms


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
    ["Carlson Cheng", "carlson@example.com", "contact:1", "12345", "+1234567890123456"],
)
def test_rejects_every_recipient_form_except_phone_numbers(recipient: str) -> None:
    sender = Mock()
    assert (
        send_message(recipient, "hello", upstream_sender=sender)
        == "rejected:invalid_recipient"
    )
    sender.assert_not_called()


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


def test_cherry_picked_send_script_contains_imessage_then_sms_fallback() -> None:
    database_row = {
        "guid": "guid-1",
        "send_error": 0,
        "is_sent": 1,
        "is_delivered": 0,
        "service": "iMessage",
        "text": "hello",
        "attributedBody": None,
    }
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success:iMessage",
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[database_row],
        ),
    ):
        result = send_message("+14155551234", "hello")

    assert result == "sent-unconfirmed:iMessage"
    script = runner.call_args.args[0]
    assert "service type = iMessage" in script
    assert "service type = SMS" in script
    assert script.index("service type = iMessage") < script.index("service type = SMS")
    assert 'return "success:iMessage"' in script
    assert 'return "success:SMS"' in script


def test_cherry_picked_direct_sms_helper_uses_sms_service() -> None:
    database_row = {
        "guid": "guid-1",
        "send_error": 0,
        "is_sent": 1,
        "is_delivered": 0,
        "service": "SMS",
        "text": "hello",
        "attributedBody": None,
    }
    with (
        patch(
            "send_only_mac_messages.upstream_messages.run_applescript",
            return_value="success",
        ) as runner,
        patch(
            "send_only_mac_messages.upstream_messages.query_messages_db",
            return_value=[database_row],
        ),
    ):
        result = _send_message_sms("+14155551234", "hello", "recipient")

    assert result == "Message sent successfully via SMS to recipient"
    script = runner.call_args.args[0]
    assert "service type = SMS" in script
    assert "service type = iMessage" not in script


def test_upstream_human_results_are_mapped_to_fixed_redacted_tokens() -> None:
    cases = {
        "Message delivered successfully via iMessage to recipient": "delivered:iMessage",
        "Message sent successfully via SMS to recipient": "sent-unconfirmed:SMS",
        (
            "Message to recipient was handed to Messages.app via iMessage, "
            "but delivery could not be verified in the Messages database."
        ): "accepted-unverified:iMessage",
        (
            "Error: message to recipient failed to send "
            "(Messages error code 22, service iMessage). "
            "The recipient may not be reachable via iMessage."
        ): "error:send_failed",
    }

    for upstream_result, expected in cases.items():
        sender = Mock(return_value=upstream_result)
        assert (
            send_message("+14155551234", "private body", upstream_sender=sender)
            == expected
        )
        sender.assert_called_once_with(
            "+14155551234", "private body", "recipient", False
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
