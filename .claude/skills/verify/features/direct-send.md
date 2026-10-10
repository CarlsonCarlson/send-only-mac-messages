# Direct send to a phone number

A client sends one text body to one exact phone number through Messages.app on this Mac with `delivery_mode: imessage_only`, and gets back a fixed token describing what the Mac observed.

## Sub-features

- `direct-normalize` accepts ten-digit US and E.164 numbers and normalizes them to `+1…`/`+…`.
- `direct-imessage-only` never attempts SMS/RCS, whatever iMessage does.
- `direct-observe` returns `delivered:iMessage`, `sent-unconfirmed:iMessage:delivery-timeout`, `error:send_failed:iMessage`, or an `error:send_status_unknown:iMessage:*` reason.

## How to get to it (user POV)

- Any MCP client calls `tool_send_message` with `recipient`, `message`, `delivery_mode: "imessage_only"`.

## Driving it with drive_send.py

Preconditions:

- Doctor passes. Carlson has named the target number for this run.

- **Send.** `printf '%s\n' '<number>' | uv run python .claude/skills/verify/scripts/drive_send.py --send`. Stdout JSON has `token` starting with `delivered:iMessage` or `sent-unconfirmed:iMessage`.
- **Proof.** `db_proof` has exactly one row, `service` `iMessage`, `is_sent` `1`, `handle_id` non-zero, `send_error` `0`. For a self-send `is_delivered` becomes `1` within the window.
- **Normalization.** Repeat with the same number formatted as `(415) 555-1234`; the row's handle matches the `+1…` form.

## Gotchas

- `delivered` means the Messages row flipped `is_delivered`; it is not a read receipt.
- A number not registered for iMessage yields `error:send_failed:iMessage` in this mode; no SMS goes out. That is correct behavior, not a bug.
- Full Disk Access missing for the terminal gives `error:send_status_unknown:iMessage:database-unavailable` even though the message went out. Check `db_proof` from a terminal that has it before concluding anything.
