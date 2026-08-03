"""MCP server exposing exactly one outbound Messages tool."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from send_only_mac_messages.sender import send_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("send_only_mac_messages")

mcp = FastMCP(
    "send-only-mac-messages",
    instructions=(
        "Send a message to an exact phone number through macOS Messages. "
        "This server cannot read conversations, contacts, chats, or attachments."
    ),
)


@mcp.tool()
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


def run_server() -> None:
    """Run the send-only server over local standard input/output."""
    logger.info("Starting send-only macOS Messages server")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
