# ADR-0007: Require an explicit per-call delivery mode

**Status:** Accepted

## Context

ADR-0006 made duplicate avoidance an implicit global policy: SMS/RCS was allowed only
after a synchronous iMessage AppleScript rejection. That prevented duplicate
submissions after an asynchronous database failure, but it also meant an Android or
deregistered-iMessage destination could not exercise SMS/RCS when Messages.app first
accepted the iMessage command and reported failure later.

Callers need to choose between two materially different intentions. Some sends must
be transport-isolated to iMessage. Other sends explicitly authorize the reachability
and duplicate-risk tradeoff of one SMS/RCS continuation.

## Decision

Keep one destructive MCP tool and add one required `delivery_mode` argument with two
values:

- `imessage_only`: submit one iMessage attempt and never invoke SMS/RCS, regardless
  of the iMessage outcome.
- `imessage_with_sms_fallback`: submit iMessage first, then submit SMS/RCS at most
  once after either a synchronous AppleScript failure or an exactly correlated
  database-observed iMessage failure.

Missing or invalid MCP modes fail validation before Messages.app. Internal callers
that omit the mode default fail-closed to `imessage_only`.

Unknown, timed-out, interrupted, missing-response, sent-unconfirmed, and
non-correlated outcomes never authorize SMS/RCS. A fallback attempt remains final for
the call, and clients must never automatically retry any result.

The tool description must state that fallback after an observed failure can
duplicate a delayed iMessage. Selecting the fallback mode is explicit permission for
that one continuation, not proof that the first transport was cancelled.

## Supersession

This decision supersedes ADR-0006 only where ADR-0006 makes synchronous failure the
sole SMS/RCS eligibility rule and says no transport selector is exposed. ADR-0006's
evidence that database failure cannot guarantee non-delivery remains authoritative
and is now surfaced as an explicit fallback-mode risk.

ADR-0005's exact-correlation requirement and at-most-one fallback limit remain in
force. All unknown-outcome and caller no-retry rules remain unchanged.

## Consequences

- `imessage_only` provides a mechanically enforceable no-SMS contract.
- `imessage_with_sms_fallback` can reach Android, RCS, or deregistered-iMessage
  destinations after an exactly observed failure.
- Fallback mode can produce two recipient-visible deliveries if an asynchronously
  failed iMessage later arrives. The API makes that risk explicit rather than global.
- Existing MCP calls without `delivery_mode` are rejected without sending.
