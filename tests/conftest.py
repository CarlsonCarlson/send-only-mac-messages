"""Pin the send clock to midday Pacific so tests that don't pass `clock` never hit quiet hours."""

from __future__ import annotations

from datetime import datetime

import pytest

from send_only_mac_messages import sender


@pytest.fixture(autouse=True)
def _daytime_send_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    noon = datetime.fromisoformat("2026-10-27T12:00:00-07:00")
    monkeypatch.setattr(sender, "utc_now", lambda: noon)
