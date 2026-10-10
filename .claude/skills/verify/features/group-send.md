# Group chat send

A client sends one text body into an existing Messages group chat by its exact chat id (for example `any;+;chat123456789012345678`), `imessage_only`, and gets a fixed token. This is the feature under development: at the current version the tool rejects the chat id before touching Messages.app.

## Sub-features

- `group-chat-id` accepts `<service>;+;chat<digits>` as the recipient.
- `group-imessage-only` rejects `imessage_with_sms_fallback` for a chat target.
- `group-observe` correlates the outgoing row through `chat_message_join` to the chat guid (group rows have `handle_id = 0`).

## How to get to it (user POV)

- `tool_send_message` with `recipient` set to the chat id from Heimdall's `sourceThreadId` (it is the Messages `chat.guid`), `delivery_mode: "imessage_only"`.

## Driving it with drive_send.py

Preconditions:

- Doctor passes with the chat id argument and reports participants.
- Carlson has authorized one test message to that group in this session.

- **Baseline (version 0.2.0).** `printf '%s\n' "$GROUP" | uv run python .claude/skills/verify/scripts/drive_send.py --send` with `GROUP` read from `verification-evidence/targets.txt`. Token `rejected:invalid_recipient`, `db_proof` empty. Nothing was sent.
- **Target behavior (verified 2026-10-07, version 0.3.0).** Same command. Token `sent:iMessage:group-delivery-not-reported`. `db_proof` has one row with `chat_guid` equal to the target, `handle_id` `0`, `service` `iMessage`, `is_sent` `1`, `send_error` `0`.
- **Fallback rejected.** Add `--delivery-mode imessage_with_sms_fallback`. Token `rejected:group_requires_imessage_only`, `db_proof` empty.
- **Unknown chat.** Target `any;+;chat1`. Token `rejected:unknown_chat_id`, `db_proof` empty.
- **SMS/RCS group.** Target a group whose `chat.service_name` is `SMS` or `RCS`. Token `rejected:group_not_imessage`, `db_proof` empty; nothing goes out over SMS under `imessage_only`.
- **Recipient view.** Ask a group member or check the receiving agent's inbox: the body `verify-send <run_id>` appears in the group.

## Gotchas

- Group iMessages on macOS 26 never flip `is_delivered`; do not wait for `delivered:*`.
- The sender alias is the chat's `last_addressed_handle`; check it before promising which number the recipients will see. `account_login` is only the Apple ID login and says nothing about which number the message shows from.
- Group rows usually have `text` NULL with the body in `attributedBody`; the driver decodes it. A SQL `text =` match misses them.
- A chat id from another Mac's database is meaningless here; chat ids are per Messages database. Use the id from the sending Mac (or, for the hosted Mac, from Kevin's Heimdall).
- Every successful drive posts a visible test message to real people.
