"""Principal-bound Streamable HTTP transport for the send-only adapter."""

from __future__ import annotations

import asyncio
import contextvars
import getpass
import logging
import os
import pwd
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from send_only_mac_messages.auth import (
    BearerVerifier,
    default_bearer_digest_path,
    load_bearer_verifier,
    parse_authorization_header,
)
from send_only_mac_messages.sender import DeliveryMode, send_message
from send_only_mac_messages.server import create_mcp

logger = logging.getLogger("send_only_mac_messages.remote")

MCP_PUBLIC_PATH = "/mcp"
MCP_REQUEST_BODY_CAP = 64 * 1024
EXPECTED_SENDER_HEADER = "x-expected-sender"
REMOTE_RESULT_SENDER_MISMATCH = "error:sender_mismatch"
REMOTE_RESULT_BUSY = "error:busy"
TRANSPORT_FAILURE_BODY = b"request rejected\n"

_LABEL = re.compile(r"[a-z][a-z0-9_-]{0,62}\Z")
_HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?:\.(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?))*\Z"
)
_remote_sender: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "send_only_remote_sender", default=None
)


class RemoteConfigurationError(RuntimeError):
    """The remote process configuration cannot prove its intended principal."""


@dataclass(frozen=True)
class RemoteServerSettings:
    """Immutable, non-secret configuration for one principal-bound endpoint."""

    public_host: str
    logical_sender: str
    expected_user: str
    expected_uid: int
    bearer_digest_path: str
    port: int = 49160

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> RemoteServerSettings:
        """Load explicit principal configuration and reject ambient-user inference."""
        values = os.environ if environment is None else environment
        public_host = values.get("SEND_ONLY_MCP_PUBLIC_HOST", "")
        logical_sender = values.get("SEND_ONLY_MCP_LOGICAL_SENDER", "")
        expected_user = values.get("SEND_ONLY_MCP_EXPECTED_USER", "")
        digest_path = values.get(
            "SEND_ONLY_MCP_BEARER_DIGEST_PATH",
            os.fspath(default_bearer_digest_path()),
        )
        port_text = values.get("SEND_ONLY_MCP_PORT", "49160")

        if not _HOST.fullmatch(public_host):
            raise RemoteConfigurationError("SEND_ONLY_MCP_PUBLIC_HOST is invalid")
        if not _LABEL.fullmatch(logical_sender):
            raise RemoteConfigurationError("SEND_ONLY_MCP_LOGICAL_SENDER is invalid")
        if not expected_user:
            raise RemoteConfigurationError("SEND_ONLY_MCP_EXPECTED_USER is required")
        try:
            expected_uid = pwd.getpwnam(expected_user).pw_uid
        except KeyError as exc:
            raise RemoteConfigurationError(
                "expected macOS user does not exist"
            ) from exc
        try:
            port = int(port_text)
        except ValueError as exc:
            raise RemoteConfigurationError("SEND_ONLY_MCP_PORT is invalid") from exc
        if not 1 <= port <= 65535:
            raise RemoteConfigurationError("SEND_ONLY_MCP_PORT is out of range")
        if os.geteuid() != expected_uid or getpass.getuser() != expected_user:
            raise RemoteConfigurationError(
                "remote server is not running as the configured macOS user"
            )

        return cls(
            public_host=public_host.lower(),
            logical_sender=logical_sender,
            expected_user=expected_user,
            expected_uid=expected_uid,
            bearer_digest_path=digest_path,
            port=port,
        )


@dataclass(frozen=True)
class SenderAttestor:
    """Recheck the authenticated logical sender and GUI user before every send."""

    logical_sender: str
    expected_uid: int
    effective_uid: Callable[[], int] = os.geteuid
    console_uid: Callable[[], int] = lambda: os.stat("/dev/console").st_uid

    def attest(self) -> bool:
        try:
            return (
                _remote_sender.get() == self.logical_sender
                and self.effective_uid() == self.expected_uid
                and self.console_uid() == self.expected_uid
            )
        except OSError:
            return False


class AuthenticatedRemoteMCP:
    """Strict origin and bearer wrapper around the SDK's stateless MCP app."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        public_host: str,
        logical_sender: str,
        verifier: BearerVerifier,
    ) -> None:
        self.protocol_app = app
        self.public_host = public_host
        self.logical_sender = logical_sender
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.protocol_app(scope, receive, send)
            return

        admission = self._admit(scope)
        if admission is not None:
            status, allow = admission
            await _send_transport_failure(send, status, allow=allow)
            return

        authorization = _header_values(scope, "authorization")
        bearer = parse_authorization_header(authorization)
        if bearer is None or not self.verifier.validate(bearer):
            await _send_transport_failure(send, 401)
            return

        expected_sender = _header_values(scope, EXPECTED_SENDER_HEADER)
        if expected_sender != [self.logical_sender]:
            await _send_transport_failure(send, 403)
            return

        body = await _read_bounded_body(receive, MCP_REQUEST_BODY_CAP)
        if body is None:
            await _send_transport_failure(send, 413)
            return

        token = _remote_sender.set(self.logical_sender)
        try:
            await self.protocol_app(
                scope,
                _replay_body(body),
                _with_security_headers(send),
            )
        finally:
            _remote_sender.reset(token)

    def _admit(self, scope: Scope) -> tuple[int, str | None] | None:
        host = _header_values(scope, "host")
        if (
            host != [self.public_host]
            or scope.get("path") != MCP_PUBLIC_PATH
            or scope.get("raw_path", b"") != MCP_PUBLIC_PATH.encode("ascii")
            or scope.get("query_string", b"") != b""
        ):
            return 404, None
        if scope.get("method") != "POST":
            return 405, "POST"
        if not _content_type_allowed(_header_values(scope, "content-type")):
            return 415, None
        if not _accept_allowed(_header_values(scope, "accept")):
            return 406, None
        if _has_non_identity_encoding(_header_values(scope, "content-encoding")):
            return 415, None
        content_length = _declared_content_length(
            _header_values(scope, "content-length")
        )
        if content_length is False:
            return 400, None
        if isinstance(content_length, int) and content_length > MCP_REQUEST_BODY_CAP:
            return 413, None
        origins = _header_values(scope, "origin")
        if origins and origins != [f"https://{self.public_host}"]:
            return 403, None
        return None


def create_remote_application(
    settings: RemoteServerSettings,
    verifier: BearerVerifier,
    *,
    attestor: SenderAttestor | None = None,
    sender: Callable[[str, str, DeliveryMode], str] = send_message,
) -> AuthenticatedRemoteMCP:
    """Create one authenticated remote application for one logical sender."""
    sender_attestor = attestor or SenderAttestor(
        logical_sender=settings.logical_sender,
        expected_uid=settings.expected_uid,
    )
    send_lock = threading.Lock()

    def remote_send_message(
        recipient: str,
        message: str,
        delivery_mode: DeliveryMode,
    ) -> dict[str, str]:
        """Sends with the explicitly selected iMessage-only or fallback policy."""
        if not sender_attestor.attest():
            logger.error("Rejecting outbound request because sender attestation failed")
            return {
                "sender": settings.logical_sender,
                "result": REMOTE_RESULT_SENDER_MISMATCH,
            }
        if not send_lock.acquire(blocking=False):
            return {
                "sender": settings.logical_sender,
                "result": REMOTE_RESULT_BUSY,
            }
        try:
            return {
                "sender": settings.logical_sender,
                "result": sender(recipient, message, delivery_mode),
            }
        finally:
            send_lock.release()

    protocol_server = create_mcp(
        remote_send_message,
        structured_output=True,
        remote_instructions=(
            "Every call requires explicit send authorization and delivery mode. "
            "imessage_only never attempts SMS/RCS. The fallback mode may make one "
            "SMS/RCS attempt after an immediate or exactly correlated iMessage "
            "failure and therefore carries duplicate-delivery risk. Clients must "
            "never retry a tool-call error, "
            "timeout, interruption, or missing response; the outcome may be unknown."
        ),
    )
    protocol_server.settings.transport_security = TransportSecuritySettings(
        allowed_hosts=[settings.public_host],
        allowed_origins=[f"https://{settings.public_host}"],
    )
    protocol_app = protocol_server.streamable_http_app()
    return AuthenticatedRemoteMCP(
        protocol_app,
        public_host=settings.public_host,
        logical_sender=settings.logical_sender,
        verifier=verifier,
    )


def run_remote_server() -> None:
    """Run the authenticated MCP origin on principal-local loopback."""
    settings = RemoteServerSettings.from_environment()
    verifier = load_bearer_verifier(settings.bearer_digest_path)
    app = create_remote_application(settings, verifier)
    logger.info(
        "Starting principal-bound remote MCP for sender=%s on loopback port=%d",
        settings.logical_sender,
        settings.port,
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=settings.port,
        access_log=False,
        log_level="info",
    )


def _header_values(scope: Scope, name: str) -> list[str]:
    wanted = name.lower().encode("ascii")
    return [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == wanted
    ]


def _content_type_allowed(values: list[str]) -> bool:
    if len(values) != 1:
        return False
    parts = [part.strip() for part in values[0].split(";")]
    if not parts or parts[0].lower() != "application/json":
        return False
    if len(parts) == 1:
        return True
    return len(parts) == 2 and parts[1].lower() == "charset=utf-8"


def _accept_allowed(values: list[str]) -> bool:
    for joined in values:
        for raw in joined.split(","):
            parts = [part.strip() for part in raw.split(";")]
            if not parts or parts[0].lower() != "application/json":
                continue
            quality = "1"
            valid = True
            for parameter in parts[1:]:
                key, separator, value = parameter.partition("=")
                if not separator or key.strip().lower() != "q":
                    valid = False
                    break
                quality = value.strip()
            if valid and _positive_quality(quality):
                return True
    return False


def _positive_quality(value: str) -> bool:
    if value == "1":
        return True
    if value == "0":
        return False
    whole, separator, fraction = value.partition(".")
    if not separator or not fraction or len(fraction) > 3 or not fraction.isdigit():
        return False
    if whole == "0":
        return any(digit != "0" for digit in fraction)
    if whole == "1":
        return all(digit == "0" for digit in fraction)
    return False


def _has_non_identity_encoding(values: list[str]) -> bool:
    return any(
        token.strip() and token.strip().lower() != "identity"
        for joined in values
        for token in joined.split(",")
    )


def _declared_content_length(values: list[str]) -> int | bool | None:
    if not values:
        return None
    if len(values) != 1 or not values[0].isdigit():
        return False
    return int(values[0])


async def _read_bounded_body(receive: Receive, limit: int) -> bytes | None:
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return None
        if message["type"] != "http.request":
            continue
        body.extend(message.get("body", b""))
        if len(body) > limit:
            return None
        if not message.get("more_body", False):
            return bytes(body)


def _replay_body(body: bytes) -> Receive:
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if delivered:
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _with_security_headers(send: Send) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = [
                (key, value)
                for key, value in message.get("headers", [])
                if key.lower() not in {b"cache-control", b"x-content-type-options"}
            ]
            headers.extend(
                [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            )
            message = {**message, "headers": headers}
        await send(message)

    return wrapped


async def _send_transport_failure(
    send: Send,
    status: int,
    *,
    allow: str | None = None,
) -> None:
    headers = [
        (b"cache-control", b"no-store"),
        (b"content-type", b"text/plain; charset=utf-8"),
        (b"content-length", str(len(TRANSPORT_FAILURE_BODY)).encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
    ]
    if allow is not None:
        headers.append((b"allow", allow.encode("ascii")))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": TRANSPORT_FAILURE_BODY})


if __name__ == "__main__":
    run_remote_server()
