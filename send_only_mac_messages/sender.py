"""Send-only adapter around the cherry-picked upstream Messages implementation."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal, TypeAlias

from send_only_mac_messages.upstream_messages import (
    AttemptState,
    CorrelationConfidence,
    ObservationReason,
    SendAttemptOutcome,
    _send_message_direct,
    _send_message_group_chat,
    _send_message_sms,
    escape_applescript,
    run_applescript,
)

MAX_MESSAGE_CHARS = 4_000

DeliveryMode: TypeAlias = Literal[
    "imessage_only",
    "imessage_with_sms_fallback",
    "sms_only",
]
IMESSAGE_ONLY: DeliveryMode = "imessage_only"
IMESSAGE_WITH_SMS_FALLBACK: DeliveryMode = "imessage_with_sms_fallback"
SMS_ONLY: DeliveryMode = "sms_only"
DELIVERY_MODES = frozenset({IMESSAGE_ONLY, IMESSAGE_WITH_SMS_FALLBACK, SMS_ONLY})

_PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+\Z")
# Exact Messages chat id of an existing group chat, as chat.guid stores it.
# Messages uses both chat<digits> and 32-hex-character group guids.
_CHAT_ID = re.compile(r"(any|iMessage|SMS|RCS);\+;[A-Za-z0-9]+\Z")

RESULT_TOKENS = (
    "delivered:iMessage",
    "delivered:SMS",
    "sent-unconfirmed:iMessage:delivery-timeout",
    "sent-unconfirmed:SMS:delivery-timeout",
    "sent:iMessage:group-delivery-not-reported",
    "error:send_failed:iMessage",
    "error:send_failed:SMS",
    "error:send_status_unknown:iMessage:database-unavailable",
    "error:send_status_unknown:SMS:database-unavailable",
    "error:send_status_unknown:iMessage:message-not-correlated",
    "error:send_status_unknown:SMS:message-not-correlated",
    "error:send_status_unknown:iMessage:send-state-timeout",
    "error:send_status_unknown:SMS:send-state-timeout",
    "error:timeout",
    "error:automation_failed",
    "error:unexpected_result",
    "rejected:invalid_recipient",
    "rejected:empty_message",
    "rejected:message_too_long",
    "rejected:group_requires_imessage_only",
    "rejected:unknown_chat_id",
    "rejected:group_not_imessage",
    "rejected:invalid_delivery_mode",
)


def chat_id_or_none(recipient: str) -> str | None:
    """Return the exact chat id when the recipient addresses a group chat."""
    raw = str(recipient).strip()
    return raw if _CHAT_ID.fullmatch(raw) else None


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
    if (
        outcome.state is AttemptState.SENT_UNCONFIRMED
        and outcome.reason is ObservationReason.GROUP_DELIVERY_NOT_REPORTED
    ):
        return f"sent:{service}:group-delivery-not-reported"
    if outcome.state is AttemptState.UNKNOWN and outcome.reason in {
        ObservationReason.DATABASE_UNAVAILABLE,
        ObservationReason.MESSAGE_NOT_CORRELATED,
        ObservationReason.SEND_STATE_TIMEOUT,
    }:
        return f"error:send_status_unknown:{service}:{outcome.reason.value}"
    if outcome.state is AttemptState.FAILED:
        if outcome.reason is ObservationReason.UNKNOWN_CHAT_ID:
            return "rejected:unknown_chat_id"
        if outcome.reason is ObservationReason.CHAT_NOT_IMESSAGE:
            return "rejected:group_not_imessage"
        return f"error:send_failed:{service}"
    if outcome.state is AttemptState.TIMEOUT:
        return "error:timeout"
    if outcome.state is AttemptState.AUTOMATION_FAILED:
        return "error:automation_failed"
    return "error:unexpected_result"


def send_message(
    recipient: str,
    message: str,
    delivery_mode: DeliveryMode = IMESSAGE_ONLY,
    *,
    upstream_sender: Callable[[str, str], object] = _send_message_direct,
    sms_sender: Callable[[str, str], object] = _send_message_sms,
    group_sender: Callable[[str, str], object] = _send_message_group_chat,
) -> str:
    """Validate input and execute the requested one-call delivery policy."""
    if delivery_mode not in DELIVERY_MODES:
        return "rejected:invalid_delivery_mode"

    chat_id = chat_id_or_none(recipient)
    if chat_id is None:
        try:
            normalized_recipient = normalize_phone_number(recipient)
        except ValueError:
            return "rejected:invalid_recipient"
    elif delivery_mode != IMESSAGE_ONLY:
        return "rejected:group_requires_imessage_only"

    if not isinstance(message, str) or not message.strip():
        return "rejected:empty_message"
    if len(message) > MAX_MESSAGE_CHARS:
        return "rejected:message_too_long"

    if chat_id is not None:
        return _public_result(group_sender(chat_id, message))
    if delivery_mode == SMS_ONLY:
        return _public_result(sms_sender(normalized_recipient, message))

    outcome = upstream_sender(normalized_recipient, message)
    if (
        delivery_mode == IMESSAGE_WITH_SMS_FALLBACK
        and isinstance(outcome, SendAttemptOutcome)
        and outcome.state is AttemptState.FAILED
        and outcome.actual_transport.public_service == "iMessage"
        and (
            outcome.correlation_confidence is CorrelationConfidence.EXACT
            or (
                outcome.correlation_confidence is CorrelationConfidence.NONE
                and outcome.fallback_permitted
            )
        )
    ):
        outcome = sms_sender(normalized_recipient, message)
    return _public_result(outcome)
