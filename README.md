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
listing, attachments, or later status lookup. After each submission, a fixed
read-only `chat.db` query requires the intended recipient, attempt start time, exact
body, and expected transport. It pins that exact row for later polls and never uses a
newest-recipient heuristic. It retains no database row or send identifier after the
call. Heimdall is not part of the send path.

Apple Blocked Contacts remains the platform-level delivery block; this adapter
neither reads nor maintains a separate blocklist.

## Delivery behavior

Each call tries iMessage first and observes that exact attempt for up to ten seconds.
A synchronous AppleScript failure or an exactly correlated definitive iMessage
failure permits exactly one SMS/RCS attempt. The fallback receives a fresh start time
and an independent ten-second observation window. A sent-unconfirmed, unknown,
timeout, interruption, missing response, or heuristic-only row never authorizes
fallback or retry. The state machine stops after the one SMS/RCS outcome.

SMS/RCS from a Mac depends on the paired iPhone and Messages configuration described by
[Apple's Text Message Forwarding documentation](https://support.apple.com/en-us/102545).

Results are intentionally narrow:

- `delivered:iMessage`
- `delivered:SMS`
- `sent-unconfirmed:iMessage:delivery-timeout`
- `sent-unconfirmed:SMS:delivery-timeout`
- `error:send_status_unknown:iMessage:database-unavailable`
- `error:send_status_unknown:SMS:database-unavailable`
- `error:send_status_unknown:iMessage:message-not-correlated`
- `error:send_status_unknown:SMS:message-not-correlated`
- `error:send_status_unknown:iMessage:send-state-timeout`
- `error:send_status_unknown:SMS:send-state-timeout`
- `rejected:invalid_recipient`
- `rejected:empty_message`
- `rejected:message_too_long`
- `error:send_failed:iMessage`
- `error:send_failed:SMS`
- `error:timeout`
- `error:automation_failed`
- `error:unexpected_result`

The transient observer polls every 500 milliseconds for at most ten seconds per
transport. `delivered` means the exact Messages row reported delivery; it does not
mean a human read the message. `sent-unconfirmed` means the exact row was marked sent
but its delivery flag was absent when that transport's window ended.
`error:send_status_unknown` distinguishes an unavailable database, an attempt that
could not be exactly correlated, and an exact row whose send state remained pending.
`error:send_failed:<service>` means an exact row reported a definitive failure, or
the service-specific AppleScript submission failed synchronously. Unknown and
timeout results are deliberately non-retryable because the original send may still
have succeeded.

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
per-call approval, budget at least 40 seconds for the end-to-end call, and never retry
an unknown result, tool-call timeout, interruption, or missing response. The one
permitted SMS fallback is part of the same approved call.
See [the principal-bound remote setup guide](docs/remote-mcp-setup.md) and
[ADR-0005](docs/adr/0005-exact-failure-sms-fallback.md).

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
