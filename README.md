# Send-only Mac Messages

A deliberately narrow MCP server for sending direct messages through macOS
Messages.app. It exposes one tool and has no code path for reading local user data.

## Boundary

`tool_send_message(recipient, message)` accepts an exact phone number and text body.
Ten-digit US numbers are normalized with `+1`; international numbers may be passed in
E.164 form. Contact names, email addresses, contact selections, group identifiers,
and recipient discovery are rejected.

The repository contains no message-history queries, Contacts integration, chat
listing, attachments, `chat.db` access, or Full Disk Access requirement. Heimdall is
not part of the send path. Apple Blocked Contacts remains the platform-level delivery
block; this adapter neither reads nor maintains a separate blocklist.

## Delivery behavior

Each call tries iMessage first. If that AppleScript attempt fails immediately, it
tries the enabled SMS service exposed by Messages.app. SMS/RCS from a Mac depends on
the paired iPhone and Messages configuration described by
[Apple's Text Message Forwarding documentation](https://support.apple.com/en-us/102545).

Results are intentionally narrow:

- `accepted-unverified:iMessage`
- `accepted-unverified:SMS`
- `rejected:invalid_recipient`
- `rejected:empty_message`
- `rejected:message_too_long`
- `error:send_failed`
- `error:timeout`
- `error:automation_failed`
- `error:unexpected_result`

`accepted` means Messages.app accepted the AppleScript command. It does not claim
delivery or human receipt because proving either would require a separate observation
source; this adapter does not read the Messages database.

Recipient and message content are passed to `osascript` over standard input, not in
process arguments or environment variables. Tool results and logs do not echo either
value.

## Requirements

- macOS with Messages.app signed in under the intended sending profile
- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/)
- Automation permission for the GUI application or Terminal process that launches the
  server to control Messages
- For SMS/RCS fallback, the applicable paired-iPhone Messages configuration

No Full Disk Access or Contacts permission is needed.

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

## Origin

This repository was forked from
[`carterlasalle/mac_messages_mcp`](https://github.com/carterlasalle/mac_messages_mcp)
to retain its tested macOS Messages send behavior, then reduced to an independent
send-only surface.
