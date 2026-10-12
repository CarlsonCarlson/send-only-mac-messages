#!/usr/bin/env python3
"""Drive the send-only MCP over stdio and prove the outcome from chat.db.

Usage (run from the repo root):
  uv run python .claude/skills/verify/scripts/drive_send.py --smoke-only
  printf '%s\n' '<phone or chat id>' | uv run python .claude/skills/verify/scripts/drive_send.py --send
  uv run python .claude/skills/verify/scripts/drive_send.py --self-test

The target is read from stdin so phone numbers stay out of shell history. Every
run writes one evidence JSON under --evidence-dir (default: verification-evidence/).
Phone targets are recorded as a SHA-256 prefix; chat ids are recorded verbatim.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_PROPERTIES = {"recipient", "message", "delivery_mode"}
APPLE_EPOCH_OFFSET = 978_307_200
CHAT_ID = re.compile(r"(any|iMessage|SMS|RCS);\+;chat[0-9]+\Z")
TOKEN = re.compile(
    r"(delivered|sent-unconfirmed|sent|rejected|error)(:[A-Za-z0-9_-]+){0,3}\Z"
)
DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"
DB_PROOF_SECONDS = 12.0

# macOS often stores the body only in attributedBody (text is NULL). The exact body
# match is a raw-bytes containment check in Python, independent of the package's
# own decoder. Rows are restricted to the target chat or handle so this read never
# touches other conversations.
PROOF_SQL_CHAT = """
SELECT m.ROWID AS row_id, m.service, m.is_sent, m.is_delivered, m.error AS send_error,
       m.handle_id, m.text, m.attributedBody, c.guid AS chat_guid
FROM message m
JOIN chat_message_join j ON j.message_id = m.ROWID
JOIN chat c ON c.ROWID = j.chat_id
WHERE m.is_from_me = 1 AND c.guid = ? AND m.date >= ?
ORDER BY m.date DESC
LIMIT 10
"""
PROOF_SQL_HANDLE = """
SELECT m.ROWID AS row_id, m.service, m.is_sent, m.is_delivered, m.error AS send_error,
       m.handle_id, m.text, m.attributedBody, NULL AS chat_guid
FROM message m
JOIN handle h ON h.ROWID = m.handle_id
WHERE m.is_from_me = 1 AND h.id = ? AND m.date >= ?
ORDER BY m.date DESC
LIMIT 10
"""


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def apple_ns(unix_seconds: float) -> int:
    return int((unix_seconds - APPLE_EPOCH_OFFSET) * 1_000_000_000)


def describe_target(target: str) -> dict[str, str]:
    if CHAT_ID.fullmatch(target):
        return {"kind": "chat", "value": target}
    digest = hashlib.sha256(target.encode()).hexdigest()[:12]
    return {"kind": "phone", "sha256_prefix": digest}


def _has_body(row: sqlite3.Row, body: str) -> bool:
    if row["text"] is not None:
        return row["text"] == body
    blob = row["attributedBody"] or b""
    return body.encode("utf-8") in bytes(blob)


def normalized_phone(target: str) -> str:
    digits = "".join(ch for ch in target if ch.isdigit())
    return f"+1{digits}" if len(digits) == 10 else f"+{digits}"


def proof_rows(db_path: Path, body: str, sent_after: float, target: str) -> list[dict]:
    if CHAT_ID.fullmatch(target):
        sql, key = PROOF_SQL_CHAT, target
    else:
        sql, key = PROOF_SQL_HANDLE, normalized_phone(target)
    uri = f"file:{db_path}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(sql, (key, apple_ns(sent_after))).fetchall()
        matched = [row for row in rows if _has_body(row, body)]
    return [
        {k: row[k] for k in row.keys() if k not in ("text", "attributedBody")}
        for row in matched
    ]


def wait_for_proof(
    db_path: Path, body: str, sent_after: float, target: str
) -> list[dict]:
    deadline = time.time() + DB_PROOF_SECONDS
    rows: list[dict] = []
    while time.time() < deadline:
        try:
            rows = proof_rows(db_path, body, sent_after, target)
        except sqlite3.Error as exc:
            return [{"db_error": type(exc).__name__}]
        if rows and all(r["is_sent"] or r["send_error"] for r in rows):
            break
        time.sleep(0.5)
    return rows


async def drive(
    send: bool, delivery_mode: str, evidence_dir: Path, message: str | None = None
) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    run_id = utc_now()
    evidence: dict = {"run_id": run_id, "mode": "send" if send else "smoke-only"}
    target = None
    if send:
        target = sys.stdin.readline().strip()
        if not target:
            print("target missing on stdin", file=sys.stderr)
            return 2
        evidence["target"] = describe_target(target)
        evidence["delivery_mode"] = delivery_mode

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "send_only_mac_messages.server"],
        env=os.environ.copy(),
    )
    exit_code = 0
    try:
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                resources = (await session.list_resources()).resources
                prompts = (await session.list_prompts()).prompts
                surface = {
                    "tool_names": sorted(t.name for t in tools),
                    "properties": (
                        sorted(tools[0].inputSchema["properties"]) if tools else []
                    ),
                    "required": (
                        sorted(tools[0].inputSchema.get("required", []))
                        if tools
                        else []
                    ),
                    "resource_count": len(resources),
                    "prompt_count": len(prompts),
                }
                surface["ok"] = (
                    surface["tool_names"] == ["tool_send_message"]
                    and set(surface["properties"]) >= EXPECTED_PROPERTIES
                    and surface["resource_count"] == 0
                    and surface["prompt_count"] == 0
                )
                evidence["surface"] = surface
                if not surface["ok"]:
                    exit_code = 1

                if send:
                    body = message if message else f"verify-send {run_id}"
                    evidence["body"] = body
                    sent_after = time.time()
                    result = await session.call_tool(
                        "tool_send_message",
                        {
                            "recipient": target,
                            "message": body,
                            "delivery_mode": delivery_mode,
                        },
                    )
                    texts = [
                        c.text
                        for c in result.content
                        if getattr(c, "type", "") == "text"
                    ]
                    raw = texts[0] if len(texts) == 1 else ""
                    evidence["token"] = raw if TOKEN.fullmatch(raw) else "unexpected"
                    evidence["is_error"] = bool(result.isError)
                    # A rejection never reaches Messages.app; one read is enough proof.
                    evidence["db_proof"] = (
                        proof_rows(DB_PATH, body, sent_after, target)
                        if raw.startswith("rejected:")
                        else wait_for_proof(DB_PATH, body, sent_after, target)
                    )
    except Exception as exc:  # protocol or launch failure
        evidence["failure"] = type(exc).__name__
        exit_code = 1

    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{run_id.replace(':', '-')}-{evidence['mode']}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({**evidence, "evidence_path": str(path)}, sort_keys=True))
    return exit_code


def self_test() -> int:
    """Smallest check that fails if the proof query or token filter breaks."""
    assert TOKEN.fullmatch("rejected:invalid_recipient")
    assert TOKEN.fullmatch("sent-unconfirmed:iMessage:delivery-timeout")
    assert not TOKEN.fullmatch("+14155551234 was sent hello")
    assert describe_target("any;+;chat1")["kind"] == "chat"
    assert describe_target("+14155551234")["kind"] == "phone"
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "chat.db"
        with sqlite3.connect(db) as c:
            c.executescript(
                """
                CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT);
                CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
                INSERT INTO handle VALUES (3, '+14155551234');
                CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
                CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, date INTEGER,
                    is_from_me INTEGER, service TEXT, is_sent INTEGER, is_delivered INTEGER,
                    error INTEGER, handle_id INTEGER, attributedBody BLOB);
                INSERT INTO chat VALUES (1, 'any;+;chat1');
                INSERT INTO message VALUES (7, 'body', 5000000000, 1, 'iMessage', 1, 0, 0, 0, NULL);
                INSERT INTO chat_message_join VALUES (1, 7);
                INSERT INTO message VALUES (8, 'body', 1000, 1, 'iMessage', 1, 0, 0, 0, NULL);
                INSERT INTO message VALUES (9, NULL, 5000000000, 1, 'iMessage', 1, 0, 0, 0, X'00626f647900');
                INSERT INTO chat VALUES (2, 'any;+;chat2');
                INSERT INTO chat_message_join VALUES (2, 9);
                INSERT INTO message VALUES (10, 'body', 5000000000, 1, 'iMessage', 1, 1, 0, 3, NULL);
                """
            )
        rows = proof_rows(db, "body", APPLE_EPOCH_OFFSET + 1, "any;+;chat1")
        assert [r["row_id"] for r in rows] == [7], rows
        assert rows[0]["chat_guid"] == "any;+;chat1" and rows[0]["handle_id"] == 0
        # attributedBody-only row in another chat is found by bytes, and only for its chat
        assert [
            r["row_id"]
            for r in proof_rows(db, "body", APPLE_EPOCH_OFFSET + 1, "any;+;chat2")
        ] == [9]
        assert [
            r["row_id"]
            for r in proof_rows(db, "body", APPLE_EPOCH_OFFSET + 1, "(415) 555-1234")
        ] == [10]
    print("self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--smoke-only", action="store_true", help="surface check, no send"
    )
    group.add_argument(
        "--send", action="store_true", help="one send to the stdin target"
    )
    group.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--delivery-mode",
        default="imessage_only",
        choices=("imessage_only", "imessage_with_sms_fallback"),
    )
    parser.add_argument(
        "--evidence-dir", type=Path, default=Path("verification-evidence")
    )
    parser.add_argument(
        "--message",
        help="exact body to send instead of the default 'verify-send <run_id>'",
    )
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return asyncio.run(
        drive(args.send, args.delivery_mode, args.evidence_dir, args.message)
    )


if __name__ == "__main__":
    raise SystemExit(main())
