# ADR-0005: Fall back once after an exactly correlated iMessage failure

**Status:** Superseded in part by ADR-0006

## Context

The send-only adapter already tried SMS/RCS when the iMessage AppleScript block
failed immediately. Messages.app can also accept that AppleScript command and mark
the exact outgoing iMessage row failed a few seconds later. ADR-0004 returned that
as `error:send_failed:iMessage` and prohibited an internal continuation, so a phone
number known not to support iMessage could fail without using the paired iPhone's
available SMS/RCS service.

ADR-0004 also preserved the upstream newest-recipient-row heuristic. A row chosen
only by recipient and recency is not strong enough evidence to authorize a second
submission: it could belong to another concurrent send. The result vocabulary
likewise treated database, correlation, and unresolved-state outcomes as
`accepted-unverified`, even though callers must treat all three as unknown rather
than successful.

## Decision

Keep the one-tool interface and make the transport policy an internal state machine.
Each attempt produces a structured outcome containing its state, actual transport,
correlation confidence, fixed reason when applicable, and whether fallback is
permitted. The outer sender converts only the final structured outcome to a fixed,
redacted token; fallback policy never parses public result strings.

Try iMessage first. Attempt SMS/RCS exactly once only after either:

- the iMessage-only AppleScript reports an immediate failure; or
- the transient observer resolves the exact outgoing iMessage body and reports a
  definitive send failure.

Give iMessage and SMS/RCS separate start timestamps and separate ten-second
observation windows. Poll every 500 milliseconds. Filter candidates by outgoing
direction, recipient or normalized handle variant, a timestamp at or after the exact
attempt start time, exact body, and expected transport. Do not include the prior
one-second pre-attempt tolerance. Treat `iMessageLite` as iMessage and `RCS` as SMS
for the public contract. Once an exact candidate resolves, pin its row identifier for
later polls of that attempt.

The newest-recipient-row heuristic is never authoritative. If an exact body cannot
be correlated, return an unknown result and do not fall back. An AppleScript timeout,
automation failure, tool interruption, missing response, transport timeout, or any
other ambiguous result also does not authorize fallback or a retry.

Return only these delivery-observation outcomes, where `<service>` is `iMessage` or
`SMS`:

- `delivered:<service>`
- `sent-unconfirmed:<service>:delivery-timeout`
- `error:send_status_unknown:<service>:database-unavailable`
- `error:send_status_unknown:<service>:message-not-correlated`
- `error:send_status_unknown:<service>:send-state-timeout`
- `error:send_failed:<service>`

`send-state-timeout` means the exact row never resolved whether it was sent.
`delivery-timeout` means the exact row was confirmed sent but delivery was not
observed. Neither authorizes a retry. Remove `accepted-unverified` and
`status-pending` from the current public contract.

Keep the AppleScript subprocess timeout at 30 seconds. Remote execution remains
serialized. Callers should budget at least 40 seconds for one MCP invocation, but a
timeout or missing response remains ambiguous and must not be retried automatically.
No attempt row, identifier, recipient, body, or status is retained after the call.

## Supersession

This decision supersedes ADR-0004 only where ADR-0004:

- fixes the observation window at six seconds;
- uses `accepted-unverified` and `status-pending` public tokens;
- permits the newest-recipient-row heuristic to resolve an outcome; and
- prohibits the one internal SMS/RCS continuation after an exactly correlated,
  definitive iMessage failure.

ADR-0004's distinction between sent-but-undelivered and unresolved send state, its
redaction requirements, and its continued observation after `is_sent` remain in
force. The one-tool, principal-isolated, transient-observation, no-retention, and
caller no-retry decisions from ADR-0001 through ADR-0004 also remain in force.
ADR-0003's one-second pre-attempt timestamp tolerance is superseded by the exact
attempt-start boundary above.

## Consequences

- An Android, RCS, or deregistered-iMessage destination can reach the paired
  iPhone's SMS/RCS path after the exact iMessage attempt definitively fails.
- At most one SMS/RCS submission can occur across the immediate and observed-failure
  paths.
- The longest normal observed-failure path is approximately 23 seconds, while
  clients reserve at least 40 seconds for protocol and process overhead.
- Missing Full Disk Access prevents observer-triggered fallback because database
  unavailability is unknown, not a definitive failure.
- A failed or ambiguous SMS/RCS attempt is final for that tool call. A fresh user
  authorization is required before any later call.
- Delivery still means the correlated Messages row reported delivery; it does not
  prove human receipt.
