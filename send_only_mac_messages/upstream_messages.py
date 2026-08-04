"""Send and delivery subset adapted from upstream Mac Messages MCP.

Upstream provenance:
- SMS/RCS fallback: f77be9eb18d38ba1e3d0ea35721c45d4781344b9
- Delivery verification: 1a8f309 (as merged in a6e460526096996ea04ab880e519e3ae627b0dc3)

Most marked function bodies come from ``mac_messages_mcp/messages.py`` at
``a6e4605``. The local transport adapter preserves this fork's stdin-only payload
boundary and redacts subprocess errors. ADR-0005 replaces the upstream correlation
heuristic with an exact, row-pinned observer and a structured one-fallback policy.
"""

# isort: skip_file
# mypy: ignore-errors

import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

_APPLESCRIPT_TIMEOUT_SECONDS = 30


def run_applescript(script: str, timeout: float = _APPLESCRIPT_TIMEOUT_SECONDS) -> str:
    """Run AppleScript over stdin while preserving upstream-compatible results."""
    try:
        completed = subprocess.run(
            ["osascript", "-"],
            input=script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: AppleScript timed out after {timeout:g} seconds"
    if completed.returncode != 0:
        return "Error: AppleScript automation failed"
    return completed.stdout.strip()


# BEGIN ADAPTED UPSTREAM SUBSET (a6e4605:mac_messages_mcp/messages.py)
# fmt: off

def _connect_sqlite_readonly(path: str) -> sqlite3.Connection:
    """Open a local SQLite database without write, journal, or creation access."""
    uri = f"{Path(path).expanduser().resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def escape_applescript(value: str) -> str:
    """Escape a string for safe interpolation into an AppleScript double-quoted string.

    Escapes backslashes first (so subsequent escapes aren't double-escaped), then
    double quotes, then control characters that would otherwise terminate the
    AppleScript string literal or break the script (newlines, carriage returns,
    tabs). Also handles Unicode line/paragraph separators (U+2028 / U+2029),
    which AppleScript treats as line terminators.
    """
    if value is None:
        return ""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\u2028", "\\n")
        .replace("\u2029", "\\n")
    )


def extract_body_from_attributed(attributed_body):
    """
    Extract message content from attributedBody binary data.

    The attributedBody column contains an Apple typedstream blob
    (NSArchiver serialization of NSMutableAttributedString).  The string
    content is stored after the first ``NSString`` class marker followed
    by a 5-byte header (``\\x01 <byte> \\x84 \\x01 +``) and a
    variable-length integer encoding the byte length of the UTF-8 text.

    Length encoding (first byte after the header):
        < 0x80  — the byte *is* the length.
        0x81    — next 2 bytes (little-endian) are the length.
        0x82    — next 3 bytes (little-endian) are the length.
        0x83    — next 4 bytes (little-endian) are the length.
    """
    if attributed_body is None:
        return None

    try:
        # Locate the first NSString class reference in the blob.
        marker = b"NSString"
        idx = attributed_body.find(marker)
        if idx < 0:
            return None

        # Skip past: NSString (8) + \x01 + <byte> + \x84 + \x01 + '+' = 5 bytes
        pos = idx + len(marker) + 5

        if pos >= len(attributed_body):
            return None

        # Read the variable-length integer for the text byte count.
        length_byte = attributed_body[pos]
        pos += 1

        if length_byte < 0x80:
            text_length = length_byte
        elif length_byte == 0x81:
            if pos + 2 > len(attributed_body):
                return None
            text_length = attributed_body[pos] | (attributed_body[pos + 1] << 8)
            pos += 2
        elif length_byte == 0x82:
            if pos + 3 > len(attributed_body):
                return None
            text_length = (
                attributed_body[pos]
                | (attributed_body[pos + 1] << 8)
                | (attributed_body[pos + 2] << 16)
            )
            pos += 3
        elif length_byte == 0x83:
            if pos + 4 > len(attributed_body):
                return None
            text_length = (
                attributed_body[pos]
                | (attributed_body[pos + 1] << 8)
                | (attributed_body[pos + 2] << 16)
                | (attributed_body[pos + 3] << 24)
            )
            pos += 4
        else:
            return None

        if pos + text_length > len(attributed_body):
            return None

        return attributed_body[pos : pos + text_length].decode(
            "utf-8", errors="replace"
        )

    except Exception:
        return None


def get_messages_db_path() -> str:
    """Get the path to the Messages database."""
    home_dir = os.path.expanduser("~")
    return os.path.join(home_dir, "Library/Messages/chat.db")


def query_messages_db(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Query the Messages database and return results as a list of dictionaries."""
    try:
        db_path = get_messages_db_path()

        # Check if the database file exists and is accessible
        if not os.path.exists(db_path):
            return [{"error": f"Messages database not found at {db_path}"}]

        # Try to connect to the database
        try:
            conn = _connect_sqlite_readonly(db_path)
        except sqlite3.OperationalError as e:
            return [
                {
                    "error": f"Cannot access Messages database. Please grant Full Disk Access permission to your terminal application in System Preferences > Security & Privacy > Privacy > Full Disk Access. Error: {str(e)} PLEASE TELL THE USER TO GRANT FULL DISK ACCESS TO THE TERMINAL APPLICATION(CURSOR, TERMINAL, CLAUDE, ETC.) AND RESTART THE APPLICATION. DO NOT RETRY UNTIL NEXT MESSAGE."
                }
            ]

        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    except Exception as e:
        return [{"error": str(e)}]


def normalize_phone_number(phone: str) -> str:
    """
    Normalize a phone number by removing all non-digit characters.
    """
    if not phone:
        return ""
    return "".join(c for c in phone if c.isdigit())


def _get_phone_formats(recipient: str) -> List[str]:
    """
    Get different phone recipient formats. Assumes the recipient given has already been normalized.

    Args:
        recipient: Normalized phone recipient

    Returns:
        List of phone recipients in various formats
    """
    # Start with the normalized input
    formats_to_try = [recipient]

    # For US recipients, try with and without country code
    if recipient.startswith("1") and len(recipient) > 10:
        # Try without the country code
        formats_to_try.append(recipient[1:])
        formats_to_try.append("+" + recipient)

    elif len(recipient) == 10:
        # Try with the country code
        formats_to_try.append("1" + recipient)
        formats_to_try.append("+1" + recipient)

    return formats_to_try


APPLE_EPOCH_OFFSET = 978307200  # seconds between the unix epoch and 2001-01-01
OBSERVATION_TIMEOUT_SECONDS = 10.0
OBSERVATION_POLL_SECONDS = 0.5


class DeliveryService(Enum):
    IMESSAGE = "iMessage"
    SMS = "SMS"


class AttemptState(Enum):
    DELIVERED = "delivered"
    SENT_UNCONFIRMED = "sent-unconfirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


class CorrelationConfidence(Enum):
    EXACT = "exact"
    NONE = "none"


class OutcomeReason(Enum):
    DATABASE_UNAVAILABLE = "database-unavailable"
    MESSAGE_NOT_CORRELATED = "message-not-correlated"
    SEND_STATE_TIMEOUT = "send-state-timeout"
    DELIVERY_TIMEOUT = "delivery-timeout"


@dataclass(frozen=True)
class AttemptOutcome:
    """Redaction-safe internal result for one transport attempt."""

    state: AttemptState
    service: DeliveryService
    correlation: CorrelationConfidence
    reason: Optional[OutcomeReason] = None
    fallback_permitted: bool = False

    def __post_init__(self) -> None:
        if self.fallback_permitted and not (
            self.state is AttemptState.FAILED
            and self.service is DeliveryService.IMESSAGE
            and self.correlation is CorrelationConfidence.EXACT
        ):
            raise ValueError("fallback requires an exactly correlated iMessage failure")
        if (
            self.state is AttemptState.FAILED
            and self.service is DeliveryService.IMESSAGE
            and self.correlation is CorrelationConfidence.EXACT
            and not self.fallback_permitted
        ):
            raise ValueError("an exactly correlated iMessage failure requires fallback")


def _outcome(
    state: AttemptState,
    service: DeliveryService,
    *,
    correlation: CorrelationConfidence,
    reason: Optional[OutcomeReason] = None,
) -> AttemptOutcome:
    return AttemptOutcome(
        state=state,
        service=service,
        correlation=correlation,
        reason=reason,
        fallback_permitted=(
            state is AttemptState.FAILED
            and service is DeliveryService.IMESSAGE
            and correlation is CorrelationConfidence.EXACT
        ),
    )


def _candidate_handles(recipient: str) -> List[str]:
    """
    Build the set of handle ids the Messages database might have recorded
    for this recipient (email as-is; phone numbers in several formats).
    """
    if "@" in recipient:
        return [recipient]
    digits = normalize_phone_number(recipient)
    candidates = {recipient.strip()}
    if digits:
        candidates.add(digits)
        candidates.add("+" + digits)
        candidates.update(_get_phone_formats(digits))
    return [c for c in candidates if c]


def _row_text(row: Dict[str, Any]) -> Optional[str]:
    """Best-effort plain text for a message row (`text` column, else attributedBody)."""
    text = row.get("text")
    if text:
        return text
    return extract_body_from_attributed(row.get("attributedBody"))


def _database_service_matches(value: object, expected: DeliveryService) -> bool:
    if not isinstance(value, str):
        return False
    if expected is DeliveryService.IMESSAGE:
        return value in {"iMessage", "iMessageLite"}
    return value in {"SMS", "RCS"}


def _verify_send_in_db(
    recipient: str,
    sent_after_unix: float,
    message_text: str,
    service: DeliveryService,
    timeout: float = OBSERVATION_TIMEOUT_SECONDS,
) -> AttemptOutcome:
    """
    Poll the Messages database for the outbound message to `recipient`
    recorded after `sent_after_unix`.

    The AppleScript `send` command returns without error even when the
    message later fails (e.g. error 22 for an unroutable handle, or a
    recipient who deregistered from iMessage), so the AppleScript result
    alone cannot confirm a send. The authoritative outcome lives in
    chat.db's message.error / message.is_sent columns, which are populated
    within a second or two of the attempt.

    Correlation requires the exact body, recipient variant, attempt start time, and
    expected transport. Once found, the row id is pinned for the rest of the attempt.
    A newer recipient row or a body mismatch can never resolve the attempt.
    """
    apple_ns = int((sent_after_unix - APPLE_EPOCH_OFFSET - 1) * 1_000_000_000)
    handles = _candidate_handles(recipient)

    def _candidate_rows() -> Union[List[Dict[str, Any]], None]:
        placeholders = ", ".join("?" for _ in handles)
        query = f"""
            SELECT m.ROWID AS row_id, m.guid, m.error AS send_error,
                   m.is_sent, m.is_delivered, m.service, m.text,
                   m.attributedBody, h.id AS handle
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.is_from_me = 1
              AND h.id IN ({placeholders})
              AND m.date >= ?
            ORDER BY m.date ASC
            LIMIT 20
        """
        results = query_messages_db(query, tuple(handles) + (apple_ns,))
        if results and "error" in results[0]:
            return None
        return results

    def _pinned_row(row_id: int) -> Union[Dict[str, Any], None, bool]:
        results = query_messages_db(
            """
            SELECT m.ROWID AS row_id, m.guid, m.error AS send_error,
                   m.is_sent, m.is_delivered, m.service, m.text,
                   m.attributedBody, h.id AS handle
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.ROWID = ? AND m.is_from_me = 1
            LIMIT 1
            """,
            (row_id,),
        )
        if results and "error" in results[0]:
            return False
        if not results:
            return None
        return results[0]

    deadline = time.monotonic() + timeout
    pinned_row_id = None
    saw_sent = False
    while time.monotonic() < deadline:
        if pinned_row_id is None:
            rows = _candidate_rows()
            if rows is None:
                return _outcome(
                    AttemptState.UNKNOWN,
                    service,
                    correlation=CorrelationConfidence.NONE,
                    reason=OutcomeReason.DATABASE_UNAVAILABLE,
                )
            exact_rows = [
                row
                for row in rows
                if _row_text(row) == message_text
                and row.get("handle") in handles
                and _database_service_matches(row.get("service"), service)
            ]
            if len(exact_rows) > 1:
                return _outcome(
                    AttemptState.UNKNOWN,
                    service,
                    correlation=CorrelationConfidence.NONE,
                    reason=OutcomeReason.MESSAGE_NOT_CORRELATED,
                )
            row = exact_rows[0] if exact_rows else None
            if row is not None:
                pinned_row_id = row.get("row_id")
                if not isinstance(pinned_row_id, int) or isinstance(
                    pinned_row_id, bool
                ):
                    return _outcome(
                        AttemptState.UNKNOWN,
                        service,
                        correlation=CorrelationConfidence.NONE,
                        reason=OutcomeReason.MESSAGE_NOT_CORRELATED,
                    )
        else:
            row = _pinned_row(pinned_row_id)
            if row is False:
                return _outcome(
                    AttemptState.UNKNOWN,
                    service,
                    correlation=CorrelationConfidence.EXACT,
                    reason=OutcomeReason.DATABASE_UNAVAILABLE,
                )
            if row is None:
                return _outcome(
                    AttemptState.UNKNOWN,
                    service,
                    correlation=CorrelationConfidence.NONE,
                    reason=OutcomeReason.MESSAGE_NOT_CORRELATED,
                )

        if row is not None:
            if (
                _row_text(row) != message_text
                or row.get("handle") not in handles
                or not _database_service_matches(row.get("service"), service)
            ):
                return _outcome(
                    AttemptState.UNKNOWN,
                    service,
                    correlation=CorrelationConfidence.NONE,
                    reason=OutcomeReason.MESSAGE_NOT_CORRELATED,
                )
            if row.get("is_delivered"):
                return _outcome(
                    AttemptState.DELIVERED,
                    service,
                    correlation=CorrelationConfidence.EXACT,
                )
            if row.get("send_error"):
                return _outcome(
                    AttemptState.FAILED,
                    service,
                    correlation=CorrelationConfidence.EXACT,
                )
            if row.get("is_sent"):
                saw_sent = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(OBSERVATION_POLL_SECONDS, remaining))

    if pinned_row_id is None:
        return _outcome(
            AttemptState.UNKNOWN,
            service,
            correlation=CorrelationConfidence.NONE,
            reason=OutcomeReason.MESSAGE_NOT_CORRELATED,
        )
    if saw_sent:
        return _outcome(
            AttemptState.SENT_UNCONFIRMED,
            service,
            correlation=CorrelationConfidence.EXACT,
            reason=OutcomeReason.DELIVERY_TIMEOUT,
        )
    return _outcome(
        AttemptState.UNKNOWN,
        service,
        correlation=CorrelationConfidence.EXACT,
        reason=OutcomeReason.SEND_STATE_TIMEOUT,
    )


def _report_send_outcome(
    recipient: str,
    display_name: str,
    service: DeliveryService,
    sent_after_unix: float,
    message_text: str,
) -> AttemptOutcome:
    """
    Return one structured, redaction-safe database observation outcome.
    """
    del display_name
    return _verify_send_in_db(recipient, sent_after_unix, message_text, service)


def _send_message_sms(
    recipient: str, message: str, contact_name: str = None
) -> Union[AttemptOutcome, str]:
    """
    Send message via SMS/RCS using AppleScript.

    Args:
        recipient: Phone number to send to
        message: Message content
        contact_name: Optional contact name for display

    Returns:
        Success or error message
    """
    safe_message = escape_applescript(message)
    safe_recipient = escape_applescript(recipient)

    script = f"""
    tell application "Messages"
        try
            -- Try to find SMS service
            set smsService to first account whose service type = SMS and enabled is true
            
            -- Send message via SMS
            send "{safe_message}" to participant "{safe_recipient}" of smsService
            
            -- Wait briefly to check for immediate errors
            delay 1
            
            return "success"
        on error
            return "error:send_failed:SMS"
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        if result == "error:send_failed:SMS":
            return _outcome(
                AttemptState.FAILED,
                DeliveryService.SMS,
                correlation=CorrelationConfidence.NONE,
            )
        if result.startswith("Error: AppleScript"):
            return result
        elif result.strip() == "success":
            display_name = contact_name if contact_name else recipient
            return _report_send_outcome(
                recipient, display_name, DeliveryService.SMS, sent_at, message
            )
        else:
            return "Unknown SMS result"
    except Exception:
        return "Error: AppleScript automation failed"


def _send_message_direct(
    recipient: str, message: str, contact_name: str = None, group_chat: bool = False
) -> Union[AttemptOutcome, str]:
    """
    Enhanced direct AppleScript method for sending messages with SMS/RCS fallback.

    This function implements automatic fallback from iMessage to SMS/RCS when:
    1. Recipient doesn't have iMessage
    2. iMessage delivery fails
    3. iMessage service is unavailable

    Args:
        recipient: Phone number or email
        message: Message content
        contact_name: Optional contact name for display
        group_chat: Whether this is a group chat

    Returns:
        Success or error message with service type used
    """
    # Clean the inputs for AppleScript using the central helper, which also
    # handles newlines, tabs, and Unicode line/paragraph separators.
    safe_message = escape_applescript(message)
    safe_recipient = escape_applescript(recipient)

    # For group chats, stick to iMessage only (SMS doesn't support group chats well)
    if group_chat:
        script = f"""
        tell application "Messages"
            try
                -- Try to get the existing chat by its full id (e.g. "iMessage;+;chat123…").
                -- `chat id "…"` looks up by guid; plain `chat "…"` looks up by display
                -- name and fails on guid-style identifiers with -1728 "Can't get chat".
                set targetChat to chat id "{safe_recipient}"
                
                -- Send the message
                send "{safe_message}" to targetChat
                
                -- Wait briefly to check for immediate errors
                delay 1
                
                -- Return success
                return "success"
            on error errMsg
                -- Chat method failed
                return "error:" & errMsg
            end try
        end tell
        """

        try:
            result = run_applescript(script)
            if result.startswith("error:"):
                return f"Error sending group message: {result[6:]}"
            elif result.strip() == "success":
                display_name = contact_name if contact_name else recipient
                return f"Group message sent successfully to {display_name}"
            else:
                return f"Unknown group message result: {result}"
        except Exception as e:
            return f"Error sending group message: {str(e)}"

    # For individual messages, try iMessage first. A synchronous AppleScript
    # failure immediately invokes the SMS-only helper inside this authorized call.
    # Keeping the attempts separate gives each transport its own start time.
    script = f"""
    tell application "Messages"
        try
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to participant "{safe_recipient}" of targetService
            send "{safe_message}" to targetBuddy
            delay 2
            return "success:iMessage"
        on error
            return "error:send_failed:iMessage"
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        display_name = contact_name if contact_name else recipient

        if result == "error:send_failed:iMessage":
            return _send_message_sms(recipient, message, contact_name)
        if result.startswith("Error: AppleScript"):
            return result
        if result.strip() == "success:iMessage":
            return _report_send_outcome(
                recipient,
                display_name,
                DeliveryService.IMESSAGE,
                sent_at,
                message,
            )
        return "Unknown result"
    except Exception:
        return "Error: AppleScript automation failed"

# fmt: on
# END ADAPTED UPSTREAM SUBSET
