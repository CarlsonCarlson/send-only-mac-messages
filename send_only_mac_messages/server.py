"""MCP server exposing exactly one outbound Messages tool."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from send_only_mac_messages.sender import DeliveryMode, send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("send_only_mac_messages")


def tool_send_message(
    recipient: Annotated[
        str,
        Field(
            description=(
                "Exact phone number, or the exact Messages chat id of an existing "
                "group chat in the form <service>;+;chat<digits> (Heimdall's "
                "sourceThreadId). Ten-digit US numbers and E.164-style "
                "international numbers are accepted; contact names are not. "
                "Chat ids require imessage_only."
            )
        ),
    ],
    message: Annotated[
        str,
        Field(description="Exact text body to send through Messages.app."),
    ],
    delivery_mode: Annotated[
        DeliveryMode,
        Field(
            description=(
                "Required delivery policy. imessage_only never attempts SMS/RCS. "
                "imessage_with_sms_fallback permits one SMS/RCS attempt after an "
                "immediate or exactly correlated iMessage failure."
            )
        ),
    ],
) -> str:
    """Sends with the explicitly selected iMessage-only or fallback policy."""
    logger.info("Submitting one outbound Messages request")
    return send_message(recipient, message, delivery_mode)


def create_mcp(
    tool_handler: Callable[[str, str, DeliveryMode], object] = tool_send_message,
    *,
    structured_output: bool | None = None,
    remote_instructions: str | None = None,
) -> FastMCP:
    """Create the one-tool MCP surface for either stdio or remote transport."""
    instructions = (
        "Send a message to an exact phone number, or into an existing group chat "
        "by its exact Messages chat id, through macOS Messages. Group sends are "
        "imessage_only and report sent, never delivered. "
        "Every call must select imessage_only or imessage_with_sms_fallback. "
        "imessage_only never attempts SMS/RCS. The fallback mode may attempt "
        "SMS/RCS once after an immediate or exactly correlated iMessage failure; "
        "fallback after an observed failure can duplicate a delayed iMessage. "
        "It can transiently observe only the correlated outgoing status for that "
        "send; it cannot read conversations, contacts, chats, or attachments."
    )
    if remote_instructions:
        instructions = f"{instructions} {remote_instructions}"
    server = FastMCP(
        "send-only-mac-messages",
        instructions=instructions,
        json_response=True,
        stateless_http=True,
        max_request_body_size=64 * 1024,
    )
    server.add_tool(
        tool_handler,
        name="tool_send_message",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
        structured_output=structured_output,
    )
    return server


mcp = create_mcp()


def run_server() -> None:
    """Run the send-only server over local standard input/output."""
    logger.info("Starting send-only macOS Messages server")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
