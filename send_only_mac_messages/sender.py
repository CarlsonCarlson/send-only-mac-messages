"""Send-only adapter around the cherry-picked upstream Messages implementation."""

from __future__ import annotations

import re
from collections.abc import Callable

from send_only_mac_messages.upstream_messages import (
    _send_message_direct,
    escape_applescript,
    run_applescript,
)

MAX_MESSAGE_CHARS = 4_000

_PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+\Z")
_UPSTREAM_DISPLAY_NAME = "recipient"
_UPSTREAM_OUTCOME = re.compile(
    r"^Message (delivered|sent) successfully via (iMessage|iMessageLite|SMS|RCS) "
)
_UPSTREAM_ASYNC_FAILURE = re.compile(
    r"^Error: message to recipient failed to send .*service "
    r"(iMessage|iMessageLite|SMS|RCS)\)"
)


def normalize_phone_number(recipient: str) -> str:
    """Normalize a raw phone-number input to an E.164-style Messages handle."""
    raw = str(recipient).strip()
    if not raw or not _PHONE_INPUT.fullmatch(raw):
        raise ValueError("recipient must be a phone number")

    digits = "".join(character for character in raw if character in "0123456789")
    if not 10 <= len(digits) <= 15:
        raise ValueError("recipient must contain 10 to 15 digits")
    if raw.startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}"


def _service_token(service: str) -> str:
    return "SMS" if service in {"SMS", "RCS"} else "iMessage"


def _redact_upstream_outcome(outcome: object) -> str:
    """Translate upstream's human-readable result into this MCP's fixed tokens."""
    if not isinstance(outcome, str):
        return "error:unexpected_result"

    match = _UPSTREAM_OUTCOME.match(outcome)
    if match is not None:
        state, service = match.groups()
        if state == "delivered":
            return f"delivered:{_service_token(service)}"
        return f"sent-unconfirmed:{_service_token(service)}:delivery-timeout"

    if outcome.startswith(
        f"Message to {_UPSTREAM_DISPLAY_NAME} was handed to Messages.app via "
    ):
        service = "SMS" if " via SMS," in outcome else "iMessage"
        if "Messages database was unavailable" in outcome:
            return f"accepted-unverified:{service}:database-unavailable"
        if "no matching message row appeared" in outcome:
            return f"accepted-unverified:{service}:message-not-correlated"
        if "matching message row remained pending" in outcome:
            return f"accepted-unverified:{service}:status-pending"
        return "error:unexpected_result"

    failure = _UPSTREAM_ASYNC_FAILURE.match(outcome)
    if failure is not None:
        return f"error:send_failed:{_service_token(failure.group(1))}"
    if outcome.startswith("Error"):
        return "error:send_failed"
    if outcome.startswith("Unknown"):
        return "error:unexpected_result"
    return "error:unexpected_result"


def send_message(
    recipient: str,
    message: str,
    *,
    upstream_sender: Callable[[str, str, str, bool], str] = _send_message_direct,
) -> str:
    """Validate the send-only input, then invoke the cherry-picked upstream sender."""
    try:
        normalized_recipient = normalize_phone_number(recipient)
    except ValueError:
        return "rejected:invalid_recipient"

    if not isinstance(message, str) or not message.strip():
        return "rejected:empty_message"
    if len(message) > MAX_MESSAGE_CHARS:
        return "rejected:message_too_long"

    outcome = upstream_sender(
        normalized_recipient,
        message,
        _UPSTREAM_DISPLAY_NAME,
        False,
    )
    return _redact_upstream_outcome(outcome)
