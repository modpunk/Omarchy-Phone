"""End-to-end call flows between two (or three) loopback instances in one process.

Signalling really goes over UDP on 127.0.0.1; no accounts, no external services, no media.
"""
import json
import os
import socket
import tempfile
import time
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"

from gi.repository import GLib  # noqa: E402

from omarchy_phone.backends import BackendError  # noqa: E402
from omarchy_phone.backends.baresip import (BaresipBackend, line_aor, netstring,  # noqa: E402
                                            parse_netstrings, parse_reginfo, strip_ansi)
from omarchy_phone.backends.loopback import LoopbackBackend  # noqa: E402
from omarchy_phone.calls import CallManager  # noqa: E402
from omarchy_phone.store import Store  # noqa: E402
from omarchy_phone.vcard import Contact  # noqa: E402

ALICE, BOB, CAROL = "+12125550101", "+16465550102", "+13125550103"


def spin(cond, timeout=2.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class Phone:
    def __init__(self, tmp, profile, number):
        self.store = Store(os.path.join(tmp, f"{profile}.db"))
        self.store.set("own_number", number)
        self.events = []
        self.backend = LoopbackBackend({"profile": profile, "number": number, "dir": os.path.join(tmp, "reg"),
                                        "echo_delay_ms": 20})
        self.mgr = CallManager(self.store, [self.backend], emit=self.events.append)

    def call(self):
        [c] = self.mgr.live_calls()
        return c

    def history(self):
        return self.store.history()


class Flows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Phone(self.tmp.name, "alice", ALICE)
        self.b = Phone(self.tmp.name, "bob", BOB)

    def tearDown(self):
        for p in (self.a, self.b, getattr(self, "c", None)):
            if p:
                p.mgr.stop()
                p.store.close()
        self.tmp.cleanup()

    def test_call_answer_hold_video_hangup(self):
        self.b.store.save_contact(Contact(name="Alice", numbers=[("cell", ALICE)]))
        self.a.mgr.dial("(646) 555-0102")
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        inc = self.b.call()
        self.assertEqual((inc.state, inc.name, inc.remote), ("incoming", "Alice", ALICE))
        self.assertTrue(spin(lambda: self.a.call().state == "ringing"))

        self.b.mgr.answer(inc.id)
        self.assertTrue(spin(lambda: self.a.call().state == "active"))
        self.b.mgr.hold(inc.id, True)
        self.assertTrue(spin(lambda: self.a.call().state == "remote_held"))
        self.b.mgr.hold(inc.id, False)
        self.assertTrue(spin(lambda: self.a.call().state == "active"))

        self.a.mgr.video(self.a.call().id, True)             # voice -> video
        self.assertTrue(spin(lambda: self.b.call().video))
        self.a.mgr.video(self.a.call().id, False)            # and back
        self.assertTrue(spin(lambda: not self.b.call().video))
        self.a.mgr.mute(None, True)
        self.assertTrue(self.a.call().muted)

        self.a.mgr.hangup(self.a.call().id)
        self.assertTrue(spin(lambda: not self.b.mgr.live_calls()))
        self.assertEqual(self.a.history()[0]["status"], "answered")
        self.assertEqual(self.b.history()[0]["status"], "answered")
        self.assertEqual(self.b.history()[0]["direction"], "in")

    def test_missed_and_cancelled(self):
        self.a.mgr.dial("loop:bob")
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        self.a.mgr.hangup(self.a.call().id)
        self.assertTrue(spin(lambda: not self.b.mgr.live_calls()))
        self.assertEqual(self.a.history()[0]["status"], "cancelled")
        self.assertEqual(self.b.history()[0]["status"], "missed")

    def test_decline_and_voicemail(self):
        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        self.b.mgr.decline(self.b.call().id)
        self.assertTrue(spin(lambda: not self.a.mgr.live_calls()))
        self.assertEqual(self.a.history()[0]["status"], "busy")
        self.assertEqual(self.b.history()[0]["status"], "rejected")

        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        self.b.mgr.decline(self.b.call().id, to_voicemail=True)
        self.assertTrue(spin(lambda: not self.a.mgr.live_calls()))
        self.assertEqual(self.a.history()[0]["status"], "voicemail")
        self.assertEqual(self.b.history()[0]["status"], "voicemail")

    def test_screening_blocks_before_ringing(self):
        self.b.store.add_list_entry("block", "+1212555010*", "reject")
        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: not self.a.mgr.live_calls()))
        self.assertFalse(any(e["type"] == "incoming" for e in self.b.events))
        h = self.b.history()[0]
        self.assertEqual((h["status"], h["reason"]), ("blocked", "Blocked (+1212555010*)"))
        self.assertEqual(self.a.history()[0]["status"], "busy")

    def test_dnd_silences_and_repeat_caller_breaks_through(self):
        self.b.store.set("dnd", True)
        self.b.store.set("dnd_action", "voicemail")
        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: not self.a.mgr.live_calls()))
        self.assertEqual(self.b.history()[0]["status"], "voicemail")
        self.a.mgr.dial(BOB)                                 # second call within 3 minutes
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        self.assertEqual(self.b.call().screening["rule"], "dnd:repeat")

    def test_group_call(self):
        self.c = Phone(self.tmp.name, "carol", CAROL)
        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: self.b.mgr.live_calls()))
        self.b.mgr.answer(self.b.call().id)
        self.assertTrue(spin(lambda: self.a.call().state == "active"))
        # second call puts the first on hold
        self.a.mgr.dial(CAROL)
        self.assertTrue(spin(lambda: self.c.mgr.live_calls()))
        self.c.mgr.answer(self.c.call().id)
        self.assertTrue(spin(lambda: len([x for x in self.a.mgr.live_calls() if x.state == "active"]) == 1))
        self.assertTrue(spin(lambda: self.b.call().state == "remote_held"))
        conf = self.a.mgr.merge()
        self.assertTrue(spin(lambda: self.b.call().state == "active"))
        self.assertTrue(all(x.conference == conf for x in self.a.mgr.live_calls()))
        self.assertTrue(spin(lambda: self.b.call().participants and self.c.call().participants))
        # one participant leaves; the other leg stays up and is no longer a conference
        self.c.mgr.hangup(self.c.call().id)
        self.assertTrue(spin(lambda: len(self.a.mgr.live_calls()) == 1))
        self.assertIsNone(self.a.call().conference)

    def test_echo_peer_and_errors(self):
        self.a.mgr.dial("loop:echo", video=True)
        self.assertTrue(spin(lambda: self.a.call().state == "active" and self.a.call().video))
        self.a.mgr.hangup(self.a.call().id)
        self.assertFalse(self.a.mgr.live_calls())
        with self.assertRaises(ValueError):
            self.a.mgr.dial("not a number")
        with self.assertRaises(BackendError):
            self.a.mgr.dial("+13125550199")                  # nobody registered that number
        self.assertEqual(len(self.a.history()), 1)   # unreachable numbers are refused up front

    def test_simulated_incoming_with_unknown_policy(self):
        self.b.store.set("unknown_action", "silent")
        cid = self.b.mgr.simulate_incoming("+13125550177", display="Robo")
        call = self.b.call()
        self.assertTrue(call.silent)
        self.assertEqual((call.name, call.to_dict()["display"]), ("Robo", "(312) 555-0177"))
        self.b.mgr.answer(cid)
        self.assertTrue(spin(lambda: self.b.call().state == "active"))


class Baresip(unittest.TestCase):
    def test_netstrings(self):
        msgs, rest = parse_netstrings(netstring(b'{"a":1}') + netstring(b"xy") + b"5:ab")
        self.assertEqual((msgs, rest), ([b'{"a":1}', b"xy"], b"5:ab"))
        with self.assertRaises(ValueError):
            parse_netstrings(b"3:abc;")

    def test_event_mapping(self):
        b = BaresipBackend()
        events = []
        b.emit = events.append
        sent = []
        b.sock = type("S", (), {"sendall": lambda self, d: sent.append(d)})()
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_INCOMING","id":"x1",'
                         b'"peeruri":"sip:+12125550101@example.org","peerdisplayname":"Ana"}'))
        self.assertEqual(events[-1]["type"], "incoming")
        cid = events[-1]["call_id"]
        b.answer(cid)
        self.assertIn(b'"command": "accept", "params": "x1"', sent[-1])
        b.set_mute(cid, True)
        self.assertIn(b'"command": "callfind", "params": "x1"', sent[-2])
        self.assertIn(b'"command": "mute", "params": "true"', sent[-1])
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_ESTABLISHED","id":"x1"}'))
        self.assertEqual(events[-1], {"type": "state", "call_id": cid, "state": "active"})
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_HOLD","id":"x1"}'))
        self.assertEqual(events[-1], {"type": "state", "call_id": cid, "state": "remote_held"})
        b.set_hold(cid, True)
        self.assertIn(b'"command": "hold", "params": "x1"', sent[-1])
        self.assertEqual(events[-1], {"type": "state", "call_id": cid, "state": "held"})
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_CLOSED","id":"x1",'
                         b'"param":"486 Busy Here,Q.850;cause=17"}'))
        self.assertEqual(events[-1], {"type": "ended", "call_id": cid, "reason": "busy"})
        # an outgoing call is matched to baresip's id by CALL_OUTGOING; a failed dial ends it
        b.dial("out1", "+16465550102")
        self.assertIn(b'"command": "dial", "params": "+16465550102"', sent[-1])
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_OUTGOING","id":"y1","direction":"outgoing"}'))
        self.assertEqual(b.ours["out1"], "y1")
        b.hangup("out1", "normal")
        self.assertIn(b'"command": "hangup", "params": "y1"', sent[-1])
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_CLOSED","id":"y1","param":"Rejected by user"}'))
        self.assertEqual(events[-1], {"type": "ended", "call_id": "out1", "reason": "normal"})
        b.dial("out2", "sip:nobody@127.0.0.1")
        tok = sent[-1].split(b'"token": "')[1].split(b'"')[0]
        b.feed(netstring(b'{"response":true,"ok":false,"data":"dial failed","token":"' + tok + b'"}'))
        self.assertIn({"type": "ended", "call_id": "out2", "reason": "failed"}, events)
        b.sock = None

    def test_close_reasons(self):
        from omarchy_phone.backends.baresip import close_reason
        for param, want in (("486 Busy Here,Q.850;cause=17", "busy"), ("503 Service Unavailable,Q.850;cause=21",
                            "rejected"), ("603 Decline", "rejected"), ("408 Request Timeout", "no_answer"),
                            ("404 Not Found", "failed"), ("Connection reset by peer [104]", "normal")):
            self.assertEqual(close_reason(param, False), want, param)
        self.assertEqual(close_reason("Busy", True), "normal")

    def test_registration_events_without_a_configured_account(self):
        """REGISTERING/REGISTER_OK/REGISTER_FAIL/UNREGISTERING, event-driven (no reginfo involved)."""
        b = BaresipBackend()
        events = []
        b.emit = events.append
        b.feed(netstring(b'{"event":true,"class":"ua","type":"REGISTERING","accountaor":"sip:x@y"}'))
        self.assertEqual(events[-1], {"type": "registration", "state": "registering", "ok": False,
                                      "detail": "", "reason": ""})
        b.feed(netstring(b'{"event":true,"class":"ua","type":"REGISTER_OK","accountaor":"sip:x@y",'
                         b'"param":"200 OK"}'))
        self.assertEqual(events[-1], {"type": "registration", "state": "registered", "ok": True,
                                      "detail": "200 OK", "reason": ""})
        b.feed(netstring(b'{"event":true,"class":"ua","type":"REGISTER_FAIL","accountaor":"sip:x@y",'
                         b'"param":"401 Unauthorized"}'))
        self.assertEqual(events[-1], {"type": "registration", "state": "failed", "ok": False,
                                      "detail": "", "reason": "401 Unauthorized"})
        # UNREGISTERING is transient; it reports nothing on its own
        n = len(events)
        b.feed(netstring(b'{"event":true,"class":"ua","type":"UNREGISTERING","accountaor":"sip:x@y"}'))
        self.assertEqual(len(events), n)
        b.sock = None


class ParseReginfo(unittest.TestCase):
    """baresip's `reginfo` menu command: an ANSI-colored text dump, not JSON."""

    def test_registered_with_server_and_expiry(self):
        dump = ("\n--- User Agents (1) ---\n"
                "0 - sip:jane@pbx.example.org                       \x1b[32mOK \x1b[;m"
                " Asterisk PBX 20.5.0 Expires 298s\n\n")
        entries = parse_reginfo(dump)
        self.assertEqual(entries, [{"aor": "sip:jane@pbx.example.org", "ok": True, "registering": False,
                                    "srv": "Asterisk PBX 20.5.0", "expires": 298}])

    def test_not_yet_registered_and_no_server(self):
        dump = "0 - sip:carol@pbx.example.org                      \x1b[33mzzz\x1b[;m (nil)\n"
        entries = parse_reginfo(dump)
        self.assertEqual(entries, [{"aor": "sip:carol@pbx.example.org", "ok": False, "registering": True,
                                    "srv": None, "expires": None}])

    def test_failed_registration(self):
        dump = "1 - sip:bob@pbx.example.org                        \x1b[31mERR\x1b[;m 127.0.0.1\n"
        entries = parse_reginfo(dump)
        self.assertEqual(entries, [{"aor": "sip:bob@pbx.example.org", "ok": False, "registering": False,
                                    "srv": "127.0.0.1", "expires": None}])

    def test_multiple_accounts_and_empty_dump(self):
        dump = ("\n--- User Agents (2) ---\n"
                "0 - sip:jane@pbx.example.org  \x1b[32mOK \x1b[;m proxy1 Expires 60s\n"
                "1 - sip:bob@pbx.example.org  \x1b[31mERR\x1b[;m proxy1\n\n")
        entries = parse_reginfo(dump)
        self.assertEqual([e["aor"] for e in entries], ["sip:jane@pbx.example.org", "sip:bob@pbx.example.org"])
        self.assertEqual(parse_reginfo("\n--- User Agents (0) ---\n\n"), [])
        self.assertEqual(parse_reginfo(""), [])

    def test_strip_ansi(self):
        self.assertEqual(strip_ansi("\x1b[32mOK \x1b[;m"), "OK ")


class LineAor(unittest.TestCase):
    def test_strips_display_name_and_params(self):
        self.assertEqual(line_aor('"Jane Doe" <sip:jane@pbx.example.org;transport=tcp>;auth_pass="x";regint=300'),
                         "sip:jane@pbx.example.org")

    def test_no_angle_brackets(self):
        self.assertEqual(line_aor("sip:jane@pbx.example.org"), "sip:jane@pbx.example.org")


class FakeBaresip:
    """A real 127.0.0.1 TCP listener speaking baresip's ctrl_tcp netstring/JSON protocol, so
    BaresipBackend's own socket handling (connect, non-blocking IO, the reginfo round trip) is
    exercised for real without a real baresip process."""

    def __init__(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.conn = None
        self.buf = b""
        self.commands = []

    def accept(self, timeout=3):
        self.srv.settimeout(timeout)
        self.conn, _ = self.srv.accept()
        self.conn.settimeout(timeout)

    def recv_command(self, timeout=3):
        self.conn.settimeout(timeout)
        while True:
            msgs, self.buf = parse_netstrings(self.buf)
            if msgs:
                cmd = json.loads(msgs[0])
                self.commands.append(cmd)
                return cmd
            chunk = self.conn.recv(4096)
            if not chunk:
                raise ConnectionError("fake baresip: the client closed the connection")
            self.buf += chunk

    def send_response(self, token, ok=True, data=""):
        self.conn.sendall(netstring(json.dumps({"response": True, "ok": ok, "data": data, "token": token}).encode()))

    def send_event(self, obj):
        self.conn.sendall(netstring(json.dumps(dict(obj, event=True)).encode()))

    def close(self):
        for s in (self.conn, self.srv):
            if s:
                try:
                    s.close()
                except OSError:
                    pass


class RegistrationOverTheWire(unittest.TestCase):
    """The full connect -> reginfo -> (uanew if absent) -> events flow, against a fake baresip."""

    def test_reginfo_on_connect_uanew_then_register_ok_then_fail(self):
        fake = FakeBaresip()
        events = []
        line = '<sip:jane@pbx.example.org>;auth_pass="hunter2";regint=300'
        b = BaresipBackend({"host": "127.0.0.1", "port": fake.port, "account_line": line})
        try:
            b.start(events.append)
            fake.accept()

            cmd = fake.recv_command()
            self.assertEqual(cmd["command"], "reginfo")
            fake.send_response(cmd["token"], ok=True, data="\n--- User Agents (0) ---\n\n")
            self.assertTrue(spin(lambda: any(e.get("state") == "registering" for e in events)))

            cmd2 = fake.recv_command()
            self.assertEqual((cmd2["command"], cmd2["params"]), ("uanew", line))
            fake.send_response(cmd2["token"], ok=True,
                              data="\n--- User Agents (1) ---\n"
                                   "0 - sip:jane@pbx.example.org  \x1b[33mzzz\x1b[;m\n\n")
            self.assertTrue(spin(lambda: events[-1] == {"type": "registration", "state": "registering",
                                                        "ok": False, "detail": "", "reason": ""}))

            fake.send_event({"class": "ua", "type": "REGISTER_OK", "accountaor": "sip:jane@pbx.example.org",
                             "param": "200 OK"})
            self.assertTrue(spin(lambda: events[-1].get("state") == "registered"))
            self.assertEqual(events[-1]["ok"], True)
            self.assertEqual(events[-1]["detail"], "200 OK")

            events.clear()
            b.refresh_registration()
            cmd3 = fake.recv_command()
            self.assertEqual(cmd3["command"], "reginfo")
            fake.send_response(cmd3["token"], ok=True,
                              data="\n--- User Agents (1) ---\n"
                                   "0 - sip:jane@pbx.example.org  \x1b[31mERR\x1b[;m 127.0.0.1\n\n")
            self.assertTrue(spin(lambda: events and events[-1].get("state") == "failed"))

            fake.send_event({"class": "ua", "type": "REGISTER_FAIL", "accountaor": "sip:jane@pbx.example.org",
                             "param": "401 Unauthorized"})
            self.assertTrue(spin(lambda: events[-1].get("reason") == "401 Unauthorized"))
        finally:
            b.stop()
            fake.close()

    def test_no_configured_account_reflects_baresips_own_state(self):
        """A baresip with its own preexisting account (e.g. a hand-written accounts file, or the
        sipbed test image) is reflected as-is when phoned has not configured one of its own."""
        fake = FakeBaresip()
        events = []
        b = BaresipBackend({"host": "127.0.0.1", "port": fake.port})   # no account_line
        try:
            b.start(events.append)
            fake.accept()
            cmd = fake.recv_command()
            self.assertEqual(cmd["command"], "reginfo")
            fake.send_response(cmd["token"], ok=True,
                              data="\n--- User Agents (1) ---\n"
                                   "0 - sip:alice@127.0.0.1  \x1b[32mOK \x1b[;m 127.0.0.1 Expires 300s\n\n")
            self.assertTrue(spin(lambda: events and events[-1].get("state") == "registered"))
            self.assertEqual(len([c for c in fake.commands if c["command"] == "uanew"]), 0)
        finally:
            b.stop()
            fake.close()

    def test_no_account_anywhere_is_no_account_not_failed(self):
        fake = FakeBaresip()
        events = []
        b = BaresipBackend({"host": "127.0.0.1", "port": fake.port})
        try:
            b.start(events.append)
            fake.accept()
            cmd = fake.recv_command()
            fake.send_response(cmd["token"], ok=True, data="\n--- User Agents (0) ---\n\n")
            self.assertTrue(spin(lambda: events and events[-1].get("state") == "no_account"))
            self.assertFalse(events[-1]["ok"])
        finally:
            b.stop()
            fake.close()


if __name__ == "__main__":
    unittest.main()
