"""Authenticated Streamable HTTP and sender-attestation contract tests."""

from __future__ import annotations

import asyncio
import getpass
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from send_only_mac_messages.auth import BearerVerifier
from send_only_mac_messages.remote import (
    MCP_REQUEST_BODY_CAP,
    REMOTE_RESULT_BUSY,
    REMOTE_RESULT_SENDER_MISMATCH,
    AuthenticatedRemoteMCP,
    RemoteConfigurationError,
    RemoteServerSettings,
    SenderAttestor,
    create_remote_application,
)
from send_only_mac_messages.server import TOOL_DESCRIPTION

PUBLIC_HOST = "messages-principal-a.example.com"
LOGICAL_SENDER = "principal_a"
BEARER = "G" * 43


def test_remote_settings_require_explicit_host_sender_and_mac_user() -> None:
    current_user = getpass.getuser()
    settings = RemoteServerSettings.from_environment(
        {
            "SEND_ONLY_MCP_PUBLIC_HOST": PUBLIC_HOST,
            "SEND_ONLY_MCP_LOGICAL_SENDER": LOGICAL_SENDER,
            "SEND_ONLY_MCP_EXPECTED_USER": current_user,
            "SEND_ONLY_MCP_PORT": "49161",
        }
    )

    assert settings.public_host == PUBLIC_HOST
    assert settings.logical_sender == LOGICAL_SENDER
    assert settings.expected_user == current_user
    assert settings.expected_uid == os.geteuid()
    assert settings.port == 49161

    for environment in (
        {},
        {
            "SEND_ONLY_MCP_PUBLIC_HOST": "bad host",
            "SEND_ONLY_MCP_LOGICAL_SENDER": LOGICAL_SENDER,
            "SEND_ONLY_MCP_EXPECTED_USER": current_user,
        },
        {
            "SEND_ONLY_MCP_PUBLIC_HOST": PUBLIC_HOST,
            "SEND_ONLY_MCP_LOGICAL_SENDER": "Principal A",
            "SEND_ONLY_MCP_EXPECTED_USER": current_user,
        },
        {
            "SEND_ONLY_MCP_PUBLIC_HOST": PUBLIC_HOST,
            "SEND_ONLY_MCP_LOGICAL_SENDER": LOGICAL_SENDER,
            "SEND_ONLY_MCP_EXPECTED_USER": "user-that-must-not-exist",
        },
    ):
        with pytest.raises(RemoteConfigurationError):
            RemoteServerSettings.from_environment(environment)


def test_origin_and_auth_rejections_happen_before_body_read() -> None:
    app = _build_app()

    for headers, expected_status in (
        (_headers(authorization=None), 401),
        (_headers(authorization="Bearer " + "H" * 43), 401),
        (_headers(expected_sender="principal_b"), 403),
    ):
        messages, body_reads = asyncio.run(_direct_request(app, headers=headers))
        assert messages[0]["status"] == expected_status
        assert body_reads == 0
        assert messages[1]["body"] == b"request rejected\n"
        assert BEARER.encode("ascii") not in messages[1]["body"]


def test_remote_origin_rejects_aliases_and_oversized_requests() -> None:
    app = _build_app()

    cases = (
        ({"host": "wrong.example.com"}, 404),
        ({"path": "/mcp/", "raw_path": b"/mcp/"}, 404),
        ({"query_string": b"q=1"}, 404),
        ({"method": "GET"}, 405),
        ({"content_type": "text/plain"}, 415),
        ({"accept": "application/json;q=0"}, 406),
        ({"content_encoding": "gzip"}, 415),
        ({"content_length": str(MCP_REQUEST_BODY_CAP + 1)}, 413),
        ({"origin": "https://wrong.example.com"}, 403),
    )

    for overrides, expected_status in cases:
        messages, body_reads = asyncio.run(
            _direct_request(app, headers=_headers(**overrides), **overrides)
        )
        assert messages[0]["status"] == expected_status
        assert body_reads == 0


def test_authenticated_initialize_reaches_one_tool_protocol_surface() -> None:
    app = _build_app()

    response = asyncio.run(
        _post_json(
            app,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "remote-test", "version": "1"},
                },
            },
        )
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["result"]["serverInfo"]["name"] == ("send-only-mac-messages")


def test_remote_tool_description_exposes_delivery_mode_contract() -> None:
    app = _build_app()

    response = asyncio.run(
        _post_json(
            app,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
    )

    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["tool_send_message"]
    assert tools[0]["description"] == TOOL_DESCRIPTION
    for argument in ("recipient", "message", "delivery_mode"):
        assert tools[0]["inputSchema"]["properties"][argument]["description"]
    assert tools[0]["inputSchema"]["properties"]["delivery_mode"]["enum"] == [
        "imessage_only",
        "imessage_with_sms_fallback",
    ]
    assert "delivery_mode" in tools[0]["inputSchema"]["required"]


def test_authenticated_tool_call_attests_sender_and_returns_sender_label() -> None:
    sender = Mock(
        return_value="error:send_status_unknown:iMessage:message-not-correlated"
    )
    attestor = SenderAttestor(
        logical_sender=LOGICAL_SENDER,
        expected_uid=501,
        effective_uid=lambda: 501,
        console_uid=lambda: 501,
    )
    app = _build_app(attestor=attestor, sender=sender)

    response = asyncio.run(_post_json(app, _tool_call()))

    assert response.status_code == 200
    result = response.json()["result"]["structuredContent"]
    assert result == {
        "sender": LOGICAL_SENDER,
        "result": "error:send_status_unknown:iMessage:message-not-correlated",
    }
    sender.assert_called_once_with(
        "+14155551234",
        "private body",
        "imessage_only",
    )
    assert "+14155551234" not in response.text
    assert "private body" not in response.text


@pytest.mark.parametrize("invalid_mode", [None, "automatic"])
def test_missing_or_invalid_delivery_mode_never_invokes_sender(
    invalid_mode: str | None,
) -> None:
    sender = Mock(return_value="delivered:iMessage")
    app = _build_app(sender=sender)
    call = _tool_call()
    arguments = call["params"]["arguments"]
    if invalid_mode is None:
        arguments.pop("delivery_mode")
    else:
        arguments["delivery_mode"] = invalid_mode

    response = asyncio.run(_post_json(app, call))

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is True
    sender.assert_not_called()


def test_sender_attestation_failure_never_invokes_messages() -> None:
    sender = Mock(
        return_value="error:send_status_unknown:iMessage:message-not-correlated"
    )
    attestor = SenderAttestor(
        logical_sender=LOGICAL_SENDER,
        expected_uid=501,
        effective_uid=lambda: 501,
        console_uid=lambda: 502,
    )
    app = _build_app(attestor=attestor, sender=sender)

    response = asyncio.run(_post_json(app, _tool_call()))

    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"] == {
        "sender": LOGICAL_SENDER,
        "result": REMOTE_RESULT_SENDER_MISMATCH,
    }
    sender.assert_not_called()


def test_remote_sender_remains_serialized_during_a_long_fallback_call() -> None:
    counter_lock = threading.Lock()
    active_calls = 0
    maximum_active_calls = 0

    def sender(recipient: str, message: str, delivery_mode: str) -> str:
        nonlocal active_calls, maximum_active_calls
        del recipient, message, delivery_mode
        with counter_lock:
            active_calls += 1
            maximum_active_calls = max(maximum_active_calls, active_calls)
        threading.Event().wait(timeout=0.05)
        with counter_lock:
            active_calls -= 1
        return "sent-unconfirmed:SMS:delivery-timeout"

    app = _build_app(sender=sender)

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        async with app.protocol_app.router.lifespan_context(app.protocol_app):  # type: ignore[attr-defined]
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=f"https://{PUBLIC_HOST}",
            ) as client:
                headers = {
                    "Authorization": f"Bearer {BEARER}",
                    "X-Expected-Sender": LOGICAL_SENDER,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                first_call = _tool_call()
                second_call = _tool_call()
                second_call["id"] = 3
                first_response, second_response = await asyncio.gather(
                    client.post(
                        "/mcp",
                        content=json.dumps(first_call),
                        headers=headers,
                    ),
                    client.post(
                        "/mcp",
                        content=json.dumps(second_call),
                        headers=headers,
                    ),
                )
                return first_response, second_response

    first_response, second_response = asyncio.run(exercise())

    result_tokens = {
        first_response.json()["result"]["structuredContent"]["result"],
        second_response.json()["result"]["structuredContent"]["result"],
    }
    assert result_tokens <= {
        "sent-unconfirmed:SMS:delivery-timeout",
        REMOTE_RESULT_BUSY,
    }
    assert "sent-unconfirmed:SMS:delivery-timeout" in result_tokens
    assert maximum_active_calls == 1


def _build_app(
    *,
    attestor: SenderAttestor | None = None,
    sender: Any = None,
) -> AuthenticatedRemoteMCP:
    settings = RemoteServerSettings(
        public_host=PUBLIC_HOST,
        logical_sender=LOGICAL_SENDER,
        expected_user=getpass.getuser(),
        expected_uid=os.geteuid(),
        bearer_digest_path="/not-used",
    )
    verifier = BearerVerifier(
        enabled=True,
        digest=hashlib.sha256(BEARER.encode("ascii")).digest(),
    )
    keyword_args: dict[str, Any] = {}
    if attestor is not None:
        keyword_args["attestor"] = attestor
    if sender is not None:
        keyword_args["sender"] = sender
    return create_remote_application(settings, verifier, **keyword_args)


def _headers(
    *,
    host: str = PUBLIC_HOST,
    authorization: str | None = f"Bearer {BEARER}",
    expected_sender: str = LOGICAL_SENDER,
    content_type: str = "application/json",
    accept: str = "application/json, text/event-stream",
    content_encoding: str | None = None,
    content_length: str | None = None,
    origin: str | None = None,
    **_ignored: object,
) -> list[tuple[bytes, bytes]]:
    values = [
        (b"host", host.encode("ascii")),
        (b"content-type", content_type.encode("ascii")),
        (b"accept", accept.encode("ascii")),
        (b"x-expected-sender", expected_sender.encode("ascii")),
    ]
    if authorization is not None:
        values.append((b"authorization", authorization.encode("ascii")))
    if content_encoding is not None:
        values.append((b"content-encoding", content_encoding.encode("ascii")))
    if content_length is not None:
        values.append((b"content-length", content_length.encode("ascii")))
    if origin is not None:
        values.append((b"origin", origin.encode("ascii")))
    return values


async def _direct_request(
    app: AuthenticatedRemoteMCP,
    *,
    headers: list[tuple[bytes, bytes]],
    method: str = "POST",
    path: str = "/mcp",
    raw_path: bytes = b"/mcp",
    query_string: bytes = b"",
    **_ignored: object,
) -> tuple[list[dict[str, Any]], int]:
    body_reads = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal body_reads
        body_reads += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "https",
        "method": method,
        "path": path,
        "raw_path": raw_path,
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": (PUBLIC_HOST, 443),
    }
    await app(scope, receive, send)  # type: ignore[arg-type]
    return sent, body_reads


async def _post_json(
    app: AuthenticatedRemoteMCP,
    payload: dict[str, Any],
) -> httpx.Response:
    async with app.protocol_app.router.lifespan_context(app.protocol_app):  # type: ignore[attr-defined]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url=f"https://{PUBLIC_HOST}",
        ) as client:
            return await client.post(
                "/mcp",
                content=json.dumps(payload),
                headers={
                    "Authorization": f"Bearer {BEARER}",
                    "X-Expected-Sender": LOGICAL_SENDER,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )


def _tool_call() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "tool_send_message",
            "arguments": {
                "recipient": "+14155551234",
                "message": "private body",
                "delivery_mode": "imessage_only",
            },
        },
    }
