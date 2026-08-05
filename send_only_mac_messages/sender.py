"""Send-only adapter around the cherry-picked upstream Messages implementation."""

from __future__ import annotations

import re
from collections.abc import Callable

from send_only_mac_messages.upstream_messages import (
    AttemptState,
    CorrelationConfidence,
    ObservationReason,
    SendAttemptOutcome,
    _send_message_direct,
    _send_message_sms,
    escape_applescript,
    run_applescript,
)

MAX_MESSAGE_CHARS = 4_000

_PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+\Z")


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


def _public_result(outcome: object) -> str:
    """Convert one structured final outcome to a fixed, redacted MCP token."""
    if not isinstance(outcome, SendAttemptOutcome):
        return "error:unexpected_result"

    service = outcome.actual_transport.public_service
    if outcome.state is AttemptState.DELIVERED:
        return f"delivered:{service}"
    if (
        outcome.state is AttemptState.SENT_UNCONFIRMED
        and outcome.reason is ObservationReason.DELIVERY_TIMEOUT
    ):
        return f"sent-unconfirmed:{service}:delivery-timeout"
    if outcome.state is AttemptState.UNKNOWN and outcome.reason in {
        ObservationReason.DATABASE_UNAVAILABLE,
        ObservationReason.MESSAGE_NOT_CORRELATED,
        ObservationReason.SEND_STATE_TIMEOUT,
    }:
        return f"error:send_status_unknown:{service}:{outcome.reason.value}"
    if outcome.state is AttemptState.FAILED:
        return f"error:send_failed:{service}"
    if outcome.state is AttemptState.TIMEOUT:
        return "error:timeout"
    if outcome.state is AttemptState.AUTOMATION_FAILED:
        return "error:automation_failed"
    return "error:unexpected_result"


def send_message(
    recipient: str,
    message: str,
    *,
    upstream_sender: Callable[[str, str], object] = _send_message_direct,
    sms_sender: Callable[[str, str], object] = _send_message_sms,
) -> str:
    """Validate input and execute one iMessage-first, at-most-one-SMS send call."""
    try:
        normalized_recipient = normalize_phone_number(recipient)
    except ValueError:
        return "rejected:invalid_recipient"

    if not isinstance(message, str) or not message.strip():
        return "rejected:empty_message"
    if len(message) > MAX_MESSAGE_CHARS:
        return "rejected:message_too_long"

    outcome = upstream_sender(normalized_recipient, message)
    if (
        isinstance(outcome, SendAttemptOutcome)
        and outcome.state is AttemptState.FAILED
        and outcome.actual_transport.public_service == "iMessage"
        and outcome.correlation_confidence is CorrelationConfidence.NONE
        and outcome.fallback_permitted
    ):
        outcome = sms_sender(normalized_recipient, message)
    return _public_result(outcome)
