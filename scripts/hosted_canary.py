#!/usr/bin/env python3
"""One-shot hosted-Mac surface check and explicitly authorized canary send."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {"tool_send_message"}
CANARY_PREFIX = "Send-only Mac Messages hosted canary"
DELIVERY_MODES = ("imessage_only", "imessage_with_sms_fallback")


def emit(phase: str, **fields: Any) -> None:
    """Print one sanitized state transition."""
    print(json.dumps({"phase": phase, **fields}, sort_keys=True), flush=True)


def classify_result(result: object) -> tuple[str, str | None]:
    """Classify a tool result without returning its raw content."""
    if getattr(result, "isError", False):
        return "error", None
    texts = [
        getattr(item, "text", "")
        for item in getattr(result, "content", [])
        if getattr(item, "type", "") == "text"
    ]
    for service in ("iMessage", "SMS"):
        if texts == [f"delivered:{service}"]:
            return "delivered", service
    for service in ("iMessage", "SMS"):
        if texts == [f"sent-unconfirmed:{service}:delivery-timeout"]:
            return "sent-unconfirmed", service
        for reason in (
            "database-unavailable",
            "message-not-correlated",
            "send-state-timeout",
        ):
            if texts == [f"error:send_status_unknown:{service}:{reason}"]:
                return "send-status-unknown", service
        if texts == [f"error:send_failed:{service}"]:
            return "send-failed", service
    return "error", None


def mutation_evidence(result_class: str) -> bool | str:
    """Return sanitized evidence that the invocation reached a submitted message."""
    if result_class in {
        "delivered",
        "sent-unconfirmed",
        "send-status-unknown",
    }:
        return True
    return "unknown"


def read_approved_target() -> str:
    """Read the approved phone handle from stdin without displaying it."""
    target = sys.stdin.readline().rstrip("\r\n")
    if not target:
        raise ValueError("approved target was not supplied")
    return target


async def run(smoke_only: bool, delivery_mode: str) -> int:
    """Verify the surface and optionally perform exactly one send invocation."""
    send_invoked = False
    target = None if smoke_only else read_approved_target()
    canary_id = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    body = f"{CANARY_PREFIX} {canary_id}"
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "send_only_mac_messages.server"],
        env=os.environ.copy(),
    )

    try:
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                resources = await session.list_resources()
                prompts = await session.list_prompts()
                if names != EXPECTED_TOOLS:
                    raise RuntimeError("unexpected tool surface")
                if resources.resources or prompts.prompts:
                    raise RuntimeError("unexpected read surface")
                emit(
                    "surface_verified",
                    tool_count=len(names),
                    resource_count=0,
                    prompt_count=0,
                    messages_mutated=False,
                )

                if smoke_only:
                    emit("stopped", messages_mutated=False)
                    return 0

                emit("send_started", canary_id=canary_id, messages_mutated=False)
                send_invoked = True
                result = await session.call_tool(
                    "tool_send_message",
                    {
                        "recipient": target,
                        "message": body,
                        "delivery_mode": delivery_mode,
                    },
                )
                result_class, service = classify_result(result)
                messages_mutated = mutation_evidence(result_class)
                emit(
                    "send_finished",
                    canary_id=canary_id,
                    result_class=result_class,
                    service=service,
                    messages_mutated=messages_mutated,
                )
                emit(
                    "stopped",
                    messages_mutated=messages_mutated,
                )
                return 0 if result_class in {"delivered", "sent-unconfirmed"} else 1
    except Exception as exc:
        emit(
            "failed",
            failure_class=type(exc).__name__,
            messages_mutated="unknown" if send_invoked else False,
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Hosted send-only Messages canary")
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="initialize and verify the MCP surface without invoking the send tool",
    )
    parser.add_argument(
        "--delivery-mode",
        choices=DELIVERY_MODES,
        default="imessage_only",
        help="delivery policy for an explicitly authorized live invocation",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.smoke_only, args.delivery_mode))


if __name__ == "__main__":
    raise SystemExit(main())
