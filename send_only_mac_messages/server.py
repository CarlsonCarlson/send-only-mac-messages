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


TOOL_DESCRIPTION = """\
Send one text message through Messages.app on this Mac.

Send to one phone number, or into one existing iMessage group by its chat id. \
Choose delivery_mode on every call. After sending, the tool watches the Messages \
database for up to 10 seconds and returns one fixed result string. The result \
never repeats the phone number or the text.

The tool only sends. It cannot read conversations, look up contacts, or list chats.

Every call sends a real message. Never repeat a call after a timeout, an error, \
or a missing response unless the result below says you may. A repeated call can \
send the text twice.

Modes. imessage_only asks Messages for one iMessage and never adds an SMS attempt \
of its own; Messages itself may still switch a failed iMessage to SMS, and the \
result then names SMS. sms_only asks for one SMS and never tries iMessage; use it \
only when the caller's own rules allow SMS and the number is known to lack \
iMessage. imessage_with_sms_fallback tries iMessage first and may also send SMS.

Fallback risk. In imessage_with_sms_fallback mode, if Messages reports that the \
iMessage failed, the tool sends the same text once more as SMS. The sender's \
thread then shows two bubbles, the failed iMessage and the SMS. If the iMessage \
was only delayed and arrives later, the person gets the text twice.

Results. <service> is iMessage or SMS. SMS also covers RCS.
- delivered:<service>. Messages marked the message delivered within 10 seconds. \
This does not mean the person read it. Do not send again.
- sent-unconfirmed:<service>:delivery-timeout. Messages marked the message sent \
but did not mark it delivered within 10 seconds. Treat it as sent. Do not send \
again.
- sent:iMessage:group-delivery-not-reported. Messages marked the group message \
sent. Messages never reports delivery for groups, so this is the success result \
for a group. Do not send again.
- error:send_failed:<service>. Messages reported that the send failed on that \
service. For iMessage this usually means the number has no iMessage. The text may \
still reach the person: a delayed iMessage can arrive, and Messages on some Macs \
switches a failed iMessage to SMS on its own. Do not repeat the call in any mode. \
Report the result and let a person decide.
- error:send_status_unknown:<service>:database-unavailable. Messages accepted the \
send, but the tool could not open the Messages database to check it. The message \
may have gone out. Never call again.
- error:send_status_unknown:<service>:message-not-correlated. Messages accepted \
the send, but the tool found no matching outgoing message within 10 seconds. The \
message may have gone out. Never call again.
- error:send_status_unknown:<service>:send-state-timeout. The tool found the \
message, but Messages marked it neither sent nor failed within 10 seconds. Never \
call again.
- error:timeout. Messages.app did not answer within 30 seconds. The message may \
have gone out. Never call again.
- error:automation_failed. The script that controls Messages.app failed to run, \
for example because macOS has not allowed this app to control Messages. The \
outcome is unknown. Never call again.
- error:unexpected_result. The tool got an answer it does not recognize. The \
outcome is unknown. Never call again.

A rejected result means the tool refused the call before sending anything. For \
every rejected result except unknown_chat_id, fix the input and call again.
- rejected:invalid_recipient. The recipient is not a phone number or a group \
chat id.
- rejected:empty_message. The message is empty.
- rejected:message_too_long. The message is longer than 4,000 characters.
- rejected:group_requires_imessage_only. A group chat id needs imessage_only.
- rejected:unknown_chat_id. Messages on this Mac did not find a chat with that id. \
Messages only exposes conversations it has loaded, roughly the recent ones, so a \
quiet group can be rejected even though it exists. Do not post into the group to \
wake it. Report the result; once a member has posted there, the same id works.
- rejected:group_not_imessage. That chat is not an iMessage chat.
- rejected:invalid_delivery_mode. delivery_mode is not one of the allowed values.

Two results come only from the remote server. Nothing was sent for either.
- error:sender_mismatch. The server could not confirm it runs as the expected \
Mac user. Do not call again until the Mac owner fixes the setup.
- error:busy. Another send was still running. You may call again after it \
finishes."""

Recipient = Annotated[
    str,
    Field(
        description=(
            "Who receives the message. Give a phone number or the chat id of an "
            "existing iMessage group. A phone number is a 10-digit US number, or "
            "an international number that starts with + and the country code. A "
            "group chat id is the exact Messages chat id, such as any;+;chat12345 "
            "or any;+;<32 hex characters>. It is the chat.guid value, which "
            "Heimdall returns as sourceThreadId. Groups work only with "
            "imessage_only. The tool never looks up chats or contacts, so it "
            "refuses names, email addresses, and group names."
        )
    ),
]
MessageText = Annotated[
    str,
    Field(
        description=(
            "The exact text to send. It cannot be empty or longer than 4,000 "
            "characters."
        )
    ),
]
DeliveryModeChoice = Annotated[
    DeliveryMode,
    Field(
        description=(
            "Required. imessage_only asks for one iMessage and never adds an SMS "
            "attempt of its own. sms_only asks for one SMS and never tries "
            "iMessage; use it only when your own rules allow SMS and the number "
            "is known to lack iMessage. "
            "imessage_with_sms_fallback sends iMessage first. If Messages reports "
            "that the iMessage failed, it sends the same text once as SMS. That "
            "can leave two bubbles in the sender's thread and can deliver the "
            "text twice. Group chat ids need imessage_only."
        )
    ),
]


def tool_send_message(
    recipient: Recipient,
    message: MessageText,
    delivery_mode: DeliveryModeChoice,
) -> str:
    """Send one message. TOOL_DESCRIPTION is the description agents see."""
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
        "This server sends text messages through Messages.app on one Mac. It has "
        "one tool, tool_send_message. Every call sends a real message, so call it "
        "once per message. Choose delivery_mode on every call. imessage_only asks "
        "for one iMessage and adds no SMS attempt of its own. sms_only asks for one "
        "SMS and never tries iMessage. imessage_with_sms_fallback sends the "
        "text once as SMS if the iMessage fails, which can leave two bubbles and "
        "can deliver the text twice. Group chats need imessage_only. The tool "
        "cannot read conversations, look up contacts, or list chats. Allow at "
        "least 90 seconds for one call; a group send or a fallback send can take "
        "that long. The tool description lists every result "
        "string, what causes it, and whether you may call again."
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
        description=TOOL_DESCRIPTION,
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
