#!/usr/bin/env python3
"""Read-only JSONL collector for one exact outgoing iMessage attempt.

PROTOTYPE: this file never sends and never authorizes SMS.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

APPLE_EPOCH_OFFSET = 978_307_200
POLL_SECONDS = 0.5


def emit(phase: str, **fields: object) -> None:
    print(json.dumps({"phase": phase, **fields}, sort_keys=True), flush=True)


def digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def candidate_handles(recipient: str) -> tuple[str, ...]:
    number = digits(recipient)
    values = {recipient.strip(), number, f"+{number}"}
    if len(number) == 11 and number.startswith("1"):
        values.update({number[1:], f"+{number}", number})
    elif len(number) == 10:
        values.update({f"1{number}", f"+1{number}"})
    return tuple(sorted(value for value in values if value))


def attributed_text(blob: object) -> str | None:
    if not isinstance(blob, bytes):
        return None
    marker = b"NSString"
    marker_index = blob.find(marker)
    if marker_index < 0:
        return None
    position = marker_index + len(marker) + 5
    if position >= len(blob):
        return None
    length_byte = blob[position]
    position += 1
    if length_byte < 0x80:
        length = length_byte
    elif length_byte in {0x81, 0x82, 0x83}:
        width = length_byte - 0x7F
        if position + width > len(blob):
            return None
        length = int.from_bytes(blob[position : position + width], "little")
        position += width
    else:
        return None
    if position + length > len(blob):
        return None
    return blob[position : position + length].decode("utf-8", errors="replace")


def row_text(row: sqlite3.Row) -> str | None:
    return row["text"] or attributed_text(row["attributedBody"])


def query_candidates(
    connection: sqlite3.Connection,
    recipient: str,
    sent_after_unix: float,
) -> list[sqlite3.Row]:
    handles = candidate_handles(recipient)
    handle_marks = ", ".join("?" for _ in handles)
    apple_ns = int((sent_after_unix - APPLE_EPOCH_OFFSET) * 1_000_000_000)
    return connection.execute(
        f"""
        SELECT m.ROWID AS row_id, m.error AS send_error,
               m.is_sent, m.is_delivered, m.service,
               m.text, m.attributedBody
        FROM message m
        JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.is_from_me = 1
          AND h.id IN ({handle_marks})
          AND m.service IN ('iMessage', 'iMessageLite')
          AND m.date >= ?
        ORDER BY m.date DESC
        LIMIT 10
        """,
        handles + (apple_ns,),
    ).fetchall()


def query_pinned(connection: sqlite3.Connection, row_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT m.ROWID AS row_id, m.error AS send_error,
               m.is_sent, m.is_delivered, m.service,
               m.text, m.attributedBody
        FROM message m
        WHERE m.ROWID = ? AND m.is_from_me = 1
        LIMIT 1
        """,
        (row_id,),
    ).fetchone()


def main() -> int:
    config = json.loads(sys.stdin.readline())
    recipient = str(config["recipient"])
    message = str(config["message"])
    sent_after_unix = float(config["sent_after_unix"])
    observe_seconds = min(max(float(config.get("observe_seconds", 60)), 1), 600)
    database = Path(
        str(config.get("database", Path.home() / "Library/Messages/chat.db"))
    ).expanduser()

    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")

    started = time.monotonic()
    deadline = started + observe_seconds
    pinned_row_id: int | None = None
    last_visible: tuple[object, ...] | None = None
    saw_error_codes: set[int] = set()

    emit(
        "collector_started",
        database_exists=database.exists(),
        observe_seconds=observe_seconds,
        sms_authorized=False,
    )
    while time.monotonic() < deadline:
        if pinned_row_id is None:
            rows = query_candidates(connection, recipient, sent_after_unix)
            row = next(
                (candidate for candidate in rows if row_text(candidate) == message),
                None,
            )
            if row is not None:
                pinned_row_id = int(row["row_id"])
        else:
            row = query_pinned(connection, pinned_row_id)

        elapsed = round(time.monotonic() - started, 3)
        if row is None:
            visible = (None, None, False, False, None)
        else:
            error = int(row["send_error"] or 0)
            if error:
                saw_error_codes.add(error)
            visible = (
                int(row["row_id"]),
                error,
                bool(row["is_sent"]),
                bool(row["is_delivered"]),
                str(row["service"]),
            )
        if visible != last_visible:
            row_id, error, is_sent, is_delivered, service = visible
            emit(
                "state_changed",
                elapsed_seconds=elapsed,
                row_matched=row_id is not None,
                error=error,
                is_sent=is_sent,
                is_delivered=is_delivered,
                service=service,
                sms_authorized=False,
            )
            last_visible = visible
        time.sleep(POLL_SECONDS)

    connection.close()
    row_id, error, is_sent, is_delivered, service = last_visible or (
        None,
        None,
        False,
        False,
        None,
    )
    if is_delivered:
        verdict = "delivered"
    elif error:
        verdict = "persistent-error-candidate-not-terminal"
    elif is_sent:
        verdict = "sent-unconfirmed"
    else:
        verdict = "unresolved"
    emit(
        "collector_finished",
        row_matched=row_id is not None,
        final_error=error,
        observed_error_codes=sorted(saw_error_codes),
        is_sent=is_sent,
        is_delivered=is_delivered,
        service=service,
        verdict=verdict,
        sms_authorized=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
