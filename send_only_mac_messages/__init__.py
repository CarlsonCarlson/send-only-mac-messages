"""Send-only macOS Messages package."""

from importlib.metadata import PackageNotFoundError, version

from .sender import send_message

__all__ = ["send_message"]

try:
    __version__ = version("send-only-mac-messages")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
