"""SIP backend: drives a baresip process through its `ctrl_tcp` module.

baresip (https://github.com/baresip/baresip) runs as a separate process with its own SIP
account config. It must load `account`, `menu` and `ctrl_tcp` (every ctrl_tcp command is a
`menu` command; without `menu` there are no commands at all), plus audio modules (`pipewire` on a
desktop; `ausine`/`aufile` in the test bed). We connect to 127.0.0.1:4444 (config `host`/`port`,
or `OMARCHY_PHONE_BARESIP=host:port`) and exchange netstring-framed JSON:

  -> {"command": "dial", "params": "+16465550102", "token": "7"}
  <- {"event": true, "class": "call", "type": "CALL_OUTGOING", "id": "0591cf12f5608457", ...}
  <- {"response": true, "ok": true, "data": "call uri: ...\ncall id: 0591cf12f5608457\n", "token": "7"}

Verified against baresip 4.11 + Asterisk 20 (tests/test_sip.py, tests/sipbed/). Protocol facts
that shaped this adapter:
- `accept`, `hangup`, `hold`, `resume` take the baresip call id as their first word; `mute`,
  `sndcode` and `videodir` act on the menu's current call, so `callfind <id>` selects it first.
- `hangup <id> scode=486 reason=Busy`: key=value parameters; `reason` cannot contain spaces.
- `mute true|false` is explicit (a bare `mute` toggles).
- `CALL_HOLD` / `CALL_RESUME` are reported on the side that was put on hold, never to the holder.
- An incoming call's `CALL_REMOTE_SDP` arrives before its `CALL_INCOMING`.
- A second hold/resume sent while the first re-INVITE is still in flight is answered ok but
  silently lost (the two ends disagree afterwards), so hold changes are serialized per call.
- The menu has no conference command, so group calls are not offered on this backend.
"""
from __future__ import annotations

import json
import os
import re
import socket
import time

from gi.repository import GLib

from .base import Backend, BackendError

COMMANDS = {
    "dial": "dial", "dial_video": "dialdir", "accept": "accept", "accept_video": "acceptdir",
    "hangup": "hangup", "hold": "hold", "resume": "resume", "mute": "mute", "select": "callfind",
    "video_dir": "videodir", "dtmf": "sndcode", "transfer": "transfer",
}
EVENT_STATES = {
    "CALL_OUTGOING": "dialing", "CALL_RINGING": "ringing", "CALL_PROGRESS": "ringing",
    "CALL_ESTABLISHED": "active",
}
# SIP status / Q.850 cause (as baresip reports them in CALL_CLOSED) -> our end reasons
_BUSY = re.compile(r"\b(486|600)\b|busy|cause=17\b", re.I)
_REJECTED = re.compile(r"\b(603|403|503)\b|declin|reject|cause=21\b", re.I)
_NO_ANSWER = re.compile(r"\b(408|480|487)\b|timeout|cause=(18|19)\b", re.I)
_FAILED = re.compile(r"\b(404|484|488|5\d\d)\b|cause=(1|3|28|38|127)\b", re.I)


def close_reason(param: str, local: bool) -> str:
    """Map baresip's CALL_CLOSED text (e.g. '486 Busy Here,Q.850;cause=17') to an end reason."""
    if local:  # our own hangup: baresip reports the reason we sent ('Busy', 'Decline', 'Rejected by user')
        return "normal"
    for rx, reason in ((_BUSY, "busy"), (_REJECTED, "rejected"), (_NO_ANSWER, "no_answer"), (_FAILED, "failed")):
        if rx.search(param or ""):
            return reason
    return "normal"


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
    capabilities = frozenset({"video", "hold", "dtmf", "voicemail", "transfer"})

    def __init__(self, config=None):
        super().__init__(config)
        env_host, _, env_port = os.environ.get("OMARCHY_PHONE_BARESIP", "").rpartition(":")
        self.host = self.config.get("host") or env_host or "127.0.0.1"
        self.port = int(self.config.get("port") or env_port or 4444)
        self.voicemail_uri = self.config.get("voicemail_uri", "")
        self.sock: socket.socket | None = None
        self.buf = b""
        self.token = 0
        self.ours: dict[str, str] = {}      # our call_id -> baresip call id
        self.theirs: dict[str, str] = {}    # baresip call id -> our call_id
        self.pending_out: list[str] = []    # dialled, baresip has not reported the call yet
        self.dial_tokens: dict[str, str] = {}   # command token -> our call_id
        self.hangup_early: set[str] = set()  # hung up before baresip reported the call
        self.local_hold: set[str] = set()
        self.remote_hold: set[str] = set()
        self.established: set[str] = set()
        self.video_on: dict[str, bool] = {}
        self.closing: set[str] = set()      # we hung up; CALL_CLOSED is our own doing
        self.want_hold: dict[str, bool] = {}   # hold state the user asked for
        self.sent_hold: dict[str, bool] = {}   # hold state last sent to baresip
        self.reinvite: dict[str, float] = {}   # our re-INVITE in flight since (monotonic)
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
        if data:
            self.feed(data)
        if not data or cond & GLib.IO_HUP:
            self._watch = 0
            self.stop()
            for cid in list(self.ours) + self.pending_out:
                self.emit({"type": "ended", "call_id": cid, "reason": "failed"})
            self._forget_all()
            self.emit({"type": "registration", "ok": False, "detail": "baresip connection lost"})
            self._retry = GLib.timeout_add_seconds(5, self._connect)
            return False
        return True

    def _forget_all(self):
        for coll in (self.ours, self.theirs, self.dial_tokens, self.video_on, self.want_hold, self.sent_hold,
                     self.reinvite):
            coll.clear()
        for coll in (self.hangup_early, self.local_hold, self.remote_hold, self.established, self.closing):
            coll.clear()
        self.pending_out.clear()
        self.buf = b""

    def feed(self, data: bytes):
        msgs, self.buf = parse_netstrings(self.buf + data)
        for m in msgs:
            try:
                ev = json.loads(m)
            except ValueError:
                continue
            if isinstance(ev, dict):
                self.handle(ev)

    def command(self, name: str, params: str = "") -> str:
        if not self.sock:
            raise BackendError("baresip is not running")
        self.token += 1
        msg = {"command": COMMANDS.get(name, name), "params": params, "token": str(self.token)}
        self.sock.sendall(netstring(json.dumps(msg).encode()))
        return str(self.token)

    def _bid(self, call_id: str) -> str:
        bid = self.ours.get(call_id)
        if not bid:
            raise BackendError(f"baresip has no call for {call_id}")
        return bid

    def _on_current(self, call_id: str, name: str, params: str = ""):
        """For commands without a call-id slot: select the call, then run the command."""
        self.command("select", self._bid(call_id))
        self.command(name, params)

    def _map(self, bid: str, cid: str):
        self.theirs[bid], self.ours[cid] = cid, bid

    def _forget(self, cid: str):
        bid = self.ours.pop(cid, None)
        self.theirs.pop(bid, None)
        for coll in (self.local_hold, self.remote_hold, self.established, self.closing):
            coll.discard(cid)
        for coll in (self.video_on, self.want_hold, self.sent_hold, self.reinvite):
            coll.pop(cid, None)

    def _held_state(self, cid: str) -> str:
        return "held" if cid in self.local_hold else "remote_held" if cid in self.remote_hold else "active"

    # ------------------------------------------------------------ events
    def handle(self, ev: dict):
        if ev.get("response"):
            self._on_response(ev)
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
            if et == "CALL_INCOMING":
                cid = "sip-" + bid
                self._map(bid, cid)
                self.emit({"type": "incoming", "call_id": cid, "remote": ev.get("peeruri", ""),
                           "display_name": ev.get("peerdisplayname", ""),
                           "video": ev.get("remotevideodir", "inactive") != "inactive"})
                return
            if et == "CALL_OUTGOING" and ev.get("direction") == "outgoing" and self.pending_out:
                cid = self.pending_out.pop(0)
                self._map(bid, cid)
                if cid in self.hangup_early:
                    self.hangup_early.discard(cid)
                    self.closing.add(cid)
                    self.command("hangup", bid)
            else:
                return  # not ours (e.g. the SDP that precedes CALL_INCOMING, or a call made elsewhere)
        if et in EVENT_STATES:
            if et == "CALL_ESTABLISHED":
                self.established.add(cid)
            elif ev.get("direction") == "incoming":
                return  # our own ringing on an incoming call
            self.emit({"type": "state", "call_id": cid, "state": EVENT_STATES[et]})
        elif et in ("CALL_HOLD", "CALL_RESUME"):  # the peer put us on hold / took us off it
            (self.remote_hold.add if et == "CALL_HOLD" else self.remote_hold.discard)(cid)
            self.emit({"type": "state", "call_id": cid, "state": self._held_state(cid)})
        elif et == "CALL_CLOSED":
            local = cid in self.closing
            self._forget(cid)
            self.emit({"type": "ended", "call_id": cid, "reason": close_reason(ev.get("param", ""), local)})
        elif et == "CALL_REMOTE_SDP" and cid in self.established:
            if ev.get("param") == "answer" and cid in self.reinvite:
                self._reinvite_done(cid)
            on = ev.get("remotevideodir", "inactive") != "inactive"
            if self.video_on.get(cid, False) != on:
                self.video_on[cid] = on
                self.emit({"type": "video", "call_id": cid, "on": on})
        elif et == "CALL_DTMF_START" and ev.get("param"):
            self.emit({"type": "dtmf", "call_id": cid, "digit": ev["param"]})

    def _on_response(self, ev: dict):
        cid = self.dial_tokens.pop(str(ev.get("token", "")), None)
        if ev.get("ok"):
            return
        detail = (ev.get("data") or "").strip() or "baresip command failed"
        if cid and cid in self.pending_out:  # the dial never became a call
            self.pending_out.remove(cid)
            self.hangup_early.discard(cid)
            self.emit({"type": "ended", "call_id": cid, "reason": "failed"})
        self.emit({"type": "error", "detail": detail})

    # ------------------------------------------------------------ operations
    def dial(self, call_id, address, video=False):
        # A bare number or extension is completed by baresip with the account's domain
        # (+16465550102 -> sip:+16465550102@pbx); URIs go through unchanged.
        target = address.strip()
        if any(c.isspace() for c in target):
            raise BackendError(f"not a SIP address: {address!r}")
        self.pending_out.append(call_id)
        try:
            if video:
                tok = self.command("dial_video", f"{target} audio=sendrecv video=sendrecv")
            else:
                tok = self.command("dial", target)
        except (BackendError, OSError) as e:
            self.pending_out.remove(call_id)
            raise BackendError(str(e)) from e
        self.dial_tokens[tok] = call_id
        self.emit({"type": "state", "call_id": call_id, "state": "dialing"})

    def answer(self, call_id, video=False):
        bid = self._bid(call_id)
        if video:
            self.command("accept_video", f"audio=sendrecv video=sendrecv callid={bid}")
        else:
            self.command("accept", bid)

    def hangup(self, call_id, reason="normal"):
        bid = self.ours.get(call_id)
        if not bid:
            if call_id in self.pending_out:
                self.hangup_early.add(call_id)  # hang up as soon as baresip reports it
                return
            raise BackendError(f"baresip has no call for {call_id}")
        self.closing.add(call_id)
        # for an unanswered incoming call the status code is what the caller sees
        params = {"busy": "scode=486 reason=Busy", "rejected": "scode=603 reason=Decline",
                  "voicemail": "scode=486 reason=Busy"}.get(reason, "")
        self.command("hangup", " ".join(p for p in (bid, params) if p))

    def divert_to_voicemail(self, call_id):
        # ctrl_tcp cannot redirect (302) a ringing call; busy is what PBXs forward to voicemail.
        if self.voicemail_uri and call_id in self.established:
            self._on_current(call_id, "transfer", self.voicemail_uri)
            return
        self.hangup(call_id, "voicemail")

    def set_hold(self, call_id, on):
        self._bid(call_id)
        self.want_hold[call_id] = on
        (self.local_hold.add if on else self.local_hold.discard)(call_id)
        self._push_hold(call_id)
        self.emit({"type": "state", "call_id": call_id, "state": self._held_state(call_id)})

    def _push_hold(self, call_id):
        """Send the wanted hold state unless our previous re-INVITE is still waiting for its answer."""
        started = self.reinvite.get(call_id)
        if started is not None and time.monotonic() - started < 4:
            return
        want = self.want_hold.get(call_id)
        if want is None or want == self.sent_hold.get(call_id, False) or call_id not in self.ours:
            return
        self.command("hold" if want else "resume", self.ours[call_id])
        self.sent_hold[call_id] = want
        self.reinvite[call_id] = time.monotonic()
        GLib.timeout_add(4500, self._reinvite_timeout, call_id, self.reinvite[call_id])

    def _reinvite_done(self, call_id):
        self.reinvite.pop(call_id, None)
        self._push_hold(call_id)

    def _reinvite_timeout(self, call_id, started):
        if self.reinvite.get(call_id) == started:  # no answer came; don't block later changes
            self._reinvite_done(call_id)
        return False

    def set_mute(self, call_id, on):
        self._on_current(call_id, "mute", "true" if on else "false")

    def set_video(self, call_id, on):
        self._on_current(call_id, "video_dir", "sendrecv" if on else "inactive")
        self.video_on[call_id] = on
        self.emit({"type": "video", "call_id": call_id, "on": on})

    def send_dtmf(self, call_id, digits):
        if digits:
            self._on_current(call_id, "dtmf", digits)
