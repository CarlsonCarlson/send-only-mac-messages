# Delivery Observation and SMS/RCS Fallback Plan

**Status:** Implemented locally by ADR-0005; deployment and live sends are not
authorized by this document.

## Goal

Make the send-only Messages adapter behave predictably when Messages.app accepts an
iMessage submission and the transient observer later proves that exact attempt
failed. The adapter should try SMS/RCS exactly once in that case, preserve honest
unknown outcomes in every ambiguous case, and give each transport a ten-second
observation window.

The public interface remains:

```text
tool_send_message(recipient, message)
```

No transport selector, history lookup, contact discovery, retained attempt record,
or second MCP tool is added.

## Observation window

- Increase the transient observation window from six seconds to ten seconds.
- Continue polling every 500 milliseconds.
- Give each transport attempt its own ten-second window:
  - iMessage: up to ten seconds.
  - SMS/RCS fallback: a new ten-second window beginning with that attempt.
- Budget at least 40 seconds for an end-to-end MCP call. With the existing
  AppleScript delays, the longest normal observer-triggered fallback path is about
  23 seconds.
- Keep the separate 30-second AppleScript process timeout unchanged. An AppleScript
  timeout is ambiguous and must not authorize fallback or retry.

## Public result contract

`<service>` is `iMessage` or `SMS`. The public `SMS` label includes both SMS and RCS.

| Result | Evidence |
| --- | --- |
| `delivered:<service>` | The exact outgoing row was marked delivered. |
| `sent-unconfirmed:<service>:delivery-timeout` | The exact row was marked sent, but delivery was not observed within ten seconds. |
| `error:send_status_unknown:<service>:database-unavailable` | The observer could not read `chat.db`. |
| `error:send_status_unknown:<service>:message-not-correlated` | The exact outgoing message could not be located confidently. |
| `error:send_status_unknown:<service>:send-state-timeout` | The exact row was found, but it was not marked sent, delivered, or failed within ten seconds. |
| `error:send_failed:<service>` | The exact row reached a definitive send failure. |

Remove these terms from the current contract:

- `accepted-unverified`
- `status-pending`

`error:send_status_unknown` is a normal domain result returned through MCP, not a
transport or protocol exception. Its `error:` prefix tells callers not to treat the
operation as successful. The word `unknown` prevents callers from misclassifying it
as a definitive send failure.

The two timeout reasons remain distinct:

- `send-state-timeout`: an exact row was found, but whether it was sent remains
  unknown.
- `delivery-timeout`: an exact row was confirmed sent, but delivery was not observed.

Neither timeout authorizes an automatic retry.

## Correlation requirements

An authoritative observation uses:

- the exact recipient or one of its normalized handle variants;
- the individual attempt's start time;
- the exact message body, including a decoded `attributedBody` when plain text is
  absent;
- the expected transport; and
- the resolved row identifier, pinned internally for later polls of that attempt.

The newest-recipient-row heuristic must not:

- declare the current message delivered;
- declare the current message failed;
- claim the current message was sent; or
- authorize SMS/RCS fallback.

If exact correlation is unavailable, return
`error:send_status_unknown:<service>:message-not-correlated`. Discard every row,
identifier, recipient, body, and attempt detail when the tool call returns.

## Fallback state machine

1. Validate the raw phone-number recipient and message using the existing rules.
2. Attempt iMessage.
3. Observe the exact iMessage attempt for up to ten seconds.
4. Resolve the iMessage outcome:
   - Delivered: return `delivered:iMessage`.
   - Confirmed sent without delivery: return
     `sent-unconfirmed:iMessage:delivery-timeout`.
   - Unknown: return `error:send_status_unknown:iMessage:<reason>`.
   - Definitive failure: produce `error:send_failed:iMessage` internally and attempt
     SMS/RCS exactly once.
5. Give the SMS/RCS attempt a new start time and a separate ten-second observation
   window. Its observer must require an SMS/RCS row so the failed iMessage row cannot
   be mistaken for the fallback attempt.
6. Return the final SMS outcome:
   - `delivered:SMS`
   - `sent-unconfirmed:SMS:delivery-timeout`
   - `error:send_status_unknown:SMS:<reason>`
   - `error:send_failed:SMS`
7. Stop after the SMS/RCS outcome. Never loop back to iMessage and never make a
   second SMS/RCS attempt.

For an accepted raw phone-number recipient,
`error:send_failed:iMessage` is the mandatory fallback trigger rather than the final
caller-visible result. The caller normally receives the subsequent SMS outcome.

The existing immediate AppleScript iMessage-to-SMS/RCS fallback remains part of the
same authorized call. Across both the immediate and observer-triggered paths, at
most one SMS/RCS submission may occur.

## Outcomes that never authorize fallback or retry

Do not attempt SMS/RCS after:

- `sent-unconfirmed:iMessage:delivery-timeout`;
- any `error:send_status_unknown:iMessage:<reason>`;
- an AppleScript timeout;
- a tool interruption;
- a missing MCP response;
- a transport timeout; or
- a heuristic-only database match.

Never retry after:

- `error:send_failed:SMS`;
- an ambiguous SMS/RCS outcome;
- a missing or interrupted result; or
- any result from a call whose completion is unknown.

A fresh user authorization is required before a caller makes another tool call.

## Internal design

Keep fallback policy behind the existing one-tool interface. Model each attempt with
a structured internal outcome containing:

- state;
- actual transport;
- correlation confidence;
- fixed reason, when applicable; and
- whether fallback is permitted.

Make fallback decisions from this structured outcome, not by parsing a public result
string. Convert the final structured outcome to a fixed redacted token only at the
outer sender seam.

The remote sender remains serialized. The implementation retains no durable attempt
ledger, so a timeout, process crash, or lost response cannot be made exactly-once and
must remain non-retriable.

## Documentation work

1. Add a new ADR that supersedes ADR-0004 only where it:
   - fixes the observation window at six seconds;
   - uses `accepted-unverified` and `status-pending`; and
   - prohibits fallback after an exactly correlated definitive iMessage failure.
2. Update `CONTEXT.md`, `README.md`, remote setup documentation, MCP tool descriptions,
   remote caller instructions, and hosted-canary result classification.
3. Preserve the one-tool, principal-isolated, transient-observation, redaction, and
   no-retention decisions from the existing ADRs.

## Required tests

Add or update deterministic tests for:

- a ten-second observation window with 500-millisecond polling;
- exact iMessage failure followed by exactly one SMS/RCS attempt;
- a new timestamp and independent observation window for SMS/RCS;
- service isolation so the SMS observer cannot resolve the failed iMessage row;
- exact correlation as a prerequisite for definitive outcomes and fallback;
- a heuristic-only match returning `message-not-correlated` without fallback;
- each `error:send_status_unknown` reason for both public services;
- the distinction between `send-state-timeout` and `delivery-timeout`;
- SMS/RCS delivery, sent-unconfirmed, unknown, and definitive failure;
- SMS/RCS failure stopping without a loop or retry;
- AppleScript timeout, tool interruption, and missing response never triggering
  fallback;
- remote serialization across the longer call;
- hosted-canary classification of the new tokens; and
- continued redaction of recipient, body, database errors, Messages error codes,
  row identifiers, and candidate state.

Run the repository's full test, formatting, import-order, typing, and build checks.
Tests must continue to replace AppleScript execution and must not send live messages.

## Deployment and live verification gates

Implementation does not authorize deployment or a send. After separate approval:

1. Commit and push the reviewed implementation and contract changes.
2. Update only the intended principal-bound hosted sender using the tracked deployment
   workflow.
3. Verify the installed revision, expected GUI user, sender attestation, Automation
   permission, Full Disk Access, paired-iPhone configuration, and remote MCP surface.
4. Run a content-free initialization and tool-discovery smoke test without invoking
   Messages.app.
5. Obtain a fresh instruction naming the logical sender, exact recipient, and exact
   canary message.
6. Invoke the send tool exactly once against an Android/RCS-capable target.
7. Compare the returned final SMS result with Messages state and recipient receipt.
8. Do not retry an ambiguous canary result.

## Non-goals

- General Messages history reads or search.
- Contact lookup or recipient discovery.
- Transport selection by callers.
- A later status-query tool.
- Durable attempt retention or an idempotency ledger.
- Automatic retry after any ambiguous result.
- More than one SMS/RCS attempt per authorized call.
