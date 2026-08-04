"""Send-only adapter around the cherry-picked upstream Messages implementation."""

from __future__ import annotations

import re
from collections.abc import Callable

from send_only_mac_messages.upstream_messages import (
    AttemptOutcome,
    AttemptState,
    CorrelationConfidence,
    OutcomeReason,
    _send_message_direct,
    _send_message_sms,
    escape_applescript,
    run_applescript,
)

MAX_MESSAGE_CHARS = 4_000

_PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+\Z")
_UPSTREAM_DISPLAY_NAME = "recipient"


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


def _render_outcome(outcome: object) -> str:
    """Convert one structured attempt result to a fixed, redacted public token."""
    if isinstance(outcome, AttemptOutcome):
        service = outcome.service.value
        if (
            outcome.state is AttemptState.DELIVERED
            and outcome.correlation is CorrelationConfidence.EXACT
            and outcome.reason is None
        ):
            return f"delivered:{service}"
        if (
            outcome.state is AttemptState.SENT_UNCONFIRMED
            and outcome.correlation is CorrelationConfidence.EXACT
            and outcome.reason is OutcomeReason.DELIVERY_TIMEOUT
        ):
            return f"sent-unconfirmed:{service}:delivery-timeout"
        if outcome.state is AttemptState.UNKNOWN and outcome.reason in {
            OutcomeReason.DATABASE_UNAVAILABLE,
            OutcomeReason.MESSAGE_NOT_CORRELATED,
            OutcomeReason.SEND_STATE_TIMEOUT,
        }:
            return f"error:send_status_unknown:{service}:{outcome.reason.value}"
        if outcome.state is AttemptState.FAILED:
            return f"error:send_failed:{service}"
        return "error:unexpected_result"

    if isinstance(outcome, str):
        if outcome.startswith("Error: AppleScript timed out"):
            return "error:timeout"
        if outcome == "Error: AppleScript automation failed":
            return "error:automation_failed"
    return "error:unexpected_result"


def send_message(
    recipient: str,
    message: str,
    *,
    upstream_sender: Callable[[str, str, str, bool], object] = _send_message_direct,
    sms_sender: Callable[[str, str, str], object] = _send_message_sms,
) -> str:
    """Validate one send and allow one SMS fallback only for definitive failure."""
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
    if isinstance(outcome, AttemptOutcome) and outcome.fallback_permitted:
        outcome = sms_sender(normalized_recipient, message, _UPSTREAM_DISPLAY_NAME)
    return _render_outcome(outcome)
