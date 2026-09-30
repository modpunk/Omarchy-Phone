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

Registration state (Registered / Registering / Failed) is tracked two ways, per `docs/phone/API.md`:
event-driven (`REGISTERING`/`REGISTER_OK`/`REGISTER_FAIL`/the `FALLBACK_*` equivalents, all reported
by the `account` module regardless of ctrl_tcp) and on-demand (`reginfo`, a `menu` command that
prints a text dump of every User-Agent's registration; ANSI-colored, so it needs stripping). We send
`reginfo` right after connecting, both to learn the current state without waiting for baresip's next
registration attempt (it may already be registered, e.g. reconnecting to a long-running baresip) and
to decide whether our configured account needs to be created (`uanew`) — baresip has no persistent
knowledge of *our* account across restarts unless it was also written to its accounts file, which we
deliberately don't do (the password would sit in that file in the clear); the account is provisioned
live over ctrl_tcp instead, using the account line from the keyring at daemon startup and whenever it
is saved. Verified against baresip 4.11's `modules/menu/static_menu.c` and `src/reg.c` sources.
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
    "reginfo": "reginfo", "uanew": "uanew", "uadel": "uadel",
}
EVENT_STATES = {
    "CALL_OUTGOING": "dialing", "CALL_RINGING": "ringing", "CALL_PROGRESS": "ringing",
    "CALL_ESTABLISHED": "active",
}
REGISTER_OK = ("REGISTER_OK", "FALLBACK_OK")
REGISTER_FAIL = ("REGISTER_FAIL", "FALLBACK_FAIL")
REGISTER_EVENTS = REGISTER_OK + REGISTER_FAIL + ("REGISTERING", "UNREGISTERING")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# "N - <aor, %-42s padded>  OK  <server, may contain spaces>  Expires 300s" (also "ERR"/"zzz", and
# an "FB-" prefix for a fallback registrar); server is "(nil)" or missing before any attempt.
_REGINFO_LINE = re.compile(r"^\s*\d+\s*-\s*(?P<aor>\S+)\s+(?:FB-)?(?P<code>OK|ERR|zzz)\s*(?P<rest>.*)$")
_EXPIRES = re.compile(r"Expires\s+(\d+)s\s*$")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def parse_reginfo(text: str) -> list[dict]:
    """Parse baresip's `reginfo` text dump into `[{aor, ok, registering, srv, expires}]`."""
    out = []
    for line in strip_ansi(text).splitlines():
        m = _REGINFO_LINE.match(line)
        if not m:
            continue
        rest = m.group("rest").strip()
        expires = None
        em = _EXPIRES.search(rest)
        if em:
            expires = int(em.group(1))
            rest = rest[:em.start()].strip()
        srv = rest if rest and rest != "(nil)" else None
        out.append({"aor": m.group("aor"), "ok": m.group("code") == "OK",
                    "registering": m.group("code") == "zzz", "srv": srv, "expires": expires})
    return out


def line_aor(line: str) -> str:
    """The bare `sip:user@host` baresip reports for an account line (its own params dropped, same
    as `account_aor()`/`encode_uri_user()` in baresip's source: URI params are not part of the AOR)."""
    m = re.search(r"<([^>]+)>", line)
    uri = m.group(1) if m else line.strip()
    return uri.split(";", 1)[0]


# SIP status / Q.850 cause (as baresip reports them in CALL_CLOSED) -> our end reasons
_BUSY = re.compile(r"\b(486|600)\b|busy|cause=17\b", re.I)
_REJECTED = re.compile(r"\b(603|403)\b|declin|reject|cause=21\b", re.I)  # Asterisk: 603 -> 503 cause=21
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
        # account / registration
        self.account_line: str | None = self.config.get("account_line")
        self.account_aor: str | None = line_aor(self.account_line) if self.account_line else None
        self._account_pushed = False        # uanew already sent for the current account_line
        self.control_tokens: dict[str, str] = {}   # token -> "reginfo" | "uanew" | "uadel"
        self.reg_state = "offline"
        self.reg_detail = ""
        self.reg_reason = ""
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

    def owns(self, address):
        return not address.startswith("loop:")  # loopback peers belong to the loopback backend

    # ------------------------------------------------------------ connection
    def start(self, emit):
        super().start(emit)
        self._connect()

    def _connect(self):
        self._retry = 0
        try:
            s = socket.create_connection((self.host, self.port), timeout=1)
        except OSError as e:
            self._reg("offline", detail=f"baresip not reachable: {e}")
            self._retry = GLib.timeout_add_seconds(5, self._connect)
            return False
        s.setblocking(False)
        self.sock = s
        self._watch = GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_io)
        self._account_pushed = False
        self._reg("connecting", detail=f"baresip at {self.host}:{self.port}")
        self.refresh_registration()   # learn the real state instead of assuming "connected" = registered
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
            self._reg("offline", detail="baresip connection lost")
            self._retry = GLib.timeout_add_seconds(5, self._connect)
            return False
        return True

    def _forget_all(self):
        for coll in (self.ours, self.theirs, self.dial_tokens, self.video_on, self.want_hold, self.sent_hold,
                     self.reinvite, self.control_tokens):
            coll.clear()
        for coll in (self.hangup_early, self.local_hold, self.remote_hold, self.established, self.closing):
            coll.clear()
        self.pending_out.clear()
        self.buf = b""
        self._account_pushed = False

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
        if et in REGISTER_EVENTS:
            if et == "REGISTERING":
                self._reg("registering")
            elif et in REGISTER_OK:
                self._account_pushed = True
                self._reg("registered", detail=ev.get("param", ""))
            elif et in REGISTER_FAIL:
                self._reg("failed", reason=ev.get("param", ""))
            # UNREGISTERING: transient (re-registering or shutting down); the next REGISTERING /
            # REGISTER_OK / REGISTER_FAIL that follows is authoritative, so nothing to report yet.
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
        tok = str(ev.get("token", ""))
        kind = self.control_tokens.pop(tok, None)
        if kind in ("reginfo", "uanew"):
            self._on_reginfo(ev.get("data") or "", bool(ev.get("ok")))
            return
        if kind == "uadel":
            return  # nothing to reconcile; a missing/unknown aor is not an error worth surfacing
        cid = self.dial_tokens.pop(tok, None)
        if ev.get("ok"):
            return
        detail = (ev.get("data") or "").strip() or "baresip command failed"
        if cid and cid in self.pending_out:  # the dial never became a call
            self.pending_out.remove(cid)
            self.hangup_early.discard(cid)
            self.emit({"type": "ended", "call_id": cid, "reason": "failed"})
        self.emit({"type": "error", "detail": detail})

    # ------------------------------------------------------------ registration
    def _reg(self, state: str, detail: str = "", reason: str = ""):
        self.reg_state, self.reg_detail = state, detail
        if state == "registered":
            self.reg_reason = ""          # a fresh success clears any earlier failure reason
        elif reason:
            self.reg_reason = reason
        self.emit({"type": "registration", "state": state, "ok": state == "registered",
                   "detail": detail, "reason": self.reg_reason if state == "failed" else ""})

    def _on_reginfo(self, data: str, cmd_ok: bool):
        if not cmd_ok:
            self._reg("failed", reason=data.strip() or "reginfo failed")
            return
        entries = parse_reginfo(data)
        if self.account_aor:  # an account we provisioned: find it by AOR, create it if missing
            mine = next((e for e in entries if e["aor"] == self.account_aor), None)
            if mine is None:
                if not self._account_pushed:
                    self._push_account()
                else:
                    self._reg("registering", detail="waiting for baresip to accept the account")
                return
            self._account_pushed = True
        else:
            # No account of our own configured; still reflect baresip's own state if it already has
            # one (e.g. a hand-written accounts file, or the sipbed test image) rather than lying.
            mine = entries[0] if entries else None
            if mine is None:
                self._reg("no_account", detail="no SIP account configured")
                return
        if mine["ok"]:
            detail = mine["srv"] or ""
            if mine["expires"]:
                detail = f"{detail} · expires {mine['expires']}s" if detail else f"expires {mine['expires']}s"
            self._reg("registered", detail=detail)
        elif mine["registering"]:
            self._reg("registering", detail=mine["srv"] or "")
        else:
            self._reg("failed", detail=mine["srv"] or "", reason=self.reg_reason or "registration rejected")

    def _push_account(self):
        tok = self.command("uanew", self.account_line)
        self.control_tokens[tok] = "uanew"
        self._reg("registering", detail="creating account")

    def refresh_registration(self):
        if not self.sock:
            return
        tok = self.command("reginfo")
        self.control_tokens[tok] = "reginfo"

    def set_account(self, line: str):
        """Provision (or replace) the live account. Persisted only in the keyring/app settings —
        never written to baresip's own accounts file, so this is the only place the account exists
        once phoned restarts (or baresip does); call it again after every daemon start and save."""
        old_aor = self.account_aor
        self.account_line = line
        self.account_aor = line_aor(line)
        self._account_pushed = False
        self.reg_reason = ""
        if not self.sock:
            return  # picked up by the reginfo round trip once we connect
        if old_aor and old_aor != self.account_aor:
            tok = self.command("uadel", old_aor)
            self.control_tokens[tok] = "uadel"
        self._push_account()

    def clear_account(self):
        old_aor = self.account_aor
        self.account_line = None
        self.account_aor = None
        self._account_pushed = False
        self.reg_reason = ""
        if self.sock and old_aor:
            tok = self.command("uadel", old_aor)
            self.control_tokens[tok] = "uadel"
        self._reg("no_account", detail="no SIP account configured")

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
