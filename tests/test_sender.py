"""Behavioral tests for the send-only Messages adapter."""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from send_only_mac_messages.sender import (
    MAX_MESSAGE_CHARS,
    build_send_script,
    escape_applescript,
    normalize_phone_number,
    run_applescript,
    send_message,
)


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
    assert send_message(recipient, "hello") == "rejected:invalid_recipient"


def test_rejects_empty_and_oversized_messages_without_invoking_messages() -> None:
    runner = Mock()

    assert (
        send_message("+14155551234", "   ", applescript_runner=runner)
        == "rejected:empty_message"
    )
    assert (
        send_message(
            "+14155551234",
            "x" * (MAX_MESSAGE_CHARS + 1),
            applescript_runner=runner,
        )
        == "rejected:message_too_long"
    )
    runner.assert_not_called()


def test_send_script_tries_imessage_then_sms_and_returns_honest_acceptance() -> None:
    script = build_send_script("+14155551234", "hello")

    assert "service type = iMessage" in script
    assert "service type = SMS" in script
    assert script.index("service type = iMessage") < script.index("service type = SMS")
    assert 'return "accepted-unverified:iMessage"' in script
    assert 'return "accepted-unverified:SMS"' in script
    assert 'return "error:send_failed"' in script
    assert "delivered" not in script.lower()


def test_exact_message_is_escaped_before_submission() -> None:
    runner = Mock(return_value="accepted-unverified:iMessage")
    message = 'first "line"\\path\nsecond\tline'

    result = send_message("+14155551234", message, applescript_runner=runner)

    assert result == "accepted-unverified:iMessage"
    script = runner.call_args.args[0]
    assert escape_applescript(message) in script


def test_osascript_receives_payload_only_over_stdin() -> None:
    completed = subprocess.CompletedProcess(
        args=["osascript", "-"],
        returncode=0,
        stdout="accepted-unverified:iMessage\n",
        stderr="",
    )
    script = build_send_script("+14155551234", "private body")

    with patch("subprocess.run", return_value=completed) as mocked_run:
        assert run_applescript(script) == "accepted-unverified:iMessage"

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
        assert run_applescript("private script") == "error:automation_failed"


def test_timeout_is_reported_without_retrying() -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["osascript", "-"], timeout=30),
    ) as mocked_run:
        assert run_applescript("private script") == "error:timeout"

    mocked_run.assert_called_once()


def test_unrecognized_runner_output_is_not_forwarded() -> None:
    assert (
        send_message(
            "+14155551234",
            "hello",
            applescript_runner=lambda _script: "recipient and body leak",
        )
        == "error:unexpected_result"
    )
