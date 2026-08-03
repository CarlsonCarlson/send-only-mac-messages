# Changelog

## [0.1.0] - Unreleased

- Rename the fork to `send-only-mac-messages`.
- Expose exactly one MCP tool for direct phone-number sends.
- Remove all message, contact, chat, database, and attachment readers.
- Preserve immediate iMessage-to-SMS fallback.
- Pass send data to `osascript` over standard input and redact results.
- Add an optional principal-bound Streamable HTTP entry point with Heimdall-style
  bearer/digest authentication, strict origin checks, and sender attestation.
- Add owner-only bearer create, replace, and revoke tooling plus launchd and
  Cloudflare deployment templates.
