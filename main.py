#!/usr/bin/env python3
"""Send-only macOS Messages package entry point."""

from send_only_mac_messages.server import run_server


def main() -> None:
    """Run the send-only MCP server."""
    run_server()


if __name__ == "__main__":
    main()
