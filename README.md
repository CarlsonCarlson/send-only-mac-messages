# Send-only Mac Messages

A deliberately narrow MCP server for sending direct messages through macOS
Messages.app. It exposes one tool and transiently observes only the status of the
message that tool just submitted.

## Boundary

`tool_send_message(recipient, message, delivery_mode)` accepts an exact phone number
or the exact Messages chat id of an existing group chat, a text body, and a required
delivery policy. `delivery_mode` is exactly one of:

- `imessage_only`: submit iMessage only and never invoke SMS/RCS.
- `imessage_with_sms_fallback`: submit iMessage first, then submit SMS/RCS once if
  AppleScript rejects iMessage immediately or the exact correlated iMessage row
  remains failed through observation.

Ten-digit US numbers are normalized with `+1`; international numbers may be passed in
E.164 form. A group chat is addressed by its exact chat id, `<service>;+;chat<digits>`
(the `chat.guid` value, which Heimdall returns as `sourceThreadId`); chat ids require
`imessage_only`, and a read-only Messages.app preflight rejects a chat id Messages does
not know or that does not run on an iMessage account, so nothing goes out over SMS/RCS.
The sender never resolves or lists chats. Contact names, email
addresses, contact selections, group names, participant lists, and recipient discovery
are rejected.

The repository contains no general message-history query, Contacts integration, chat
listing, attachments, or later status lookup. After a send is accepted, a fixed
read-only `chat.db` query considers at most ten recent outgoing candidates for the
same recipient and expected transport, and requires the exact outbound body. It pins
that row only for the current attempt and retains no database row or send identifier
after the call. Heimdall is not part of the send path.

Apple Blocked Contacts remains the platform-level delivery block; this adapter
neither reads nor maintains a separate blocklist.

## Delivery behavior

Each call uses its required `delivery_mode`. `imessage_only` never calls the SMS/RCS
transport, including after a synchronous or database-observed iMessage failure.
`imessage_with_sms_fallback` attempts the enabled SMS/RCS service exactly once after
either a synchronous iMessage AppleScript failure or an exactly correlated,
database-observed `error:send_failed:iMessage`. The SMS/RCS attempt gets its own start
timestamp and observation window.

Fallback after a database-observed failure deliberately accepts duplicate-delivery
risk: a row can report an asynchronous error before the recipient later receives the
iMessage. Unknown status, sent-unconfirmed, timeout, interruption, missing response,
or a non-correlated outcome never authorizes fallback in either mode. Use
`imessage_only` when duplicate-free transport isolation matters more than reaching an
SMS/RCS destination.

SMS/RCS from a Mac depends on the paired iPhone and Messages configuration described by
[Apple's Text Message Forwarding documentation](https://support.apple.com/en-us/102545).

Results are intentionally narrow:

- `delivered:iMessage`
- `delivered:SMS`
- `sent-unconfirmed:iMessage:delivery-timeout`
- `sent-unconfirmed:SMS:delivery-timeout`
- `sent:iMessage:group-delivery-not-reported`
- `error:send_status_unknown:iMessage:database-unavailable`
- `error:send_status_unknown:SMS:database-unavailable`
- `error:send_status_unknown:iMessage:message-not-correlated`
- `error:send_status_unknown:SMS:message-not-correlated`
- `error:send_status_unknown:iMessage:send-state-timeout`
- `error:send_status_unknown:SMS:send-state-timeout`
- `rejected:invalid_recipient`
- `rejected:empty_message`
- `rejected:message_too_long`
- `rejected:group_requires_imessage_only`
- `rejected:unknown_chat_id`
- `rejected:group_not_imessage`
- `error:send_failed:iMessage`
- `error:send_failed:SMS`
- `error:timeout`
- `error:automation_failed`
- `error:unexpected_result`

The transient observer polls every 500 milliseconds for at most ten seconds per
transport attempt. It searches recent outgoing rows using recipient, attempt start
time, exact body, and expected transport, then pins the exact row identifier for later
polls. The newest-recipient-row heuristic is never authoritative.
`delivered` means that the resolved Messages row reported delivery; it does not mean
a human read the message.
`sent-unconfirmed` means the row was marked sent but its delivery flag was still
absent when the ten-second window ended. `sent:iMessage:group-delivery-not-reported`
means a group-chat row was marked sent; Messages never reports delivery for group
iMessages, so the observer returns as soon as that row is seen. The observer continues polling after
`is_sent`. `error:send_status_unknown` distinguishes an unavailable database, a
message that could not be correlated, and an exact row whose send state remained
unresolved.
`error:send_failed:<service>` means that transport reported an immediate failure or
the exact correlated row continued to report an asynchronous failure through the
observation window. An iMessage failure starts SMS/RCS only when the caller explicitly
selected `imessage_with_sms_fallback` and the failure was immediate or exactly
correlated. A simultaneous send to the same recipient remains unknown unless the
exact body can be decoded and matched.

Clients should allow at least 40 seconds for one MCP invocation. The AppleScript
process timeout remains 30 seconds, and a timeout or missing response is ambiguous:
never retry it automatically.

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
per-call approval, require the delivery mode on every call, and never retry a
tool-call timeout or missing response. An internal SMS/RCS attempt is part of the
same approved call only when `imessage_with_sms_fallback` was explicitly selected.
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
interrupted post-invocation result is never retried automatically. Unknown-status
tokens prove that a submission reached Messages.app. A definitive-failure token may
instead represent an immediate failure, so mutation remains unknown. The harness
returns failure unless the final result is delivered or sent-unconfirmed.
Live harness sends default to `imessage_only`; selecting
`--delivery-mode imessage_with_sms_fallback` explicitly authorizes the one possible
SMS/RCS continuation.

## Origin

This repository was forked from
[`carterlasalle/mac_messages_mcp`](https://github.com/carterlasalle/mac_messages_mcp)
to retain its tested macOS Messages send behavior, then reduced to an independent
send-only surface.
