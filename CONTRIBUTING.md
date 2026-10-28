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

Tests must mock AppleScript and must never send a real message. Database tests must
use temporary fixtures and never open the user's live Messages database. Do not
expand ADR-0005's exact-attempt observer or ADR-0006's immediate-only SMS/RCS
fallback into history
reads, Contacts access, chat or recipient discovery, attachments, arbitrary database
access, retained send state, automatic retry after ambiguity, or a second MCP tool
without another explicit architecture decision.

Never commit real phone numbers, message bodies, credentials, raw AppleScript errors,
or hosted-Mac secrets.
