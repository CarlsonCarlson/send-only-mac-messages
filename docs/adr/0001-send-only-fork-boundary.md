# ADR-0001: Reduce the tested fork to one outbound tool

**Status:** Accepted; delivery-observation clauses superseded by ADR-0003

## Context

The original fork exposed message history, search, Contacts lookup, chat discovery,
attachments, diagnostics, and sending. The hosted Carlson prototype proved its send
path under the Carlson graphical session, but the product goal is a mass-text sender,
not a second message reader. Heimdall already owns the separate message-reading
boundary.

Research found a smaller independent sender, but it had substantially less test and
operational evidence and exposed send data in process arguments and tool results. The
existing fork had stronger send regressions and a successful hosted-Mac canary.

## Decision

Rename the fork and repository to `send-only-mac-messages`, retain the proven send
behavior as prior art, and delete every reader. The MCP surface contains exactly one
tool: a direct send to a raw phone number. It has no Contacts access, contact-name or
group resolution, message or chat database access, attachments, MCP resources, MCP
prompts, Full Disk Access requirement, or Heimdall connection.

Keep immediate iMessage-to-SMS fallback for now. Return only fixed
accepted-unverified, rejected, or error tokens. Send payloads reach `osascript` over
standard input rather than arguments or environment variables.

Apple's Blocked Contacts behavior remains outside the adapter. A Heimdall-hidden
conversation remains unreadable but is not automatically unsendable.

## Consequences

- Raw numbers can be used before they exist in Contacts or prior conversations.
- The adapter cannot resolve a name, inspect a thread, choose a group, fetch an
  attachment, or verify delivery from `chat.db`.
- SMS fallback depends on the hosted Mac and paired iPhone's Messages configuration.
- `accepted-unverified:iMessage` and `accepted-unverified:SMS` mean command
  acceptance, not delivery.
- Any future read capability, recipient discovery, group sending, delivery observer,
  custom blocklist, or second MCP tool requires a new architecture decision.
