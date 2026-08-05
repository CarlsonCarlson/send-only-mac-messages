"""Send and delivery subset adapted from upstream Mac Messages MCP.

Upstream provenance:
- SMS/RCS fallback: f77be9eb18d38ba1e3d0ea35721c45d4781344b9
- Delivery verification: 1a8f309 (as merged in a6e460526096996ea04ab880e519e3ae627b0dc3)

Most marked function bodies began in ``mac_messages_mcp/messages.py`` at ``a6e4605``.
The local transport adapter preserves this fork's stdin-only payload boundary and
redacts subprocess errors. ADR-0005 replaces the heuristic observer result with an
exact-attempt structured outcome; ADR-0006 permits the bounded SMS/RCS continuation
only after a synchronous AppleScript failure.
"""

from __future__ import annotations

# isort: skip_file
# mypy: ignore-errors

import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
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


OBSERVATION_TIMEOUT_SECONDS = 10.0
OBSERVATION_POLL_INTERVAL_SECONDS = 0.5


class AttemptState(Enum):
    DELIVERED = "delivered"
    SENT_UNCONFIRMED = "sent-unconfirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"
    TIMEOUT = "timeout"
    AUTOMATION_FAILED = "automation-failed"
    UNEXPECTED_RESULT = "unexpected-result"


class CorrelationConfidence(Enum):
    EXACT = "exact"
    NONE = "none"


class MessageTransport(str, Enum):
    IMESSAGE = "iMessage"
    IMESSAGE_LITE = "iMessageLite"
    SMS = "SMS"
    RCS = "RCS"

    @property
    def public_service(self) -> str:
        if self in {MessageTransport.SMS, MessageTransport.RCS}:
            return "SMS"
        return "iMessage"

    @property
    def compatible_database_values(self) -> tuple[str, ...]:
        if self.public_service == "SMS":
            return (MessageTransport.SMS.value, MessageTransport.RCS.value)
        return (
            MessageTransport.IMESSAGE.value,
            MessageTransport.IMESSAGE_LITE.value,
        )

    @classmethod
    def from_database(
        cls,
        value: object,
        *,
        fallback: MessageTransport,
    ) -> MessageTransport:
        try:
            return cls(value)
        except (TypeError, ValueError):
            return fallback


class ObservationReason(Enum):
    DATABASE_UNAVAILABLE = "database-unavailable"
    MESSAGE_NOT_CORRELATED = "message-not-correlated"
    SEND_STATE_TIMEOUT = "send-state-timeout"
    DELIVERY_TIMEOUT = "delivery-timeout"
    APPLESCRIPT_TIMEOUT = "applescript-timeout"
    AUTOMATION_FAILED = "automation-failed"
    UNEXPECTED_RESULT = "unexpected-result"


@dataclass(frozen=True)
class SendAttemptOutcome:
    state: AttemptState
    actual_transport: MessageTransport
    correlation_confidence: CorrelationConfidence
    reason: Optional[ObservationReason] = None
    fallback_permitted: bool = False


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
    timeout: float = OBSERVATION_TIMEOUT_SECONDS,
    *,
    service: MessageTransport = MessageTransport.IMESSAGE,
    poll_interval: float = OBSERVATION_POLL_INTERVAL_SECONDS,
) -> SendAttemptOutcome:
    """
    Poll the Messages database for the outbound message to `recipient`
    recorded after `sent_after_unix`.

    The AppleScript `send` command returns without error even when the
    message later fails (e.g. error 22 for an unroutable handle, or a
    recipient who deregistered from iMessage), so the AppleScript result
    alone cannot confirm a send. Status evidence appears in chat.db's
    message.error / message.is_sent / message.is_delivered columns, whose
    values can change asynchronously during the observation window.

    `sent_after_unix` alone is not a reliable correlation key: two sends to
    the same handle close together (e.g. rapid-fire tool calls) can both be
    "the latest row after time X" from either call's point of view, so a
    plain `ORDER BY date DESC LIMIT 1` can report the outcome of the wrong
    message. Matching rows are therefore filtered by exact body match
    (decoding attributedBody when `text` is NULL), expected transport, and
    recipient variants. If no body matches, the outcome remains unknown.

    Returns one structured outcome. Only an exact-body match is authoritative, and
    once found its row id is pinned for the remainder of this observation window.
    """
    apple_ns = int((sent_after_unix - APPLE_EPOCH_OFFSET) * 1_000_000_000)
    database_unavailable = False
    compatible_services = service.compatible_database_values

    def _query_rows(
        handles: List[str], pinned_row_id: Optional[int]
    ) -> List[Dict[str, Any]]:
        nonlocal database_unavailable
        # m.error is aliased to send_error so a real row can't be mistaken
        # for query_messages_db's {"error": ...} failure dict.
        if pinned_row_id is not None:
            query = """
                SELECT m.ROWID AS row_id, m.guid,
                       m.error AS send_error, m.is_sent, m.is_delivered,
                       m.service, m.text, m.attributedBody
                FROM message m
                WHERE m.ROWID = ? AND m.is_from_me = 1
                LIMIT 1
            """
            params: tuple[Any, ...] = (pinned_row_id,)
        else:
            handle_placeholders = ", ".join("?" for _ in handles)
            service_placeholders = ", ".join("?" for _ in compatible_services)
            query = f"""
                SELECT m.ROWID AS row_id, m.guid,
                       m.error AS send_error, m.is_sent, m.is_delivered,
                       m.service, m.text, m.attributedBody
                FROM message m
                JOIN handle h ON m.handle_id = h.ROWID
                WHERE m.is_from_me = 1
                  AND h.id IN ({handle_placeholders})
                  AND m.service IN ({service_placeholders})
                  AND m.date >= ?
                ORDER BY m.date DESC
                LIMIT 10
            """
            params = tuple(handles) + compatible_services + (apple_ns,)
        results = query_messages_db(query, params)
        database_unavailable = bool(results and "error" in results[0])
        if results and "row_id" in results[0]:
            return results
        return []

    variants = _candidate_handles(recipient)
    deadline = time.time() + timeout
    pinned_row_id: Optional[int] = None
    pinned_row_seen = False
    last_sent_transport: Optional[MessageTransport] = None
    last_failed_transport: Optional[MessageTransport] = None
    while time.time() < deadline:
        rows = _query_rows(variants, pinned_row_id)
        row = rows[0] if pinned_row_id is not None and rows else None
        if pinned_row_id is None and message_text is not None:
            row = next((row for row in rows if _row_text(row) == message_text), None)
            if row is not None:
                pinned_row_id = row.get("row_id")
        if row is not None:
            pinned_row_seen = True
            actual_transport = MessageTransport.from_database(
                row.get("service"),
                fallback=service,
            )
            # Database flags can change asynchronously. Delivery is definitive,
            # while an observed error is not safe evidence for another submission.
            if row.get("is_delivered"):
                return SendAttemptOutcome(
                    state=AttemptState.DELIVERED,
                    actual_transport=actual_transport,
                    correlation_confidence=CorrelationConfidence.EXACT,
                )
            if row.get("send_error"):
                last_failed_transport = actual_transport
            else:
                last_failed_transport = None
                if row.get("is_sent"):
                    last_sent_transport = actual_transport
        time.sleep(poll_interval)
    if last_failed_transport is not None:
        return SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=last_failed_transport,
            correlation_confidence=CorrelationConfidence.EXACT,
        )
    if last_sent_transport is not None:
        return SendAttemptOutcome(
            state=AttemptState.SENT_UNCONFIRMED,
            actual_transport=last_sent_transport,
            correlation_confidence=CorrelationConfidence.EXACT,
            reason=ObservationReason.DELIVERY_TIMEOUT,
        )
    if database_unavailable:
        return SendAttemptOutcome(
            state=AttemptState.UNKNOWN,
            actual_transport=service,
            correlation_confidence=(
                CorrelationConfidence.EXACT
                if pinned_row_seen
                else CorrelationConfidence.NONE
            ),
            reason=ObservationReason.DATABASE_UNAVAILABLE,
        )
    if pinned_row_seen:
        return SendAttemptOutcome(
            state=AttemptState.UNKNOWN,
            actual_transport=service,
            correlation_confidence=CorrelationConfidence.EXACT,
            reason=ObservationReason.SEND_STATE_TIMEOUT,
        )
    return SendAttemptOutcome(
        state=AttemptState.UNKNOWN,
        actual_transport=service,
        correlation_confidence=CorrelationConfidence.NONE,
        reason=ObservationReason.MESSAGE_NOT_CORRELATED,
    )


def _script_result_outcome(
    result: str,
    service: MessageTransport,
) -> Optional[SendAttemptOutcome]:
    """Return a structured non-success result, or ``None`` for script success."""
    if result.strip() == "success":
        return None
    if result.startswith("error:"):
        return SendAttemptOutcome(
            state=AttemptState.FAILED,
            actual_transport=service,
            correlation_confidence=CorrelationConfidence.NONE,
            fallback_permitted=service.public_service == "iMessage",
        )
    if result.startswith("Error: AppleScript timed out"):
        return SendAttemptOutcome(
            state=AttemptState.TIMEOUT,
            actual_transport=service,
            correlation_confidence=CorrelationConfidence.NONE,
            reason=ObservationReason.APPLESCRIPT_TIMEOUT,
        )
    if result == "Error: AppleScript automation failed":
        return SendAttemptOutcome(
            state=AttemptState.AUTOMATION_FAILED,
            actual_transport=service,
            correlation_confidence=CorrelationConfidence.NONE,
            reason=ObservationReason.AUTOMATION_FAILED,
        )
    return SendAttemptOutcome(
        state=AttemptState.UNEXPECTED_RESULT,
        actual_transport=service,
        correlation_confidence=CorrelationConfidence.NONE,
        reason=ObservationReason.UNEXPECTED_RESULT,
    )


def _execute_transport_attempt(
    recipient: str,
    message: str,
    service: MessageTransport,
    script: str,
) -> SendAttemptOutcome:
    """Execute and observe one transport submission without retaining attempt state."""
    try:
        sent_at = time.time()
        result = run_applescript(script)
        script_outcome = _script_result_outcome(
            result,
            service,
        )
        if script_outcome is not None:
            return script_outcome
        return _verify_send_in_db(
            recipient,
            sent_at,
            message,
            service=service,
        )
    except Exception:
        return SendAttemptOutcome(
            state=AttemptState.UNEXPECTED_RESULT,
            actual_transport=service,
            correlation_confidence=CorrelationConfidence.NONE,
            reason=ObservationReason.UNEXPECTED_RESULT,
        )


def _send_message_sms(recipient: str, message: str) -> SendAttemptOutcome:
    """
    Send message via SMS/RCS using AppleScript.

    Args:
        recipient: Phone number to send to
        message: Message content

    Returns:
        Structured final outcome for the one SMS/RCS attempt.
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

    return _execute_transport_attempt(
        recipient,
        message,
        MessageTransport.SMS,
        script,
    )


def _send_message_direct(recipient: str, message: str) -> SendAttemptOutcome:
    """
    Submit one iMessage attempt and return its structured observed outcome.

    The outer send-only adapter owns the one permitted SMS continuation. Keeping the
    transports in separate AppleScript processes gives each attempt its own start
    time and prevents more than one SMS submission.

    Args:
        recipient: Phone number or email
        message: Message content

    Returns:
        Structured outcome for the iMessage attempt.
    """
    # Clean the inputs for AppleScript using the central helper, which also
    # handles newlines, tabs, and Unicode line/paragraph separators.
    safe_message = escape_applescript(message)
    safe_recipient = escape_applescript(recipient)

    script = f"""
    tell application "Messages"
        try
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to participant "{safe_recipient}" of targetService
            send "{safe_message}" to targetBuddy
            delay 2
            return "success"
        on error errMsg
            return "error:" & errMsg
        end try
    end tell
    """

    return _execute_transport_attempt(
        recipient,
        message,
        MessageTransport.IMESSAGE,
        script,
    )

# fmt: on
# END ADAPTED UPSTREAM SUBSET
