# Changelog

## [0.3.2] - 2026-10-27

- Refuse every send from 8pm to 8am Pacific with `rejected:quiet_hours` (Carlson,
  2026-10-27: "no more sending past 8pm"). The check runs first, before input checks
  and before Messages.app is touched, so it covers every caller of this server, cloud
  routines included. The time is read in America/Los_Angeles, so the edge follows
  daylight saving. `send_message` takes an optional `clock` for tests.

## [0.3.1] - 2026-10-12

- Correct the result glossary after the first hosted group test: `rejected:unknown_chat_id`
  means Messages has not loaded the chat (quiet groups), `error:send_failed` can still
  reach the person, and `imessage_only` cannot stop Messages itself from switching a
  failed iMessage to SMS. Tighten the chat id pattern to `chat<digits>` or 32 hex.
  Raise the suggested client timeout to 90 seconds.

## [0.3.0] - 2026-10-12

- Accept an exact Messages chat id (`<service>;+;chat<digits>`) as `recipient` to send
  into an existing group chat (ADR-0008). The caller supplies the id; the adapter still
  resolves nothing.
- Reject `imessage_with_sms_fallback` for chat targets with
  `rejected:group_requires_imessage_only`. A read-only Messages.app preflight returns
  `rejected:unknown_chat_id` or `rejected:group_not_imessage` before any submission.
- Correlate group sends through `chat_message_join` to the exact chat guid (group rows
  have `handle_id = 0`) and return `sent:iMessage:group-delivery-not-reported` as soon
  as the row is marked sent, since group iMessages never report delivery.
- Also accept 32-hex-character group chat ids (`any;+;<32 hex characters>`), which
  Messages uses alongside `chat<digits>`. The pattern is now
  `(any|iMessage|SMS|RCS);+;[A-Za-z0-9]+`; the read-only preflight still rejects any
  chat Messages does not know or that is not on iMessage.
- Rewrite the tool description, argument descriptions, and server instructions in
  plain words. The tool description now lists every result string, what causes it,
  and whether the caller may call again. Local and remote servers now show the same
  description and argument descriptions. Argument names, mode values, and result
  strings are unchanged.
- Add a third delivery mode, `sms_only` (ADR-0009). It makes one SMS/RCS attempt and
  never tries iMessage, so a caller that already knows a number has no iMessage
  leaves one bubble instead of a failed iMessage plus the SMS. Chat ids with
  `sms_only` return `rejected:group_requires_imessage_only`.
- Add a project verification skill (`.claude/skills/verify`) that drives the stdio
  server like a client and proves outcomes from `chat.db`.

## [0.1.0] - Unreleased

- Rename the fork to `send-only-mac-messages`.
- Expose exactly one MCP tool for direct phone-number sends.
- Remove all message, contact, chat, database, and attachment readers.
- Cherry-pick the upstream iMessage-to-SMS/RCS fallback implementation from
  `f77be9e`, limited to the send-only package surface.
- Pass send data to `osascript` over standard input and redact results.
- Add an optional principal-bound Streamable HTTP entry point with Heimdall-style
  bearer/digest authentication, strict origin checks, and sender attestation.
- Add owner-only bearer create, replace, and revoke tooling plus launchd and
  Cloudflare deployment templates.
- Cherry-pick upstream's read-only, six-second delivery verifier from `1a8f309`
  verbatim, without adding another MCP tool or retaining message state.
- Require exact body and transport correlation, pin the resolved attempt row, and
  observe each transport for up to ten seconds at 500-millisecond intervals.
- Fall back to SMS/RCS exactly once only after a synchronous iMessage AppleScript
  failure, with a fresh timestamp and observation window. Database-observed failures
  remain final to prevent duplicate transport submissions.
- Replace `accepted-unverified` and `status-pending` with fixed
  `error:send_status_unknown` reason tokens.
