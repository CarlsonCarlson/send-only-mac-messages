# SMS/RCS fallback mode

With `delivery_mode: imessage_with_sms_fallback`, the tool submits iMessage first and may submit SMS/RCS exactly once after an immediate or exactly correlated iMessage failure. The caller accepts that a delayed iMessage and the SMS can both arrive.

## Sub-features

- `fallback-immediate` SMS after AppleScript rejects the iMessage at once.
- `fallback-observed` SMS after the correlated row reports `error` within the window.
- `fallback-never-on-unknown` no SMS after timeout, unknown, or uncorrelated outcomes.

## How to get to it (user POV)

- `tool_send_message` with `delivery_mode: "imessage_with_sms_fallback"`.

## Driving it with drive_send.py

Preconditions:

- Doctor passes. This Mac has Text Message Forwarding from a paired iPhone, or the fallback cannot succeed.
- Carlson named a target that is known not to be on iMessage (an Android number), or accepted the duplicate risk for an iMessage target.

- **Send.** `printf '%s\n' '<number>' | uv run python .claude/skills/verify/scripts/drive_send.py --send --delivery-mode imessage_with_sms_fallback`. Token is `delivered:SMS` or `sent-unconfirmed:SMS:delivery-timeout` for a non-iMessage target.
- **Proof.** `db_proof` shows the SMS/RCS row with `is_sent` `1`; an earlier iMessage row with `send_error` non-zero may also appear. Both rows have the same body.

## Gotchas

- Against an iMessage-capable target this mode behaves like `imessage_only`; nothing to see.
- Two rows with the same body is the documented duplicate risk, not a driver bug.
- The driver's token filter accepts any `delivered:SMS`-shaped token; read `service` in `db_proof` to confirm which transport actually carried it.
