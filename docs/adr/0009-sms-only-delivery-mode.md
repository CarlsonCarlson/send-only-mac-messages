# ADR-0009: Add an `sms_only` delivery mode

**Status:** Proposed. Shipped in 0.3.0 behind an explicit mode value; no caller uses it and no live send has exercised it. Carlson decides whether campaigns may use it.

## Context

ADR-0007 gave callers two modes. `imessage_only` cannot reach a number without
iMessage. `imessage_with_sms_fallback` can, but only by trying iMessage first. When
that iMessage fails, the sender's thread keeps the failed iMessage bubble and gains a
second SMS bubble. If the iMessage was only delayed, the person gets the text twice.
A live fallback send to an Android number (2026-10-12 UTC, recorded in
`docs/decisions/2026-10-06-group-chat-sends.tsv`) left both bubbles. The iMessage row
failed with error 22, and the RCS row was delivered.

Campaign callers often already know from message history that a number has never
used iMessage. For them the iMessage attempt is pure cost. Research in the owner's
automation repository (`docs/research/photon-sms-fallback-2026-10-11.md`) found no
outside library that avoids this, and recommended choosing the transport before the
one attempt.

## Decision

Add a third value, `sms_only`, to the required `delivery_mode` argument.

- `sms_only` calls the existing SMS/RCS sender exactly once and never calls the
  iMessage sender. No result in this mode leads to another attempt.
- A chat id with `sms_only` returns `rejected:group_requires_imessage_only` before
  Messages.app, as fallback mode already does. Groups stay iMessage-only (ADR-0008).
- The SMS/RCS sender, its observation window, and its result strings are unchanged.
  An `sms_only` call returns the same tokens as the SMS half of a fallback call.

## Consequences

- A caller that knows a number is SMS-only makes one attempt and leaves one bubble.
- Choosing the mode is the caller's call. If the history is stale and the person now
  uses iMessage, the SMS still goes out as SMS. The tool does not check.
- The mode enum grows from two values to three. Existing calls are unaffected.
