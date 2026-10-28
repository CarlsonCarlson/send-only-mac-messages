# send-only-mac-messages verification map

This directory is the maintained source for verifying the user-facing behavior of the send-only Messages MCP. Read the index before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- Work from the repo root with `uv sync --extra dev` done.
- `.claude/skills/verify/scripts/doctor.sh` passes.
- Messages.app on this Mac is signed in to the account the test should send from.
- `verification-evidence/targets.txt` holds the real targets (gitignored); never paste them into committed files.
- No other agent or person is sending from this Mac.

## Driving conventions

- Every drive goes through `drive_send.py`; the target goes on stdin.
- A send is real. Only `--smoke-only` and `--self-test` are safe to run without Carlson's say-so.
- One send per authorization. An error, timeout, or missing output ends the attempt.
- Read `verification-evidence/<run_id>-send.json` for the token and `db_proof`; never infer from the server log.

## Proof and skip reporting

- Report the token and the matching `db_proof` row together.
- A `rejected:*` token with an empty `db_proof` proves nothing was sent.
- Record the feature ID, target kind, and evidence path with every result.
- Report a feature you could not drive (no authorization, no target) as not verified, with the unmet precondition.

## Features

- [Direct send to a phone number](./direct-send.md): `imessage_only` to an exact number.
- [SMS/RCS fallback mode](./sms-fallback.md): `imessage_with_sms_fallback` and its duplicate risk.
- [Group chat send](./group-send.md): a Messages chat id target. Today rejected; this is the feature under development.
- [Rejections and tool surface](./surface-and-rejections.md): schema, required fields, and the `rejected:*` tokens that never reach Messages.app.
