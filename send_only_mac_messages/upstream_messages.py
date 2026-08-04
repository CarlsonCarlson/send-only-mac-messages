"""Send and delivery subset adapted from upstream Mac Messages MCP.

Upstream provenance:
- SMS/RCS fallback: f77be9eb18d38ba1e3d0ea35721c45d4781344b9
- Delivery verification: 1a8f309 (as merged in a6e460526096996ea04ab880e519e3ae627b0dc3)

Most marked function bodies come from ``mac_messages_mcp/messages.py`` at
``a6e4605``. The local transport adapter preserves this fork's stdin-only payload
boundary and redacts subprocess errors. The transient observer intentionally keeps
polling after ``is_sent`` and preserves fixed unverified reasons per ADR-0004.
"""

# isort: skip_file
# mypy: ignore-errors

import os
import sqlite3
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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


class _ObservationFailure(Enum):
    DATABASE_UNAVAILABLE = "database-unavailable"


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


def _verify_send_in_db(
    recipient: str,
    sent_after_unix: float,
    message_text: Optional[str] = None,
    timeout: float = 6.0,
) -> Optional[Dict[str, Any]]:
    """
    Poll the Messages database for the outbound message to `recipient`
    recorded after `sent_after_unix`.

    The AppleScript `send` command returns without error even when the
    message later fails (e.g. error 22 for an unroutable handle, or a
    recipient who deregistered from iMessage), so the AppleScript result
    alone cannot confirm a send. The authoritative outcome lives in
    chat.db's message.error / message.is_sent columns, which are populated
    within a second or two of the attempt.

    `sent_after_unix` alone is not a reliable correlation key: two sends to
    the same handle close together (e.g. rapid-fire tool calls) can both be
    "the latest row after time X" from either call's point of view, so a
    plain `ORDER BY date DESC LIMIT 1` can report the outcome of the wrong
    message. When `message_text` is given, matching rows are additionally
    filtered by exact body match (decoding attributedBody when `text` is
    NULL) so each call correlates to *its own* send rather than whichever
    row happens to be newest. If nothing matches the body (e.g. Messages
    re-encoded the text, or the row only has an attachment), we fall back to
    the plain latest-row behavior rather than reporting a false negative.

    Returns the terminal row or last row observed as sent. If no sent row resolves,
    returns a typed database-unavailable state or None for message-not-correlated.
    """
    apple_ns = int((sent_after_unix - APPLE_EPOCH_OFFSET - 1) * 1_000_000_000)
    database_unavailable = False

    def _matching_rows(handles: List[str]) -> List[Dict[str, Any]]:
        nonlocal database_unavailable
        placeholders = ", ".join("?" for _ in handles)
        # m.error is aliased to send_error so a real row can't be mistaken
        # for query_messages_db's {"error": ...} failure dict.
        query = f"""
            SELECT m.guid, m.error AS send_error, m.is_sent, m.is_delivered,
                   m.service, m.text, m.attributedBody
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.is_from_me = 1
              AND h.id IN ({placeholders})
              AND m.date >= ?
            ORDER BY m.date DESC
            LIMIT 10
        """
        results = query_messages_db(query, tuple(handles) + (apple_ns,))
        if results and "guid" in results[0]:
            return results
        if results and "error" in results[0]:
            database_unavailable = True
        return []

    def _best_row(handles: List[str]) -> Optional[Dict[str, Any]]:
        rows = _matching_rows(handles)
        if not rows:
            return None
        if message_text is not None:
            for row in rows:
                if _row_text(row) == message_text:
                    return row
            # No row's body matched this send -- fall back to the newest row
            # rather than reporting nothing (e.g. attachment-only messages,
            # or Messages normalizing the text on write).
        return rows[0]

    exact = [recipient.strip()]
    variants = _candidate_handles(recipient)
    deadline = time.time() + timeout
    row = None
    last_sent_row = None
    while time.time() < deadline:
        # Prefer the exact handle the send targeted; only widen to format
        # variants when the exact handle has no row (Messages sometimes
        # records the handle in a different format than it was given).
        row = _best_row(exact) or _best_row(variants)
        if row is not None:
            # A sent flag can precede the delivery flag, so keep polling until
            # delivery, failure, or the observation window ends.
            if row.get("send_error") or row.get("is_delivered"):
                return row
            if row.get("is_sent"):
                last_sent_row = row
        time.sleep(0.5)
    if last_sent_row is not None:
        return last_sent_row
    if database_unavailable:
        return _ObservationFailure.DATABASE_UNAVAILABLE
    return None


def _report_send_outcome(
    recipient: str,
    display_name: str,
    service: str,
    sent_after_unix: float,
    message_text: Optional[str] = None,
) -> str:
    """
    Turn the database verification result into the string returned to the
    caller. Never claims success for a message the database says failed.
    """
    row = _verify_send_in_db(recipient, sent_after_unix, message_text)
    if row is None:
        return (
            f"Message to {display_name} was handed to Messages.app via {service}, "
            "but delivery could not be verified because no matching message row "
            "appeared during the observation window."
        )
    if row is _ObservationFailure.DATABASE_UNAVAILABLE:
        return (
            f"Message to {display_name} was handed to Messages.app via {service}, "
            "but delivery could not be verified because the Messages database "
            "was unavailable."
        )
    actual_service = row.get("service") or service
    if row.get("send_error"):
        return (
            f"Error: message to {display_name} failed to send "
            f"(Messages error code {row['send_error']}, service {actual_service}). "
            f"The recipient may not be reachable via {actual_service}."
        )
    status = "delivered" if row.get("is_delivered") else "sent"
    return f"Message {status} successfully via {actual_service} to {display_name}"


def _send_message_sms(recipient: str, message: str, contact_name: str = None) -> str:
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
        on error errMsg
            return "error:" & errMsg
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        if result.startswith("error:"):
            return f"Error sending SMS: {result[6:]}"
        elif result.strip() == "success":
            display_name = contact_name if contact_name else recipient
            return _report_send_outcome(
                recipient, display_name, "SMS", sent_at, message
            )
        else:
            return f"Unknown SMS result: {result}"
    except Exception as e:
        return f"Error sending SMS: {str(e)}"


def _send_message_direct(
    recipient: str, message: str, contact_name: str = None, group_chat: bool = False
) -> str:
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

    # For individual messages, try iMessage first with automatic SMS fallback
    # Enhanced AppleScript with built-in fallback logic
    script = f"""
    tell application "Messages"
        try
            -- First, try iMessage
            set targetService to 1st service whose service type = iMessage
            
            try
                -- Try to get the existing participant if possible
                set targetBuddy to participant "{safe_recipient}" of targetService
                
                -- Send the message via iMessage
                send "{safe_message}" to targetBuddy
                
                -- Wait briefly to check for immediate errors
                delay 2
                
                -- Return success with service type
                return "success:iMessage"
            on error iMessageErr
                -- iMessage failed, try SMS fallback if recipient looks like a phone number
                try
                    -- Check if recipient looks like a phone number (contains digits)
                    if "{safe_recipient}" contains "0" or "{safe_recipient}" contains "1" or "{safe_recipient}" contains "2" or "{safe_recipient}" contains "3" or "{safe_recipient}" contains "4" or "{safe_recipient}" contains "5" or "{safe_recipient}" contains "6" or "{safe_recipient}" contains "7" or "{safe_recipient}" contains "8" or "{safe_recipient}" contains "9" then
                        -- Try SMS service
                        set smsService to first account whose service type = SMS and enabled is true
                        send "{safe_message}" to participant "{safe_recipient}" of smsService
                        
                        -- Wait briefly to check for immediate errors
                        delay 2
                        
                        return "success:SMS"
                    else
                        -- Not a phone number, can't use SMS
                        return "error:iMessage failed and SMS not available for email addresses - " & iMessageErr
                    end if
                on error smsErr
                    -- Both iMessage and SMS failed
                    return "error:Both iMessage and SMS failed - iMessage: " & iMessageErr & " SMS: " & smsErr
                end try
            end try
        on error generalErr
            return "error:" & generalErr
        end try
    end tell
    """

    try:
        sent_at = time.time()
        result = run_applescript(script)
        display_name = contact_name if contact_name else recipient

        if result.startswith("error:"):
            return f"Error sending message: {result[6:]}"
        elif result.strip() == "success:iMessage":
            return _report_send_outcome(
                recipient, display_name, "iMessage", sent_at, message
            )
        elif result.strip() == "success:SMS":
            return _report_send_outcome(
                recipient, display_name, "SMS", sent_at, message
            )
        elif result.strip() == "success":
            return _report_send_outcome(
                recipient, display_name, "iMessage", sent_at, message
            )
        else:
            return f"Unknown result: {result}"
    except Exception as e:
        return f"Error sending message: {str(e)}"

# fmt: on
# END ADAPTED UPSTREAM SUBSET
