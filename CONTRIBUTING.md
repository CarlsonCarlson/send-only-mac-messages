# Contributing

## Checks

```bash
uv sync --frozen --extra dev
uv run pytest -q
uv run black --check .
uv run isort --check-only .
uv run mypy send_only_mac_messages
uv build
```

Tests must mock AppleScript and must never send a real message. Do not introduce
message reads, Contacts access, chat or recipient discovery, attachments, database
access, Full Disk Access, or a second MCP tool without an explicit architecture
decision.

Never commit real phone numbers, message bodies, credentials, raw AppleScript errors,
or hosted-Mac secrets.
