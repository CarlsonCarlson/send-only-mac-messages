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
        result_state = "delivered" if state == "delivered" else "sent-unconfirmed"
        return f"{result_state}:{_service_token(service)}"

    if outcome.startswith(
        f"Message to {_UPSTREAM_DISPLAY_NAME} was handed to Messages.app via "
    ):
        service = "SMS" if " via SMS," in outcome else "iMessage"
        return f"accepted-unverified:{service}"

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
