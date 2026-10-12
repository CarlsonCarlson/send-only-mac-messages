"""Tests for the sanitized one-shot hosted canary harness."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.hosted_canary import classify_result, mutation_evidence


@dataclass
class Content:
    type: str
    text: str


@dataclass
class Result:
    content: list[Content]
    isError: bool = False


def test_classifies_only_allow_listed_send_outcome_tokens() -> None:
    assert classify_result(Result([Content("text", "delivered:iMessage")])) == (
        "delivered",
        "iMessage",
    )
    assert classify_result(
        Result([Content("text", "sent-unconfirmed:iMessage:delivery-timeout")])
    ) == ("sent-unconfirmed", "iMessage")
    assert classify_result(
        Result(
            [
                Content(
                    "text",
                    "error:send_status_unknown:SMS:message-not-correlated",
                )
            ]
        )
    ) == ("send-status-unknown", "SMS")
    assert classify_result(
        Result(
            [
                Content(
                    "text",
                    "error:send_status_unknown:iMessage:database-unavailable",
                )
            ]
        )
    ) == ("send-status-unknown", "iMessage")
    assert classify_result(
        Result([Content("text", "error:send_status_unknown:SMS:send-state-timeout")])
    ) == ("send-status-unknown", "SMS")
    assert classify_result(Result([Content("text", "error:send_failed:SMS")])) == (
        "send-failed",
        "SMS",
    )
    assert classify_result(
        Result([Content("text", "sent:iMessage:group-delivery-not-reported")])
    ) == ("sent", "iMessage")
    assert classify_result(
        Result([Content("text", "rejected:group_requires_imessage_only")])
    ) == ("rejected", None)
    assert classify_result(Result([Content("text", "error:busy")])) == ("busy", None)


def test_rejects_raw_or_ambiguous_tool_results() -> None:
    assert classify_result(Result([Content("text", "sent to private target")])) == (
        "error",
        None,
    )
    assert classify_result(Result([], isError=True)) == ("error", None)
    assert classify_result(
        Result([Content("text", "error:send_status_unknown:iMessage:private-db-error")])
    ) == ("error", None)
    assert classify_result(Result([Content("text", "sent-unconfirmed:iMessage")])) == (
        "error",
        None,
    )
    assert classify_result(
        Result([Content("text", "accepted-unverified:iMessage")])
    ) == ("error", None)
    assert classify_result(
        Result([Content("text", "rejected:private recipient detail")])
    ) == ("error", None)


def test_send_failure_does_not_claim_messages_state_was_mutated() -> None:
    assert mutation_evidence("delivered") is True
    assert mutation_evidence("sent-unconfirmed") is True
    assert mutation_evidence("send-status-unknown") is True
    assert mutation_evidence("sent") is True
    assert mutation_evidence("rejected") is False
    assert mutation_evidence("busy") is False
    assert mutation_evidence("timeout") == "unknown"
    assert mutation_evidence("send-failed") == "unknown"
    assert mutation_evidence("error") == "unknown"
