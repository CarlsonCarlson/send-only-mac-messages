# Send-only Mac Messages

This context defines the boundary between Heimdall's message-reading policy and the
narrow macOS Messages component that performs outbound sends.

## Language

**Send-only Messages adapter**:
A macOS Messages component implemented by this repository. It exposes exactly one
MCP tool that accepts an exact phone number and message text, then performs the send
without history reads, contact lookup, recipient discovery, group lookup, resources,
prompts, or attachments. After submission it may transiently observe only the
correlated outgoing row's send status. New numbers do not need to exist in Contacts
or Heimdall.
_Avoid_: Messages MCP, general Messages bridge

**Raw phone-number recipient**:
The exact number supplied by the caller. Ten-digit US numbers and E.164-style
international numbers are accepted without consulting Contacts, Heimdall, prior
conversations, or any other local data source.
_Avoid_: Contact name, contact selector, discovered recipient

**Message-reading authority**:
Heimdall is the only component allowed to read or search Messages history. The
send-only Messages adapter has one exception: bounded correlation and status
observation for the message it just submitted.
_Avoid_: Shared history reader, searchable sender

**Transient send observation**:
A six-second, in-call `chat.db` observation restricted to recent outgoing candidates
for the supplied phone number and send time. The verbatim upstream verifier prefers
an exact body match, then falls back to the newest candidate for that recipient. It
returns fixed status tokens and retains no row, GUID, recipient, body, or attempt
identifier after the call.
_Avoid_: Message history, delivery database, later status lookup

**Conversation visibility**:
Heimdall's policy for whether message content may be read by an agent or operator. A
hidden conversation remains unreadable but its number is not automatically prohibited
from receiving outbound messages.
_Avoid_: Send permission, outbound authorization

**System-blocked destination**:
A phone number or contact in Apple's Blocked Contacts list. Apple prevents messages
to or from that destination from being delivered; the send-only adapter does not
maintain or inspect a separate blocklist.
_Avoid_: Heimdall-hidden destination, custom suppression record

**Independent send path**:
The outbound path from Nimbus to the send-only Messages adapter. It does not call
Heimdall, and Heimdall does not depend on or connect to the adapter.
_Avoid_: Heimdall-authorized sender, Heimdall send clearance

**Messages delivery service**:
The Apple Messages transport selected for an outbound phone number. The adapter tries
iMessage first and uses the upstream AppleScript's immediate SMS/RCS fallback when
the iMessage AppleScript block errors. A later failure reported by the transient
observer is returned to the caller and does not trigger another send attempt.
_Avoid_: iMessage-only sender

**Accepted-unverified**:
A fixed result meaning Messages.app accepted the AppleScript command through iMessage
or SMS, but the transient observer could not resolve a correlated status. It does not
claim delivery or human receipt.
_Avoid_: Sent, delivered, receipt-confirmed

**Sent-unconfirmed**:
A fixed result meaning the correlated outgoing row was marked sent before its
delivery flag was present. The verbatim upstream verifier stops at `is_sent`.
_Avoid_: Delivered, failed

**Delivered**:
A fixed result meaning the correlated outgoing row was marked delivered within the
observation window. It is not proof that a human read the message.
_Avoid_: Read, human-confirmed
