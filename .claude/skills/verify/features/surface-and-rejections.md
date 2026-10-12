# Rejections and tool surface

Clients discover exactly one tool with three required arguments, and bad input is rejected with a fixed token before Messages.app is touched.

## Sub-features

- `surface-one-tool` `tools/list` returns only `tool_send_message`; no resources, no prompts.
- `surface-schema` properties `recipient`, `message`, `delivery_mode` are all required; `delivery_mode` enum is `imessage_only`, `imessage_with_sms_fallback`.
- `reject-recipient` names, emails, short digit strings → `rejected:invalid_recipient`.
- `reject-body` blank → `rejected:empty_message`; over 4000 chars → `rejected:message_too_long`.
- `reject-mode` unknown mode → `rejected:invalid_delivery_mode`.

## How to get to it (user POV)

- Any MCP client's `tools/list`, then `tools/call` with bad input.

## Driving it with drive_send.py

Preconditions:

- Doctor passes. No authorization needed: none of these reach Messages.app.

- **Surface.** `uv run python .claude/skills/verify/scripts/drive_send.py --smoke-only`. `surface.ok` is `true`, `tool_names` is `["tool_send_message"]`, `required` lists all three properties.
- **Bad recipient.** `printf '%s\n' 'Carlson Cheng' | uv run python .claude/skills/verify/scripts/drive_send.py --send`. Token `rejected:invalid_recipient`, `db_proof` empty.
- **Unit rejections.** `uv run pytest -q tests/test_sender.py -k "rejects"` covers blank, oversized, and bad-mode bodies without a server.

## Gotchas

- A `rejected:*` drive still spawns the server; it just never runs AppleScript. The empty `db_proof` is the proof.
- Schema assertions also live in `tests/test_server_surface.py`; keep them and this file in step when the surface changes.
