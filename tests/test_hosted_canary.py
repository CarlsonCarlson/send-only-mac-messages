"""Tests for the sanitized one-shot hosted canary harness."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.hosted_canary import classify_result


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
