---
name: verify
description: Drive the send-only Mac Messages MCP (stdio transport) on this Mac the way a client does, send one real message when authorized, and prove the result from chat.db. Use before and after any change to sending, delivery observation, validation, or the tool surface, and for the group-chat canary to the test group listed in verification-evidence/targets.txt.
---

# Verify send-only-mac-messages

The product is one MCP tool, `tool_send_message`, that drives Messages.app on the Mac it runs on. Verification means: start the server over stdio exactly as a client would, call the tool, read the fixed result token, and independently read the outgoing row in `~/Library/Messages/chat.db`. There is no UI to screenshot. The proof is the token plus the database row.

Messages.app is one shared instance. A send here is a real message from this Mac's signed-in account. Never run two drives at once, and never run a send while another agent is sending from this Mac.

## Launch

No long-running server. `drive_send.py` spawns `python -m send_only_mac_messages.server` per run and tears it down when the client closes. One-time prerequisites from the repo root:

```bash
uv sync --extra dev
```

Ready when `doctor.sh` passes. The remote HTTP transport is not driven by this skill; its no-send smoke is `scripts/smoke-public-mcp-url.sh` against the published host, and a live remote canary is `scripts/hosted_canary.py` on the hosted Mac.

## Doctor

Read-only. Run first, and again whenever a result looks wrong:

```bash
.claude/skills/verify/scripts/doctor.sh
.claude/skills/verify/scripts/doctor.sh "$(awk -F'\t' '$1=="group"{print $2}' verification-evidence/targets.txt)"
```

Passes when the venv imports, the version metadata is consistent, Messages.app is running, `chat.db` is readable (Full Disk Access for the terminal), and, with a chat id, that chat exists with at least one participant. The `services:` line must be a number; an error there means Automation permission for this terminal is missing or Messages is not signed in.

## Drive

Driver: `.claude/skills/verify/scripts/drive_send.py`. The target goes on stdin so phone numbers stay out of shell history.

```bash
# surface only, never sends
uv run python .claude/skills/verify/scripts/drive_send.py --smoke-only

# one authorized send; target is a phone number or a Messages chat id
printf '%s\n' '<target>' | uv run python .claude/skills/verify/scripts/drive_send.py --send
printf '%s\n' '<target>' | uv run python .claude/skills/verify/scripts/drive_send.py --send --delivery-mode imessage_with_sms_fallback

# driver self-check (no server, no send)
uv run python .claude/skills/verify/scripts/drive_send.py --self-test
```

A send body is always `verify-send <run_id>`, so it is unique and recognizable to the recipient as a test. Known targets are not committed: they live in `verification-evidence/targets.txt` (gitignored), one `label<TAB>target` per line. Read it before a send and pass the exact value on stdin. A self-send to Carlson's own number is the lowest-impact live check of the phone path.

Authorization: `--send` reaches real people. Run it only on Carlson's explicit say-so for that target in this session. A tool error, timeout, or missing output is an unknown outcome: never rerun `--send` to "check".

## Evidence

Every run writes `verification-evidence/<run_id>-<mode>.json` (gitignored) and prints the same JSON with `evidence_path`. Fields:

- `surface`: tool names, schema properties and required list, resource and prompt counts, `ok`.
- `token`: the fixed result string, or `unexpected` if it is not in the fixed vocabulary.
- `db_proof`: outgoing rows with that exact body after the send started, each with `chat_guid`, `handle_id`, `service`, `is_sent`, `is_delivered`, `send_error`. The driver polls up to 12 seconds.

Proof standards: a `rejected:*` token must come with an empty `db_proof` (nothing sent). A `delivered:*` or `sent-unconfirmed:*` token must come with exactly one row whose `chat_guid` or handle matches the target. Group rows have `handle_id = 0` and, on this OS, `is_delivered` stays `0` for group iMessages; `is_sent = 1` with `send_error = 0` is the strongest observable group proof. Never treat the token alone as proof of a send, and never treat `is_sent` as proof a human read it.

## Cleanup

The stdio server exits with the driver; there is nothing to kill. Remove scratch only:

```bash
rm -rf .pytest_cache/.verify-scratch 2>/dev/null; true
```

Do not delete `verification-evidence/`. Test messages already delivered to a group cannot be recalled; tell the recipients it was a test if that matters.

## Features

See [features/README.md](features/README.md) for the maintained map of user-facing behavior and the recipe for each.
