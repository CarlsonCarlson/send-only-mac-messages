# Send-only Mac Messages

This context defines the boundary between Heimdall's message-reading policy and the
narrow macOS Messages component that performs outbound sends.

## Language

**Send-only Messages adapter**:
A macOS Messages component implemented by this repository. It exposes exactly one
MCP tool that accepts an exact phone number and message text, then performs the send
without message reads, contact lookup, recipient discovery, group lookup, resources,
prompts, or attachments. New numbers do not need to exist in Contacts or Heimdall.
_Avoid_: Messages MCP, general Messages bridge

**Raw phone-number recipient**:
The exact number supplied by the caller. Ten-digit US numbers and E.164-style
international numbers are accepted without consulting Contacts, Heimdall, prior
conversations, or any other local data source.
_Avoid_: Contact name, contact selector, discovered recipient

**Message-reading authority**:
Heimdall is the only component allowed to read or search Messages data. The send-only
Messages adapter has no message-reading capability.
_Avoid_: Shared reader, read-capable sender

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
iMessage first and keeps immediate SMS/RCS fallback when the iMessage AppleScript
attempt errors. It does not inspect prior messages to predict service availability.
_Avoid_: iMessage-only sender

**Accepted-unverified**:
A fixed result meaning Messages.app accepted the AppleScript command through iMessage
or SMS. It does not claim delivery or human receipt, and the adapter never reads
`chat.db` to strengthen that claim.
_Avoid_: Sent, delivered, receipt-confirmed
