# Changelog

## [0.1.0] - Unreleased

- Rename the fork to `send-only-mac-messages`.
- Expose exactly one MCP tool for direct phone-number sends.
- Remove all message, contact, chat, database, and attachment readers.
- Cherry-pick the upstream iMessage-to-SMS/RCS fallback implementation from
  `f77be9e`, limited to the send-only package surface.
- Pass send data to `osascript` over standard input and redact results.
- Add an optional principal-bound Streamable HTTP entry point with Heimdall-style
  bearer/digest authentication, strict origin checks, and sender attestation.
- Add owner-only bearer create, replace, and revoke tooling plus launchd and
  Cloudflare deployment templates.
- Cherry-pick upstream's read-only, six-second delivery verifier from `1a8f309`
  verbatim, without adding another MCP tool or retaining message state.
