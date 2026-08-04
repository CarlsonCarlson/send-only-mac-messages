# ADR-0005: Fall back once after an exact iMessage failure

**Status:** Accepted

## Context

ADR-0004 preserved a six-second observer and returned accepted-unverified results for
ambiguous states. It also prohibited SMS fallback after a correlated asynchronous
iMessage failure. That contract could leave a definitively failed iMessage without
the already-supported SMS/RCS path, while its newest-recipient-row heuristic could
mistake another send for the current attempt.

## Decision

Keep one MCP tool and no durable attempt ledger. Give each transport attempt its own
ten-second observation window with 500-millisecond polling. Budget at least 40 seconds
for callers; the normal two-transport path is approximately 23 seconds. Keep the
separate 30-second AppleScript process timeout.

Exact correlation requires the normalized recipient, the individual attempt start
time, the exact `text` or decoded `attributedBody`, and the expected transport. Pin
the resolved row identifier for later polls. A newest-recipient row, body mismatch,
transport mismatch, or multiple exact candidates is not authoritative.

Model each attempt as a structured internal outcome containing state, service,
correlation confidence, fixed reason, and whether fallback is permitted. Convert it
to a public token only at the outer sender boundary.

Return:

- `delivered:<service>` for an exact row marked delivered;
- `sent-unconfirmed:<service>:delivery-timeout` for an exact row marked sent without
  delivery by the deadline;
- `error:send_status_unknown:<service>:database-unavailable` when the database cannot
  be read;
- `error:send_status_unknown:<service>:message-not-correlated` when no unique exact
  row can be pinned;
- `error:send_status_unknown:<service>:send-state-timeout` when a pinned row never
  reports sent, delivered, or failed; and
- `error:send_failed:<service>` for a definitive transport failure.

A synchronous iMessage AppleScript failure keeps the immediate fallback behavior.
An exactly correlated definitive iMessage failure also permits exactly one SMS/RCS
attempt. That attempt gets a fresh start time and requires an SMS/RCS row. Stop after
its result. Never fall back or retry after an unknown state, sent-unconfirmed result,
AppleScript or tool timeout, interruption, missing response, or heuristic-only row.

This decision supersedes ADR-0004 only for its six-second window,
accepted-unverified/status-pending result terms, correlation heuristic, and
prohibition on fallback after a definitive correlated iMessage failure. The one-tool,
principal-isolated, transient-observation, redaction, and no-retention decisions
remain in force.

## Consequences

- A normal observer-triggered fallback can occupy the serialized sender for about 23
  seconds.
- Full Disk Access remains required for exact observation, but database access does
  not imply general history authority.
- Ambiguous completion cannot be made exactly-once without durable state, so callers
  must obtain fresh authorization before another tool call.
- `delivered` is a Messages database flag, not proof of human receipt.
