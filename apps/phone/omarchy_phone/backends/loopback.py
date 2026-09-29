"""Loopback backend: calls between local daemon instances over 127.0.0.1.

For development and tests only; carries signalling, not media. Each instance registers
`<dir>/<profile>.json` = {"port", "number", "name"} so peers can be dialled as `loop:<profile>`
or by their number. Messages are single JSON datagrams:

  invite {call, from, display, video}   ringing {call}   answer {call, video}
  bye {call, reason}   hold {call, on}   video {call, on}   conf {call, participants}

Also provides a virtual peer `loop:echo` (answers after a short delay, accepts every
operation) so a single instance can demo the whole in-call UI.
"""
from __future__ import annotations

import json
import os
import socket

from gi.repository import GLib

from .base import Backend, BackendError

ECHO = "loop:echo"


def default_dir() -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/omarchy-phone-{os.getuid()}"
    return os.path.join(base, "omarchy-phone-loopback")


class LoopbackBackend(Backend):
    id = "loopback"
    name = "Loopback (local test)"
    capabilities = frozenset({"video", "hold", "group", "dtmf", "voicemail"})

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.profile = self.config.get("profile", "default")
        self.number = self.config.get("number", "")
        self.display = self.config.get("display", self.profile)
        self.dir = self.config.get("dir") or default_dir()
        self.echo_delay_ms = int(self.config.get("echo_delay_ms", 800))
        self.sock: socket.socket | None = None
        self.peers: dict[str, tuple[str, int]] = {}   # call_id -> peer address
        self._watch = 0

    # ------------------------------------------------------------ lifecycle
    def start(self, emit):
        super().start(emit)
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        port = self.sock.getsockname()[1]
        tmp = self._reg_path(self.profile) + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"port": port, "number": self.number, "name": self.display, "pid": os.getpid()}, f)
        os.replace(tmp, self._reg_path(self.profile))
        self._watch = GLib.io_add_watch(self.sock.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_readable)
        emit({"type": "registration", "ok": True, "detail": f"loop:{self.profile} on 127.0.0.1:{port}"})

    def stop(self):
        for call_id in list(self.peers):
            self._send(call_id, {"t": "bye", "reason": "normal"})
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = 0
        if self.sock:
            self.sock.close()
            self.sock = None
        try:
            os.unlink(self._reg_path(self.profile))
        except FileNotFoundError:
            pass

    def _reg_path(self, profile: str) -> str:
        return os.path.join(self.dir, f"{profile}.json")

    # ------------------------------------------------------------ discovery
    def directory(self) -> list[dict]:
        out = []
        try:
            names = sorted(os.listdir(self.dir))
        except FileNotFoundError:
            return out
        for fn in names:
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn)) as f:
                    info = json.load(f)
            except (OSError, ValueError):
                continue
            info["profile"] = fn[:-5]
            out.append(info)
        return out

    def _resolve(self, address: str) -> tuple[str, int] | None:
        for info in self.directory():
            if info["profile"] == self.profile:
                continue
            if address in (f"loop:{info['profile']}", info.get("number")):
                return ("127.0.0.1", int(info["port"]))
        return None

    def owns(self, address: str) -> bool:
        return address == ECHO or address.startswith("loop:") or self._resolve(address) is not None

    # ------------------------------------------------------------ wire
    def _send(self, call_id: str, msg: dict, addr=None):
        addr = addr or self.peers.get(call_id)
        if not addr or not self.sock or addr == "echo":
            return
        msg = dict(msg, call=call_id)
        try:
            self.sock.sendto(json.dumps(msg).encode(), addr)
        except OSError:
            self.emit({"type": "ended", "call_id": call_id, "reason": "failed"})

    def _on_readable(self, *_):
        while self.sock:
            try:
                data, addr = self.sock.recvfrom(65536)
            except BlockingIOError:
                break
            except OSError:
                break
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            self._handle(msg, addr)
        return True

    def _handle(self, msg: dict, addr):
        t, cid = msg.get("t"), msg.get("call")
        if not cid:
            return
        if t == "invite":
            self.peers[cid] = addr
            self._send(cid, {"t": "ringing"})
            self.emit({"type": "incoming", "call_id": cid, "remote": msg.get("from", ""),
                       "display_name": msg.get("display", ""), "video": bool(msg.get("video"))})
            return
        if cid not in self.peers:
            return
        if t == "ringing":
            self.emit({"type": "state", "call_id": cid, "state": "ringing"})
        elif t == "answer":
            self.emit({"type": "state", "call_id": cid, "state": "active"})
            if msg.get("video"):
                self.emit({"type": "video", "call_id": cid, "on": True})
        elif t == "bye":
            self.peers.pop(cid, None)
            self.emit({"type": "ended", "call_id": cid, "reason": msg.get("reason", "normal")})
        elif t == "hold":
            self.emit({"type": "state", "call_id": cid, "state": "remote_held" if msg.get("on") else "active"})
        elif t == "video":
            self.emit({"type": "video", "call_id": cid, "on": bool(msg.get("on"))})
        elif t == "conf":
            self.emit({"type": "participants", "call_id": cid, "participants": msg.get("participants", [])})

    # ------------------------------------------------------------ operations
    def dial(self, call_id, address, video=False):
        self.emit({"type": "state", "call_id": call_id, "state": "dialing"})
        if address == ECHO:
            self.peers[call_id] = "echo"
            GLib.timeout_add(self.echo_delay_ms // 2, self._echo, call_id, "ringing", video)
            GLib.timeout_add(self.echo_delay_ms, self._echo, call_id, "active", video)
            return
        peer = self._resolve(address)
        if peer is None:
            raise BackendError(f"no loopback peer for {address}")
        self.peers[call_id] = peer
        self._send(call_id, {"t": "invite", "from": self.number or f"loop:{self.profile}",
                             "display": self.display, "video": video})

    def _echo(self, call_id, state, video):
        if call_id in self.peers:
            self.emit({"type": "state", "call_id": call_id, "state": state})
            if state == "active" and video:
                self.emit({"type": "video", "call_id": call_id, "on": True})
        return False

    def answer(self, call_id, video=False):
        if call_id not in self.peers:
            raise BackendError("no such call")
        self._send(call_id, {"t": "answer", "video": video})
        self.emit({"type": "state", "call_id": call_id, "state": "active"})

    def hangup(self, call_id, reason="normal"):
        self._send(call_id, {"t": "bye", "reason": reason})
        if self.peers.pop(call_id, None) is not None or reason != "normal":
            self.emit({"type": "ended", "call_id": call_id, "reason": reason})

    def set_hold(self, call_id, on):
        self._send(call_id, {"t": "hold", "on": on})
        self.emit({"type": "state", "call_id": call_id, "state": "held" if on else "active"})

    def set_video(self, call_id, on):
        self._send(call_id, {"t": "video", "on": on})
        self.emit({"type": "video", "call_id": call_id, "on": on})

    def merge(self, conference_id, call_ids):
        for cid in call_ids:
            others = [c for c in call_ids if c != cid]
            self._send(cid, {"t": "conf", "participants": others, "conference": conference_id})

    # ------------------------------------------------------------ test helpers
    def simulate_incoming(self, call_id: str, remote: str, display: str = "", video: bool = False):
        """Pretend a call arrived from `remote` (no peer; answering it behaves like the echo peer)."""
        self.peers[call_id] = "echo"
        self.emit({"type": "incoming", "call_id": call_id, "remote": remote,
                   "display_name": display, "video": video})
