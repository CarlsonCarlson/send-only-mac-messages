# Changelog

## [0.3.0] - Unreleased

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
