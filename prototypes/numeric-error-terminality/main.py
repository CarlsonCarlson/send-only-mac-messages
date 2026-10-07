#!/usr/bin/env python3
"""Interactive TUI for the throwaway numeric-error state model."""

from __future__ import annotations

import json

from model import Sample, State, finish_window, observe

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"


def render(state: State) -> None:
    print(CLEAR, end="")
    print(f"{BOLD}PROTOTYPE — numeric iMessage error terminality{RESET}")
    print(f"{DIM}Does a local numeric error ever justify a second SMS submission?{RESET}\n")
    visible = {
        "elapsed_seconds": state.elapsed_seconds,
        "pinned_row_id": state.pinned_row_id,
        "service": state.service,
        "error": state.error,
        "is_sent": state.is_sent,
        "is_delivered": state.is_delivered,
        "saw_error": state.saw_error,
        "error_codes": list(state.error_codes),
        "verdict": state.verdict.value,
        "sms_authorized": state.sms_authorized,
        "sample_count": state.sample_count,
        "ignored_sample_count": state.ignored_sample_count,
        "last_event": state.last_event,
    }
    print(json.dumps(visible, indent=2))
    print(
        "\n"
        f"{BOLD}[1]{RESET} {DIM}no matching row{RESET}  "
        f"{BOLD}[2]{RESET} {DIM}error 22{RESET}  "
        f"{BOLD}[3]{RESET} {DIM}clear error{RESET}  "
        f"{BOLD}[4]{RESET} {DIM}mark sent{RESET}\n"
        f"{BOLD}[5]{RESET} {DIM}mark delivered{RESET}  "
        f"{BOLD}[t]{RESET} {DIM}finish window{RESET}  "
        f"{BOLD}[r]{RESET} {DIM}reset{RESET}  "
        f"{BOLD}[q]{RESET} {DIM}quit{RESET}"
    )


def next_sample(state: State, **changes: object) -> Sample:
    current_row = state.pinned_row_id or 101
    return Sample(
        elapsed_seconds=state.elapsed_seconds + 0.5,
        row_id=changes.get("row_id", current_row),
        service=str(changes.get("service", state.service or "iMessage")),
        error=int(changes.get("error", state.error or 0)),
        is_sent=bool(changes.get("is_sent", state.is_sent)),
        is_delivered=bool(changes.get("is_delivered", state.is_delivered)),
    )


def main() -> int:
    state = State()
    while True:
        render(state)
        choice = input("\nAction: ").strip().lower()
        if choice == "q":
            return 0
        if choice == "r":
            state = State()
        elif choice == "1":
            state = observe(
                state,
                Sample(state.elapsed_seconds + 0.5, None, None, None, False, False),
            )
        elif choice == "2":
            state = observe(state, next_sample(state, error=22, is_sent=False))
        elif choice == "3":
            state = observe(state, next_sample(state, error=0, is_sent=False))
        elif choice == "4":
            state = observe(state, next_sample(state, error=0, is_sent=True))
        elif choice == "5":
            state = observe(state, next_sample(state, is_sent=True, is_delivered=True))
        elif choice == "t":
            state = finish_window(state)
        else:
            state = State(last_event=f"unknown action: {choice!r}")


if __name__ == "__main__":
    raise SystemExit(main())
