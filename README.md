# Send-only Mac Messages

A deliberately narrow MCP server for sending direct messages through macOS
Messages.app. It exposes one tool and transiently observes only the status of the
message that tool just submitted.

## Boundary

`tool_send_message(recipient, message)` accepts an exact phone number and text body.
Ten-digit US numbers are normalized with `+1`; international numbers may be passed in
E.164 form. Contact names, email addresses, contact selections, group identifiers,
and recipient discovery are rejected.

The repository contains no general message-history query, Contacts integration, chat
listing, attachments, or later status lookup. After a send is accepted, a fixed
read-only `chat.db` query considers at most ten recent outgoing candidates for the
same recipient and prefers the exact outbound body. It retains no database row or
send identifier after the call. Heimdall is not part of the send path.

Apple Blocked Contacts remains the platform-level delivery block; this adapter
neither reads nor maintains a separate blocklist.

## Delivery behavior

Each call tries iMessage first. It tries the enabled SMS service if the AppleScript
attempt fails immediately. This is the upstream SMS/RCS fallback from commit
`f77be9e`; a later database-reported failure does not trigger another send attempt.
It does not fall back after `sent-unconfirmed`, `accepted-unverified`, a timeout, or
an interruption because the iMessage outcome could still be successful and a retry
could duplicate the message.

SMS/RCS from a Mac depends on the paired iPhone and Messages configuration described by
[Apple's Text Message Forwarding documentation](https://support.apple.com/en-us/102545).

Results are intentionally narrow:

- `delivered:iMessage`
- `delivered:SMS`
- `sent-unconfirmed:iMessage`
- `sent-unconfirmed:SMS`
- `accepted-unverified:iMessage`
- `accepted-unverified:SMS`
- `rejected:invalid_recipient`
- `rejected:empty_message`
- `rejected:message_too_long`
- `error:send_failed`
- `error:timeout`
- `error:automation_failed`
- `error:unexpected_result`

The upstream transient observer polls every 500 milliseconds for at most six seconds.
It searches recent outgoing rows using recipient and send time, prefers an exact body
match, and retains upstream's newest-recipient-row fallback when no body matches.
`delivered` means that the resolved Messages row reported delivery; it does not mean
a human read the message.
`sent-unconfirmed` means the row was marked sent before its delivery flag was present;
the verbatim upstream verifier stops polling at that point. `accepted-unverified`
means Messages accepted the command but the observer could not resolve a row or access
the database. A simultaneous send to the same recipient remains ambiguous, especially
when the body cannot be decoded; the upstream fallback may resolve the newest row.

Recipient and message content are passed to `osascript` over standard input, not in
process arguments or environment variables. Tool results and logs do not echo either
value.

## Requirements

- macOS with Messages.app signed in under the intended sending profile
- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)
- Automation permission for the GUI application or Terminal process that launches the
  server to control Messages
- Full Disk Access for the responsible process so it can read the correlated status
  from `~/Library/Messages/chat.db`
- For SMS/RCS fallback, the applicable paired-iPhone Messages configuration

No Contacts permission is needed. Full Disk Access is broader than the adapter's
fixed query; macOS does not provide row-level permission for the Messages database.

## Run from source

```bash
git clone https://github.com/CarlsonCarlson/send-only-mac-messages.git
cd send-only-mac-messages
uv sync --extra dev
uv run send-only-mac-messages
```

Example MCP configuration:

```json
{
  "mcpServers": {
    "send-only-mac-messages": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/send-only-mac-messages",
        "run",
        "send-only-mac-messages"
      ]
    }
  }
}
```

The process must be launched inside the intended user's active macOS graphical
session. An SSH-owned process does not inherit a Terminal process's Messages
Automation permission.

## Authenticated remote mode

The optional `send-only-mac-messages-remote` entry point mirrors Heimdall's private
remote-MCP pattern: stateless Streamable HTTP on loopback, a dedicated exact
hostname and `/mcp` path, one bearer in the client environment, and only its SHA-256
digest on the Mac. It also requires an expected logical sender label and rechecks the
effective and active-console user immediately before each send.

Remote authentication does not authorize a particular message. Keep the tool on
per-call approval, and never retry a tool-call timeout or missing response. The
upstream immediate SMS fallback is part of the same approved call.
See [the principal-bound remote setup guide](docs/remote-mcp-setup.md) and
[ADR-0002](docs/adr/0002-principal-bound-remote-mcp.md).

## Verify

```bash
uv sync --extra dev
uv run pytest -q
uv run black --check .
uv run isort --check-only .
uv run mypy send_only_mac_messages
uv build
```

Tests replace AppleScript execution and never send a real message.

## Hosted canary harness

`scripts/hosted_canary.py --smoke-only` initializes the packaged server and proves
that discovery returns one send tool, zero resources, and zero prompts without
invoking Messages.app.

The live harness is intentionally one-shot. Its launcher refuses the wrong macOS
user, the wrong console user, and any process that is not descended from the visible
Terminal app. The approved phone handle arrives through a mode-600 FIFO; sanitized
status contains only phase, canary ID, service, and outcome class. A failed or
interrupted post-invocation result is never retried automatically.

## Origin

This repository was forked from
[`carterlasalle/mac_messages_mcp`](https://github.com/carterlasalle/mac_messages_mcp)
to retain its tested macOS Messages send behavior, then reduced to an independent
send-only surface.
