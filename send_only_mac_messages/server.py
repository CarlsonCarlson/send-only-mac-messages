"""MCP server exposing exactly one outbound Messages tool."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from send_only_mac_messages.sender import send_message

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
                "Exact phone number. Ten-digit US numbers and E.164-style "
                "international numbers are accepted; contact names are not."
            )
        ),
    ],
    message: Annotated[
        str,
        Field(description="Exact text body to send through Messages.app."),
    ],
) -> str:
    """Send one message using iMessage with immediate SMS/RCS fallback."""
    logger.info("Submitting one outbound Messages request")
    return send_message(recipient, message)


def create_mcp(
    tool_handler: Callable[[str, str], object] = tool_send_message,
    *,
    structured_output: bool | None = None,
    remote_instructions: str | None = None,
) -> FastMCP:
    """Create the one-tool MCP surface for either stdio or remote transport."""
    instructions = (
        "Send a message to an exact phone number through macOS Messages. "
        "This server cannot read conversations, contacts, chats, or attachments."
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
