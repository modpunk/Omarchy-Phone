"""CallManager: call state machine, screening, history, notifications and audio policy.

Backends report protocol events; the CallManager decides what they mean for the user.
Everything the UI needs is published through `emit(event)` (the daemon turns that into the
D-Bus `Event` signal).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

from . import numbers, screening
from .backends import Backend, BackendError

LIVE = ("dialing", "ringing", "incoming", "active", "held", "remote_held")


@dataclass
class Call:
    id: str
    remote: str
    name: str
    direction: str                 # in | out
    backend: str
    state: str = "dialing"
    video: bool = False
    muted: bool = False
    held: bool = False
    silent: bool = False           # screened to "silent": shown, not rung
    screening: dict = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    answered: float | None = None
    conference: str | None = None
    participants: list = field(default_factory=list)
    contact_id: int | None = None

    def to_dict(self):
        d = asdict(self)
        d["display"] = numbers.format_number(self.remote) if self.remote.startswith("+") else self.remote
        return d


class CallManager:
    def __init__(self, store, backends: list[Backend], notifier=None, audio=None, emit=None):
        self.store = store
        self.backends = {b.id: b for b in backends}
        self.notifier = notifier
        self.audio = audio
        self.emit = emit or (lambda ev: None)
        self.calls: dict[str, Call] = {}
        self.registration: dict[str, dict] = {}
        self.speaker = False
        for b in backends:
            b.start(lambda ev, b=b: self._on_backend(b, ev))

    def stop(self):
        for b in self.backends.values():
            b.stop()

    # ------------------------------------------------------------ helpers
    def _publish(self, call: Call, kind="call"):
        self.emit({"type": kind, "call": call.to_dict()})

    def _who(self, remote: str) -> tuple[str, int | None]:
        c = self.store.contact_for_number(remote)
        if c:
            return c.display_name(), c.id
        return (numbers.format_number(remote, self.store.get("region")) if remote.startswith("+") else remote), None

    def live_calls(self) -> list[Call]:
        return [c for c in self.calls.values() if c.state in LIVE]

    def state(self) -> dict:
        return {"calls": [c.to_dict() for c in self.live_calls()], "speaker": self.speaker,
                "registration": self.registration, "dnd": bool(self.store.get("dnd")),
                "backends": [{"id": b.id, "name": b.name, "capabilities": sorted(b.capabilities)}
                             for b in self.backends.values()]}

    def _backend_for(self, address: str) -> Backend:
        preferred = self.store.get("backend")
        order = sorted(self.backends.values(), key=lambda b: b.id != preferred)
        for b in order:
            if b.owns(address):
                return b
        raise BackendError(f"no backend can reach {address}")

    def _get(self, call_id: str) -> Call:
        c = self.calls.get(call_id)
        if c is None or c.state not in LIVE:
            raise KeyError(f"no live call {call_id}")
        return c

    def _hold_others(self, keep: str, conference: str | None = None):
        for c in self.live_calls():
            if c.id != keep and c.state == "active" and (conference is None or c.conference != conference):
                self.hold(c.id, True)

    # ------------------------------------------------------------ user operations
    def dial(self, address: str, video: bool = False) -> dict:
        region = self.store.get("region")
        addr = numbers.normalize_address(address, region) or (address.strip() if address.strip().startswith(
            "loop:") else None)
        if not addr:
            raise ValueError(f"not a callable number or address: {address!r}")
        backend = self._backend_for(addr)
        name, cid = self._who(addr)
        call = Call(id=uuid.uuid4().hex[:12], remote=addr, name=name, direction="out", backend=backend.id,
                    video=video and backend.can("video"), contact_id=cid)
        self.calls[call.id] = call
        self._hold_others(call.id)
        self.store.log_call(call_id=call.id, remote=addr, name=name, direction="out", started=call.started,
                            status="calling", video=int(call.video), backend=backend.id)
        try:
            backend.dial(call.id, addr, video=call.video)
        except BackendError as e:
            self._end(call, "failed", str(e))
            raise
        self._publish(call)
        return call.to_dict()

    def answer(self, call_id: str, video: bool = False):
        call = self._get(call_id)
        if call.direction != "in" or call.state != "incoming":
            raise ValueError("call is not ringing")
        self._hold_others(call_id)
        b = self.backends[call.backend]
        call.video = video and b.can("video")
        b.answer(call_id, video=call.video)
        if self.audio:
            self.audio.ring(False)
        if self.notifier:
            self.notifier.close(call_id)

    def decline(self, call_id: str, to_voicemail: bool = False):
        call = self._get(call_id)
        b = self.backends[call.backend]
        call.screening = call.screening or {}
        if to_voicemail and b.can("voicemail"):
            call.screening["user"] = "voicemail"
            b.divert_to_voicemail(call_id)
        else:
            call.screening["user"] = "declined"
            b.hangup(call_id, "busy" if call.state == "incoming" else "normal")

    def hangup(self, call_id: str):
        call = self._get(call_id)
        if call.conference:
            for c in self.live_calls():
                if c.conference == call.conference:
                    self.backends[c.backend].hangup(c.id, "normal")
            return
        self.backends[call.backend].hangup(call_id, "busy" if call.state == "incoming" else "normal")

    def hold(self, call_id: str, on: bool):
        call = self._get(call_id)
        if on == call.held:
            return
        if not on:
            self._hold_others(call_id, call.conference)
        members = [c for c in self.live_calls() if call.conference and c.conference == call.conference] or [call]
        for c in members:
            self.backends[c.backend].set_hold(c.id, on)
            c.held = on
            self._publish(c)

    def mute(self, call_id: str | None, on: bool):
        targets = [self._get(call_id)] if call_id else self.live_calls()
        for c in targets:
            if c.muted != on:
                self.backends[c.backend].set_mute(c.id, on)
                c.muted = on
                self._publish(c)

    def video(self, call_id: str, on: bool):
        call = self._get(call_id)
        b = self.backends[call.backend]
        if on and not b.can("video"):
            raise BackendError(f"{b.name} cannot do video")
        b.set_video(call_id, on)

    def dtmf(self, call_id: str, digits: str):
        call = self._get(call_id)
        self.backends[call.backend].send_dtmf(call_id, "".join(d for d in digits if d in "0123456789*#ABCD"))

    def merge(self, call_ids: list[str] | None = None) -> str:
        """Join calls (default: every active/held call) into one group call."""
        calls = [self._get(c) for c in call_ids] if call_ids else [
            c for c in self.live_calls() if c.state in ("active", "held", "remote_held")]
        if len(calls) < 2:
            raise ValueError("need at least two connected calls to merge")
        if len({c.backend for c in calls}) != 1:
            raise BackendError("calls on different services cannot be merged")
        b = self.backends[calls[0].backend]
        if not b.can("group"):
            raise BackendError(f"{b.name} cannot do group calls")
        conf = next((c.conference for c in calls if c.conference), None) or "conf-" + uuid.uuid4().hex[:8]
        b.merge(conf, [c.id for c in calls])
        for c in calls:
            c.conference = conf
            if c.held:
                b.set_hold(c.id, False)
                c.held = False
            c.participants = [o.name for o in calls if o.id != c.id]
            self.store.update_call(c.id, conference=conf)
            self._publish(c)
        self.emit({"type": "conference", "conference": conf, "calls": [c.id for c in calls]})
        return conf

    def split(self, call_id: str):
        call = self._get(call_id)
        conf = call.conference
        call.conference = None
        self.backends[call.backend].split(call_id)
        self._hold_others(call_id)
        self._publish(call)
        rest = [c for c in self.live_calls() if c.conference == conf]
        if len(rest) == 1:
            rest[0].conference = None
            self._publish(rest[0])

    def set_speaker(self, on: bool) -> dict | None:
        self.speaker = on
        route = None
        if self.audio:
            route = self.audio.route_kind("speaker" if on else "earpiece")
        self.emit({"type": "audio", "speaker": on, "route": route})
        return route

    def set_route(self, route_id: int) -> dict:
        route = self.audio.set_route(route_id)
        self.speaker = route["kind"] == "speaker"
        self.emit({"type": "audio", "speaker": self.speaker, "route": route})
        return route

    # ------------------------------------------------------------ backend events
    def _on_backend(self, backend: Backend, ev: dict):
        t = ev.get("type")
        if t == "registration":
            self.registration[backend.id] = {"ok": ev.get("ok"), "detail": ev.get("detail", "")}
            self.emit({"type": "registration", "backend": backend.id, **self.registration[backend.id]})
            return
        if t == "error":
            self.emit({"type": "error", "backend": backend.id, "detail": ev.get("detail", "")})
            return
        if t == "incoming":
            self._incoming(backend, ev)
            return
        call = self.calls.get(ev.get("call_id", ""))
        if call is None:
            return
        if t == "state":
            st = ev["state"]
            if st == "active" and call.answered is None:
                call.answered = time.time()
                self.store.update_call(call.id, answered=call.answered, status="answered")
            if st in ("held", "active") and call.state != "incoming":
                call.held = st == "held"
            if call.state == "incoming" and st in ("ringing", "dialing"):
                return  # our own ringing echo
            call.state = st
            self._publish(call)
        elif t == "video":
            call.video = bool(ev.get("on"))
            self.store.update_call(call.id, video=int(call.video))
            self._publish(call)
        elif t == "participants":
            call.participants = [self._who(p)[0] if isinstance(p, str) and p.startswith("+") else p
                                 for p in ev.get("participants", [])]
            self._publish(call)
        elif t == "ended":
            self._end(call, ev.get("reason", "normal"))

    def _screen_context(self, remote: str) -> screening.Context:
        contact = self.store.contact_for_number(remote)
        lists = self.store.list_entries()
        s = self.store.settings()
        return screening.Context(
            settings=s,
            allow=[e["pattern"] for e in lists if e["kind"] == "allow"],
            block=[(e["pattern"], e["action"] or screening.REJECT) for e in lists if e["kind"] == "block"],
            spam=[e["pattern"] for e in lists if e["kind"] == "spam"],
            is_contact=contact is not None,
            is_favorite=bool(contact and contact.favorite),
            contact_groups=contact.groups if contact else [],
            allowed_groups=s.get("dnd_allowed_groups", []) or [],
            recent_calls=self.store.recent_calls_from(remote, time.time() - screening.REPEAT_WINDOW),
        )

    def _incoming(self, backend: Backend, ev: dict):
        region = self.store.get("region")
        raw = ev.get("remote", "")
        if raw.lower().startswith("sip:") and "@" in raw:
            user = raw[4:].split("@", 1)[0]
            remote = numbers.normalize(user, region) or raw
        else:
            remote = numbers.normalize_address(raw, region) or raw
        name, cid = self._who(remote) if remote else ("Unknown", None)
        if cid is None and ev.get("display_name"):
            name = ev["display_name"]  # caller-supplied and unverified; the UI always shows the number too
        decision = screening.screen(remote, self._screen_context(remote))
        call = Call(id=ev["call_id"], remote=remote, name=name or "Unknown", direction="in",
                    backend=backend.id, state="incoming", video=bool(ev.get("video")),
                    screening=decision.to_dict(), contact_id=cid, silent=decision.action == screening.SILENT)
        self.calls[call.id] = call
        self.store.log_call(call_id=call.id, remote=remote, name=call.name, direction="in",
                            started=call.started, status="ringing", reason=decision.reason,
                            video=int(call.video), backend=backend.id)
        if decision.action == screening.REJECT:
            call.screening["user"] = "blocked"
            backend.hangup(call.id, "busy")
            return
        if decision.action == screening.VOICEMAIL:
            call.screening["user"] = "screened"
            backend.divert_to_voicemail(call.id)
            return
        busy = len(self.live_calls()) > 1
        if self.audio and not call.silent and not busy:
            self.audio.ring(True)
        if self.notifier:
            self.notifier.incoming(call.id, call.name, decision.reason or (
                "Call waiting" if busy else ""), silent=call.silent)
        self._publish(call, "incoming")

    def _end(self, call: Call, reason: str, detail: str = ""):
        prev = call.state
        call.state = "ended"
        user = (call.screening or {}).get("user")
        if call.direction == "in":
            if call.answered:
                status = "answered"
            elif user == "blocked":
                status = "blocked"
            elif user == "screened" or reason == "voicemail":
                status = "voicemail"
            elif user == "declined":
                status = "rejected"
            else:
                status = "missed"
        else:
            status = "answered" if call.answered else {"busy": "busy", "rejected": "rejected",
                                                       "voicemail": "voicemail", "failed": "failed",
                                                       "no_answer": "no_answer"}.get(reason, "cancelled")
        self.store.update_call(call.id, ended=time.time(), status=status)
        if self.notifier:
            self.notifier.close(call.id)
            if status == "missed" and not call.silent:
                self.notifier.missed(call.remote, call.name)
            elif status in ("missed", "voicemail", "blocked") and call.screening.get("reason"):
                self.notifier.screened(call.remote, call.name, f"{call.screening['reason']} · {status}")
        if self.audio and prev == "incoming":
            self.audio.ring(False)
        if call.conference:
            rest = [c for c in self.live_calls() if c.conference == call.conference]
            for c in rest:
                c.participants = [p for p in c.participants if p != call.name]
                if len(rest) == 1:
                    c.conference = None
                self._publish(c)
        self.emit({"type": "ended", "call": dict(call.to_dict(), status=status, reason=reason, detail=detail)})
        if not self.live_calls():
            self.speaker = False
            if self.audio:
                self.audio.restore()
        del self.calls[call.id]

    # ------------------------------------------------------------ notification actions
    def notification_action(self, key: str, action: str):
        try:
            if key.startswith("missed:") or key.startswith("screened:"):
                remote = key.split(":", 1)[1]
                if action == "callback":
                    self.dial(remote)
                elif action == "allow":
                    self.store.add_list_entry("allow", remote, note="from notification")
                elif action == "default":
                    self.emit({"type": "show", "page": "recents"})
                return
            if action == "answer":
                self.answer(key)
            elif action == "decline":
                self.decline(key)
            elif action == "voicemail":
                self.decline(key, to_voicemail=True)
            elif action == "default":
                self.emit({"type": "show", "page": "incoming", "call_id": key})
        except (KeyError, ValueError, BackendError) as e:
            self.emit({"type": "error", "detail": str(e)})

    # ------------------------------------------------------------ test hook
    def simulate_incoming(self, remote: str, display: str = "", video: bool = False) -> str:
        b = self.backends.get("loopback")
        if b is None:
            raise BackendError("simulate_incoming needs the loopback backend")
        cid = "sim-" + uuid.uuid4().hex[:8]
        b.simulate_incoming(cid, remote, display, video)
        return cid
