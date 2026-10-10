# ADR-0008: Send into an existing group chat by its exact Messages chat id

**Status:** Accepted

## Context

ADR-0001 limited the tool to one raw phone number and said group sending would need
a new decision. Kevin's client work regularly targets existing iMessage groups (a
couple, a household), and the only other route was driving Messages.app by hand.

Three facts shaped the shape of the change. AppleScript addresses an existing group
as `chat id "<service>;+;chat<digits>"`, the same string `chat.db` stores in
`chat.guid` and the same string Heimdall returns as `sourceThreadId`. Outgoing
group rows carry `handle_id = 0`, so the handle-based observer from ADR-0003/0005
can never correlate them. And on macOS 26 group iMessages never report
`is_delivered` (local sample: 1030 outgoing group iMessages in 90 days, none
delivered), so waiting for delivery is a guaranteed timeout.

## Decision

Keep one tool. `recipient` now also accepts an exact Messages chat id matching
`^(any|iMessage|SMS|RCS);\+;chat[0-9]+$`. The sender does not resolve, list, or
search chats; the caller supplies the id (from Heimdall on the hosted Mac). Names,
participant lists, and partial ids are still `rejected:invalid_recipient`.

Chat targets are iMessage-only. `imessage_with_sms_fallback` with a chat id returns
`rejected:group_requires_imessage_only` before Messages.app. Because AppleScript's
`send ... to chat id` uses whatever service the chat already has, a read-only
AppleScript preflight asks Messages.app for the chat and its account's service type
first: an unknown id returns `rejected:unknown_chat_id`, and a chat that is not on an
iMessage account returns `rejected:group_not_imessage`. Nothing is submitted in either
case. There is no MMS group continuation.

The observer correlates a chat target through `chat_message_join` to the exact
`chat.guid`, with the same exact-body, outgoing-only, transport, start-time and
ten-candidate limits as ADR-0005. Because delivery is never reported for groups, a
clean `is_sent` row ends the window at once with the new fixed token
`sent:iMessage:group-delivery-not-reported`. An observed error is still
`error:send_failed:iMessage`; no row is still `message-not-correlated`.

The ADR-0003 rule against reading the chat table as a source stands: the chat table
appears only as a JOIN that filters the outgoing row for the send just made. The
direct phone path is unchanged, including its observer call.

## Consequences

- Clients can reach an existing group with one call and one id; Heimdall's
  `sourceThreadId` is that id.
- A group result is "sent", never "delivered". Callers must not wait for or infer
  delivery.
- Chat ids are per Messages database. An id from one Mac means nothing on another.
- The sender alias is the chat's existing `last_addressed_handle`; the tool cannot
  change which number a group shows the message from.
- Verified live on 2026-10-07 from a local Mac into an existing three-person group
  (`.claude/skills/verify`; the evidence file is kept outside git).
