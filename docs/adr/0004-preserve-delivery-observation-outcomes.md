# ADR-0004: Preserve transient delivery observation outcomes

**Status:** Accepted; timing, outcomes, and fallback superseded by ADR-0005

## Context

ADR-0003 retained the upstream verifier's stop condition: it returned as soon as a
correlated row reported `is_sent`. Messages may set `is_sent` before
`is_delivered`, so a delivery flag appearing later in the same six-second window was
reported as sent-unconfirmed instead of delivered.

The verifier also collapsed a `chat.db` query error and a healthy query with no
matching row into the same accepted-unverified result. Operators therefore could not
tell whether the responsible process lacked database access or correlation simply
timed out.

## Decision

Keep the six-second, in-call transient send observation and its existing bounded
query. After a correlated row reports `is_sent`, remember that row and continue
polling every 500 milliseconds. Return immediately only when the row reports delivery
or an asynchronous failure. When the window ends, return sent-unconfirmed only if a
correlated sent row was observed. A candidate row that never reports sent, delivered,
or failed remains unresolved and does not justify a sent-unconfirmed result.

Preserve observer failure provenance using only fixed, redacted reason tokens:

- `delivered:iMessage` or `delivered:SMS` when delivery was observed;
- `sent-unconfirmed:iMessage:delivery-timeout` or
  `sent-unconfirmed:SMS:delivery-timeout` when a sent row never reported delivery;
- `accepted-unverified:iMessage:database-unavailable` or the SMS equivalent when
  the observer could not query `chat.db`;
- `accepted-unverified:iMessage:message-not-correlated` or the SMS equivalent when
  no matching row appeared during the window; and
- `accepted-unverified:iMessage:status-pending` or the SMS equivalent when a matching
  row appeared but never reported sent, delivered, or failed; and
- `error:send_failed:iMessage` or `error:send_failed:SMS` when the correlated row
  reported an asynchronous failure. Retain unsuffixed `error:send_failed` only when
  no delivery service can be resolved.

Database error text, Messages error codes, recipient, body, GUID, row identifier, and
candidate state remain internal and are never returned through MCP or logs. The
immediate AppleScript iMessage-to-SMS fallback is unchanged. No observer outcome,
timeout, interruption, or missing response triggers another send.

This decision supersedes ADR-0003's requirement to stop on `is_sent` and its
unreasoned accepted-unverified and sent-unconfirmed result tokens. All bounded-read,
one-tool, no-retention, principal-isolation, and approval decisions remain in force.

## Consequences

- A successful delivery can take up to the remaining observation window to report.
- A sent message without a delivery flag now takes approximately six seconds to
  return and explains that the window expired.
- Database permission and correlation failures are distinguishable without exposing
  private database details.
- A matching row that never resolves a send state is reported without claiming it was
  sent.
- `delivered` still means a Messages database delivery flag, not human receipt.
