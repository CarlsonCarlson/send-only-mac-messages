# ADR-0003: Observe one send transiently for delivery status

**Status:** Accepted; polling/results superseded by ADR-0004 and correlation by ADR-0005

## Context

ADR-0001 removed every Messages database reader and limited results to
`accepted-unverified`. That boundary prevented the adapter from distinguishing an
AppleScript command that was accepted from a message that failed asynchronously a
second or two later.

Upstream commit `1a8f309` added a bounded `chat.db` check that resolves a recent
outgoing row using the target handle and send time, preferring an exact body match.
The required product behavior is similarly short-lived: delivery status is useful
immediately after the send and does not need to be retained or queried later.

## Decision

Keep exactly one MCP tool and add a **transient send observation** inside that tool.
There is no status lookup tool, arbitrary identifier lookup, history API, Heimdall
call, or retained send-attempt record.

Use the upstream implementations of `_verify_send_in_db`,
`_report_send_outcome`, `_send_message_sms`, and `_send_message_direct` verbatim,
along with their required helper functions. The code is taken from upstream tree
`a6e4605`, which contains the SMS/RCS work from `f77be9e` and the delivery verifier
from `1a8f309`.

Immediately before AppleScript, the upstream sender records the send time. After
Messages.app accepts the command, the verifier polls
`~/Library/Messages/chat.db` every 500 milliseconds for at most six seconds. Its
query:

- considers only outgoing rows;
- requires the intended phone handle or a normalized variant;
- requires a database timestamp no earlier than one second before the attempt;
- examines at most ten newest candidates;
- prefers an exact body match using `text` or decoded `attributedBody`; and
- falls back to the newest candidate for that recipient when no body matches,
  preserving upstream behavior.

Open SQLite with `mode=ro` and `PRAGMA query_only = ON`. The transplanted upstream
module contains its generic query helper because the verifier calls it, but neither
that helper nor any other read path is exposed through MCP. The fixed-token adapter
must not expose recipient, body, database errors, Messages error codes, GUIDs,
surrounding rows, or other local data through MCP results or logs.

Return only these additional fixed outcomes:

- `delivered:iMessage` or `delivered:SMS`: the correlated row reported delivery
  during the observation window;
- `sent-unconfirmed:iMessage` or `sent-unconfirmed:SMS`: the correlated row reported
  sent, but not delivered, when the window ended; or
- `error:send_failed`: the correlated row reported an asynchronous failure.

Retain `accepted-unverified:iMessage` and `accepted-unverified:SMS` when Messages
accepted the command but the database was unavailable or no row resolved. A later
database-reported failure is returned as `error:send_failed`; it does not trigger an
SMS attempt. The only fallback is the immediate iMessage-to-SMS/RCS AppleScript path
from upstream commit `f77be9e`.

Retain upstream's stop condition verbatim: return when a nonzero Messages error or
`is_sent` appears. Delivery is reported only when `is_delivered` is already present on
that resolved row. Discard all candidate state when the tool call returns.

This decision supersedes ADR-0001's prohibition on all `chat.db` access and
ADR-0002's requirement that every accepted send remain unverified. All other
send-only, principal-isolation, one-tool, and approval decisions remain in force.

## Consequences

- The responsible macOS process now requires Full Disk Access in addition to
  Messages Automation permission. macOS grants file-level access more broadly than
  this fixed query, so the OS permission is not a row-level security boundary.
- Heimdall remains the only general message-reading and history-search authority.
- A manual message to a different recipient cannot match the handle filter. A
  simultaneous message to the same recipient is normally separated by exact body.
- A same-recipient, same-body send remains ambiguous. If no body matches, the
  verbatim upstream verifier may resolve the newest row for that recipient.
- A tool call may take approximately six seconds when no resolved row appears.
- `delivered` is a Messages database receipt, not proof that a human read the message.
