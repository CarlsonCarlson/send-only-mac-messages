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
A ten-second, in-call `chat.db` observation for one transport attempt, restricted to
recent outgoing candidates for the supplied phone number, attempt start time, exact
body, and expected transport. After an exact match it pins the row identifier and
continues past `is_sent` until delivery, failure, or timeout. A fallback SMS/RCS
attempt receives its own start time and ten-second window. The observer returns fixed
status tokens and retains no row, identifier, recipient, body, or attempt state after
the call.
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

**Messages delivery mode**:
The required per-call policy selected by the caller. `imessage_only` submits through
iMessage and never invokes SMS/RCS. `imessage_with_sms_fallback` submits through
iMessage first and may submit SMS/RCS exactly once after either a synchronous
AppleScript failure or an exactly correlated database-observed failure. The latter
explicitly accepts the known risk that a delayed iMessage and the fallback can both
arrive. Unknown, timed-out, interrupted, missing, or non-correlated outcomes never
authorize fallback or retry. Omitted or invalid modes fail before Messages.app.
_Avoid_: Automatic transport selection, implicit SMS permission

**Send-status unknown**:
A fixed error result meaning Messages.app accepted the AppleScript command, but the
transient observer cannot say whether the exact attempt was sent. Its fixed reason is
`database-unavailable`, `message-not-correlated`, or `send-state-timeout`. It never
authorizes fallback or retry and does not claim delivery or human receipt.
_Avoid_: Sent, delivered, receipt-confirmed

**Sent-unconfirmed**:
A fixed result meaning the correlated outgoing row was marked sent, but its delivery
flag was still absent when the ten-second observation window ended. Its fixed reason is
`delivery-timeout`.
_Avoid_: Delivered, failed

**Delivered**:
A fixed result meaning the correlated outgoing row was marked delivered within the
observation window. It is not proof that a human read the message.
_Avoid_: Read, human-confirmed
