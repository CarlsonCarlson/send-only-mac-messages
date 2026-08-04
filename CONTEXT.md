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
A ten-second, in-call `chat.db` observation restricted to one outgoing attempt. Exact
correlation requires the recipient or a normalized handle variant, the attempt start
time, the exact plain or decoded attributed body, and the expected transport. The
observer pins the matched row identifier for later polls and never treats the newest
recipient row as evidence. It returns fixed status tokens and retains no row, GUID,
recipient, body, or attempt identifier after the call.
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
iMessage first. A synchronous AppleScript failure or an exactly correlated definitive
iMessage failure permits exactly one SMS/RCS attempt inside the same authorized call.
Each attempt has its own start time and ten-second observation window. Every unknown
or ambiguous outcome stops without fallback.
_Avoid_: iMessage-only sender

**Send status unknown**:
A fixed error result meaning the adapter cannot safely classify one submitted attempt.
Its reason is `database-unavailable`, `message-not-correlated`, or
`send-state-timeout`. It never authorizes automatic fallback or retry.
_Avoid_: Accepted, failed, retryable

**Sent-unconfirmed**:
A fixed result meaning the correlated outgoing row was marked sent, but its delivery
flag was still absent when the observation window ended. Its fixed reason is
`delivery-timeout`.
_Avoid_: Delivered, failed

**Delivered**:
A fixed result meaning the correlated outgoing row was marked delivered within the
observation window. It is not proof that a human read the message.
_Avoid_: Read, human-confirmed
