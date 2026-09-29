"""SIP backend: drives a baresip process through its `ctrl_tcp` module.

baresip (https://github.com/baresip/baresip) runs as a separate process with its own SIP
account config and the `pipewire`, `opus`, `ctrl_tcp` modules loaded. We connect to
127.0.0.1:4444 and exchange netstring-framed JSON:

  -> {"command": "dial", "params": "sip:ana@example.org", "token": "7"}
  <- {"response": true, "ok": true, "data": "", "token": "7"}
  <- {"event": true, "class": "call", "type": "CALL_INCOMING", "id": "...", "peeruri": "...", ...}

Status: written against the documented protocol and unit-tested with a fake server; not yet
run against a real baresip (not installed on the dev machine). Command names differ slightly
between baresip releases; they are collected in COMMANDS so a release difference is a
one-line change.
"""
from __future__ import annotations

import json
import socket

from gi.repository import GLib

from .base import Backend, BackendError

COMMANDS = {
    "dial": "dial", "dial_video": "dialdir", "accept": "accept", "accept_video": "acceptdir",
    "hangup": "hangup", "hold": "hold", "resume": "resume", "mute": "mute", "select": "callfind",
    "video_dir": "video_dir", "dtmf": "sndcode", "conference": "conference",
}
EVENT_STATES = {
    "CALL_OUTGOING": "dialing", "CALL_RINGING": "ringing", "CALL_PROGRESS": "ringing",
    "CALL_ESTABLISHED": "active", "CALL_HOLD": "held", "CALL_RESUME": "active",
}


def netstring(payload: bytes) -> bytes:
    return str(len(payload)).encode() + b":" + payload + b","


def parse_netstrings(buf: bytes) -> tuple[list[bytes], bytes]:
    """Split complete netstrings off `buf`; returns (messages, remainder)."""
    out = []
    while True:
        colon = buf.find(b":")
        if colon <= 0:
            if colon == 0 or (buf and not buf[:12].isdigit()):
                raise ValueError("bad netstring")
            return out, buf
        n = int(buf[:colon])
        end = colon + 1 + n
        if len(buf) < end + 1:
            return out, buf
        if buf[end:end + 1] != b",":
            raise ValueError("bad netstring terminator")
        out.append(buf[colon + 1:end])
        buf = buf[end + 1:]


class BaresipBackend(Backend):
    id = "sip"
    name = "SIP (baresip)"
    capabilities = frozenset({"video", "hold", "group", "dtmf", "voicemail", "transfer"})

    def __init__(self, config=None):
        super().__init__(config)
        self.host = self.config.get("host", "127.0.0.1")
        self.port = int(self.config.get("port", 4444))
        self.voicemail_uri = self.config.get("voicemail_uri", "")
        self.sock: socket.socket | None = None
        self.buf = b""
        self.token = 0
        self.ours: dict[str, str] = {}      # our call_id -> baresip call id
        self.theirs: dict[str, str] = {}    # baresip call id -> our call_id
        self.pending_out: list[str] = []
        self._watch = 0
        self._retry = 0

    # ------------------------------------------------------------ connection
    def start(self, emit):
        super().start(emit)
        self._connect()

    def _connect(self):
        self._retry = 0
        try:
            s = socket.create_connection((self.host, self.port), timeout=1)
        except OSError as e:
            self.emit({"type": "registration", "ok": False, "detail": f"baresip not reachable: {e}"})
            self._retry = GLib.timeout_add_seconds(5, self._connect)
            return False
        s.setblocking(False)
        self.sock = s
        self._watch = GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_io)
        self.emit({"type": "registration", "ok": True, "detail": f"baresip at {self.host}:{self.port}"})
        return False

    def stop(self):
        for src in (self._watch, self._retry):
            if src:
                GLib.source_remove(src)
        self._watch = self._retry = 0
        if self.sock:
            self.sock.close()
            self.sock = None

    def _on_io(self, _fd, cond):
        try:
            data = self.sock.recv(65536) if self.sock else b""
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data or cond & GLib.IO_HUP:
            self._watch = 0
            self.stop()
            for cid in list(self.ours):
                self.emit({"type": "ended", "call_id": cid, "reason": "failed"})
            self.ours.clear()
            self.theirs.clear()
            self._retry = GLib.timeout_add_seconds(5, self._connect)
            return False
        self.feed(data)
        return True

    def feed(self, data: bytes):
        msgs, self.buf = parse_netstrings(self.buf + data)
        for m in msgs:
            try:
                self.handle(json.loads(m))
            except ValueError:
                continue

    def command(self, name: str, params: str = "") -> str:
        if not self.sock:
            raise BackendError("baresip is not running")
        self.token += 1
        msg = {"command": COMMANDS.get(name, name), "params": params, "token": str(self.token)}
        self.sock.sendall(netstring(json.dumps(msg).encode()))
        return str(self.token)

    def _on(self, call_id: str, name: str, params: str = ""):
        bid = self.ours.get(call_id)
        if bid:
            self.command("select", bid)
        self.command(name, params)

    # ------------------------------------------------------------ events
    def handle(self, ev: dict):
        if ev.get("response"):
            if not ev.get("ok"):
                self.emit({"type": "error", "detail": ev.get("data", "")})
            return
        if not ev.get("event"):
            return
        et, bid = ev.get("type", ""), ev.get("id", "")
        if et in ("REGISTER_OK", "REGISTER_FAIL"):
            self.emit({"type": "registration", "ok": et == "REGISTER_OK", "detail": ev.get("param", "")})
            return
        if ev.get("class") != "call" or not bid:
            return
        cid = self.theirs.get(bid)
        if cid is None:
            if et == "CALL_INCOMING" or ev.get("direction") == "incoming":
                cid = "sip-" + bid
            elif self.pending_out:
                cid = self.pending_out.pop(0)
            else:
                return
            self.theirs[bid], self.ours[cid] = cid, bid
            if et == "CALL_INCOMING":
                self.emit({"type": "incoming", "call_id": cid, "remote": ev.get("peeruri", ""),
                           "display_name": ev.get("peerdisplayname", ""),
                           "video": "video" in (ev.get("param") or "")})
                return
        if et in EVENT_STATES:
            self.emit({"type": "state", "call_id": cid, "state": EVENT_STATES[et]})
        elif et == "CALL_CLOSED":
            self.theirs.pop(bid, None)
            self.ours.pop(cid, None)
            param = (ev.get("param") or "").lower()
            reason = "busy" if "busy" in param or "486" in param else "rejected" if "603" in param or "declin" in param \
                else "no_answer" if "408" in param or "timeout" in param else "normal"
            self.emit({"type": "ended", "call_id": cid, "reason": reason})
        elif et == "CALL_REMOTE_SDP" or et == "CALL_VIDEO":
            self.emit({"type": "video", "call_id": cid, "on": "video" in (ev.get("param") or "")})

    # ------------------------------------------------------------ operations
    def dial(self, call_id, address, video=False):
        uri = address if ":" in address else f"sip:{address}"  # E.164 goes to the account's default domain
        self.pending_out.append(call_id)
        if video:
            self.command("dial_video", f"{uri} audio=sendrecv video=sendrecv")
        else:
            self.command("dial", uri)
        self.emit({"type": "state", "call_id": call_id, "state": "dialing"})

    def answer(self, call_id, video=False):
        if video:
            self._on(call_id, "accept_video", "audio=sendrecv video=sendrecv")
        else:
            self._on(call_id, "accept")

    def hangup(self, call_id, reason="normal"):
        bid = self.ours.get(call_id, "")
        # baresip's hangup takes an optional status code for rejecting incoming calls
        params = {"busy": "486 Busy Here", "rejected": "603 Decline"}.get(reason, "")
        self.command("hangup", " ".join(p for p in (bid, params) if p))

    def divert_to_voicemail(self, call_id):
        if not self.voicemail_uri:
            return self.hangup(call_id, "busy")  # most SIP servers forward busy to voicemail
        self._on(call_id, "transfer", self.voicemail_uri)

    def set_hold(self, call_id, on):
        self._on(call_id, "hold" if on else "resume")

    def set_mute(self, call_id, on):
        self._on(call_id, "mute")  # baresip toggles; the CallManager only calls on a real change

    def set_video(self, call_id, on):
        self._on(call_id, "video_dir", "sendrecv" if on else "inactive")
        self.emit({"type": "video", "call_id": call_id, "on": on})

    def send_dtmf(self, call_id, digits):
        for d in digits:
            self._on(call_id, "dtmf", d)

    def merge(self, conference_id, call_ids):
        for cid in call_ids:
            self._on(cid, "conference")
