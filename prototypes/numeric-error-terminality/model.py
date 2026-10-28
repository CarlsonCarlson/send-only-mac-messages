"""Pure state model for the numeric-error terminality prototype."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Verdict(str, Enum):
    WAITING_FOR_ROW = "waiting-for-row"
    PENDING = "pending"
    ERROR_OBSERVED = "error-observed-not-terminal"
    ERROR_CLEARED = "error-cleared-after-observation"
    SENT_PENDING_DELIVERY = "sent-pending-delivery"
    DELIVERED = "delivered"
    PERSISTENT_ERROR_CANDIDATE = "persistent-error-candidate-not-terminal"
    SENT_UNCONFIRMED = "sent-unconfirmed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Sample:
    elapsed_seconds: float
    row_id: int | None
    service: str | None
    error: int | None
    is_sent: bool
    is_delivered: bool


@dataclass(frozen=True)
class State:
    elapsed_seconds: float = 0.0
    pinned_row_id: int | None = None
    service: str | None = None
    error: int | None = None
    is_sent: bool = False
    is_delivered: bool = False
    saw_error: bool = False
    error_codes: tuple[int, ...] = ()
    verdict: Verdict = Verdict.WAITING_FOR_ROW
    sms_authorized: bool = False
    sample_count: int = 0
    ignored_sample_count: int = 0
    last_event: str = "prototype initialized"


def observe(state: State, sample: Sample) -> State:
    """Reduce one database sample into visible prototype state."""
    if (
        state.pinned_row_id is not None
        and sample.row_id is not None
        and sample.row_id != state.pinned_row_id
    ):
        return replace(
            state,
            elapsed_seconds=sample.elapsed_seconds,
            ignored_sample_count=state.ignored_sample_count + 1,
            last_event=f"ignored row {sample.row_id}; row {state.pinned_row_id} is pinned",
        )

    pinned_row_id = state.pinned_row_id or sample.row_id
    if sample.row_id is None:
        return replace(
            state,
            elapsed_seconds=sample.elapsed_seconds,
            sample_count=state.sample_count + 1,
            verdict=Verdict.WAITING_FOR_ROW,
            last_event="no exact outgoing iMessage row matched",
        )

    error = int(sample.error or 0)
    saw_error = state.saw_error or error != 0
    error_codes = state.error_codes
    if error != 0 and error not in error_codes:
        error_codes += (error,)

    if sample.is_delivered:
        verdict = Verdict.DELIVERED
        event = "positive delivery observed"
    elif error != 0:
        verdict = Verdict.ERROR_OBSERVED
        event = f"numeric error {error} observed; still not terminal"
    elif sample.is_sent:
        verdict = Verdict.SENT_PENDING_DELIVERY
        event = "row is sent but delivery is not yet observed"
    elif saw_error:
        verdict = Verdict.ERROR_CLEARED
        event = "previous numeric error cleared without terminal proof"
    else:
        verdict = Verdict.PENDING
        event = "exact row is present with no terminal state"

    return State(
        elapsed_seconds=sample.elapsed_seconds,
        pinned_row_id=pinned_row_id,
        service=sample.service,
        error=error,
        is_sent=sample.is_sent,
        is_delivered=sample.is_delivered,
        saw_error=saw_error,
        error_codes=error_codes,
        verdict=verdict,
        sms_authorized=False,
        sample_count=state.sample_count + 1,
        ignored_sample_count=state.ignored_sample_count,
        last_event=event,
    )


def finish_window(state: State) -> State:
    """Classify the end of a bounded observation without authorizing SMS."""
    if state.is_delivered:
        verdict = Verdict.DELIVERED
        event = "window ended after positive delivery"
    elif state.error:
        verdict = Verdict.PERSISTENT_ERROR_CANDIDATE
        event = "window ended with a persistent numeric error; evidence only"
    elif state.is_sent:
        verdict = Verdict.SENT_UNCONFIRMED
        event = "window ended after send without delivery"
    else:
        verdict = Verdict.UNRESOLVED
        event = "window ended without a terminal result"
    return replace(
        state,
        verdict=verdict,
        sms_authorized=False,
        last_event=event,
    )
