# ADR-0006: Permit SMS fallback only after a synchronous iMessage failure

**Status:** Superseded in part by ADR-0007

## Context

ADR-0005 allowed an exactly correlated `chat.db` `send_error` to authorize a second
SMS/RCS submission. Live evidence showed that this assumption was unsafe: an
iMessage row could report an asynchronous error and the recipient could still
receive that first submission. The automatic SMS/RCS continuation then delivered
the same body a second time through another transport.

The transient observer is evidence about the submitted row, but a nonzero
`send_error` during its bounded window is not an idempotency guarantee and cannot
prove that the first submission will never arrive. Without a durable provider-side
idempotency key, recipient capability result, or cancellation acknowledgement, a
second submission risks duplication.

## Decision

Keep the iMessage-first interface and the one possible SMS/RCS continuation, but
permit that continuation only when the iMessage AppleScript reports a synchronous
`error:` result. That failure happens before the observer is entered and is modeled
with no database correlation confidence.

An exactly correlated database `send_error` never authorizes SMS/RCS. Continue
observing the pinned row through the ten-second window because its flags can change
asynchronously. If delivery appears, return `delivered:iMessage`, even if an error
was observed earlier or remains set. If the error persists without delivery through
the window, return `error:send_failed:iMessage` as the final result for that call.

Enforce this at both boundaries:

- observer-produced failures set no fallback permission; and
- the outer sender accepts fallback permission only from a failure with no database
  correlation confidence.

Callers must not retry a database-observed failure automatically. A fresh tool call
still requires fresh user authorization.

## Supersession

This decision supersedes ADR-0005 only where ADR-0005 permits and describes an
SMS/RCS continuation after an exactly correlated database failure. It reaffirms
ADR-0004's rule that no observer outcome triggers another send. ADR-0005's exact
correlation, row pinning, ten-second window, result vocabulary, and structured
outcome model remain in force.

## Consequences

- One database-observed iMessage failure produces one transport submission, not an
  automatic second submission.
- A provisional error that later reports delivery is returned as delivered.
- An Android, RCS, or deregistered-iMessage destination may return
  `error:send_failed:iMessage` instead of automatically reaching SMS/RCS when the
  AppleScript initially accepts the iMessage attempt. Avoiding duplicate delivery
  takes precedence over automatic reachability in this ambiguous case.
- Immediate iMessage AppleScript rejection can still fall back to SMS/RCS exactly
  once, with its own start time and observation window.
- No live receipt, durable attempt ledger, transport selector, or additional MCP
  tool is added.
