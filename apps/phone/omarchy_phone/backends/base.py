"""Backend interface. See docs/phone/DESIGN.md section 2.4.

A backend turns protocol traffic into events and executes call operations. It never touches
contacts, screening, history or audio routing; those belong to the CallManager.

Events passed to `emit(event)` (dicts):
  {"type": "incoming", "call_id", "remote", "display_name", "video"}
  {"type": "state", "call_id", "state"}         # dialing|ringing|active|held|remote_held
  {"type": "video", "call_id", "on"}
  {"type": "participants", "call_id", "participants": [..]}
  {"type": "ended", "call_id", "reason"}        # normal|busy|rejected|voicemail|no_answer|failed
  {"type": "registration", "state": str, "ok": bool, "detail": str, "reason": str}
    state one of: connecting (transport up, no verdict yet), no_account (nothing configured),
    registering, registered, failed, offline (not connected). `ok` is `state == "registered"`,
    kept for callers that only care about the boolean. `reason` is set on `failed`.
"""
from __future__ import annotations

from typing import Callable

Emit = Callable[[dict], None]


class BackendError(RuntimeError):
    pass


class Backend:
    id = "base"
    name = "Base"
    capabilities: frozenset[str] = frozenset()

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.emit: Emit = lambda ev: None

    def start(self, emit: Emit) -> None:
        self.emit = emit

    def stop(self) -> None:
        pass

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    def owns(self, address: str) -> bool:
        """Whether this backend can reach `address` (E.164 or URI)."""
        return True

    # Operations; call_id is chosen by the CallManager for outgoing calls.
    def dial(self, call_id: str, address: str, video: bool = False) -> None:
        raise BackendError("dial not supported")

    def answer(self, call_id: str, video: bool = False) -> None:
        raise BackendError("answer not supported")

    def hangup(self, call_id: str, reason: str = "normal") -> None:
        raise BackendError("hangup not supported")

    def divert_to_voicemail(self, call_id: str) -> None:
        self.hangup(call_id, "voicemail")

    def set_hold(self, call_id: str, on: bool) -> None:
        raise BackendError("hold not supported")

    def set_mute(self, call_id: str, on: bool) -> None:
        pass  # muting is always possible locally

    def set_video(self, call_id: str, on: bool) -> None:
        raise BackendError("video not supported")

    def send_dtmf(self, call_id: str, digits: str) -> None:
        pass

    def merge(self, conference_id: str, call_ids: list[str]) -> None:
        raise BackendError("group calls not supported")

    def split(self, call_id: str) -> None:
        pass

    # Account / registration (SIP-like backends; no-ops elsewhere)
    def set_account(self, line: str) -> None:
        """Provision or replace the account. `line` is backend-specific (baresip: an accounts-file
        line); backends that have no account concept ignore this."""
        pass

    def clear_account(self) -> None:
        pass

    def refresh_registration(self) -> None:
        """Ask the backend to re-check its registration state now (in addition to whatever it
        reports on its own); a no-op where there is nothing to check."""
        pass
