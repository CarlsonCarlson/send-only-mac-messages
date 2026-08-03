"""Narrow outbound-only integration with macOS Messages.app."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

APPLESCRIPT_TIMEOUT_SECONDS = 30.0
MAX_MESSAGE_CHARS = 4_000

_ALLOWED_APPLESCRIPT_RESULTS = {
    "accepted-unverified:iMessage",
    "accepted-unverified:SMS",
    "error:send_failed",
}
_PHONE_INPUT = re.compile(r"\+?[0-9 ()-]+\Z")


def escape_applescript(value: str) -> str:
    """Escape a value for an AppleScript double-quoted string literal."""
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


def normalize_phone_number(recipient: str) -> str:
    """Normalize a raw phone-number input to an E.164-style Messages handle."""
    raw = str(recipient).strip()
    if not raw or not _PHONE_INPUT.fullmatch(raw):
        raise ValueError("recipient must be a phone number")

    digits = "".join(character for character in raw if character in "0123456789")
    if not 10 <= len(digits) <= 15:
        raise ValueError("recipient must contain 10 to 15 digits")
    if raw.startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}"


def run_applescript(script: str, timeout: float = APPLESCRIPT_TIMEOUT_SECONDS) -> str:
    """Run AppleScript over stdin and return only an allow-listed result token."""
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
        return "error:timeout"

    if completed.returncode != 0:
        return "error:automation_failed"

    result = completed.stdout.strip()
    if result not in _ALLOWED_APPLESCRIPT_RESULTS:
        return "error:unexpected_result"
    return result


def build_send_script(recipient: str, message: str) -> str:
    """Build the iMessage-first AppleScript with immediate SMS fallback."""
    safe_recipient = escape_applescript(recipient)
    safe_message = escape_applescript(message)
    return f"""tell application "Messages"
    try
        set imessageService to first service whose service type = iMessage
        send "{safe_message}" to participant "{safe_recipient}" of imessageService
        return "accepted-unverified:iMessage"
    on error
        try
            set smsService to first account whose service type = SMS and enabled is true
            send "{safe_message}" to participant "{safe_recipient}" of smsService
            return "accepted-unverified:SMS"
        on error
            return "error:send_failed"
        end try
    end try
end tell"""


def send_message(
    recipient: str,
    message: str,
    *,
    applescript_runner: Callable[[str], str] = run_applescript,
) -> str:
    """Submit one direct phone-number message without reading local user data."""
    try:
        normalized_recipient = normalize_phone_number(recipient)
    except ValueError:
        return "rejected:invalid_recipient"

    if not isinstance(message, str) or not message.strip():
        return "rejected:empty_message"
    if len(message) > MAX_MESSAGE_CHARS:
        return "rejected:message_too_long"

    result = applescript_runner(build_send_script(normalized_recipient, message))
    if result in _ALLOWED_APPLESCRIPT_RESULTS or result in {
        "error:timeout",
        "error:automation_failed",
        "error:unexpected_result",
    }:
        return result
    return "error:unexpected_result"
