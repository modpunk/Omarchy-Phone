"""End-to-end call flows between two (or three) loopback instances in one process.

Signalling really goes over UDP on 127.0.0.1; no accounts, no external services, no media.
"""
import os
import tempfile
import time
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"

from gi.repository import GLib  # noqa: E402

from omarchy_phone.backends import BackendError  # noqa: E402
from omarchy_phone.backends.baresip import BaresipBackend, netstring, parse_netstrings  # noqa: E402
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
        self.assertIn(b'"command": "callfind", "params": "x1"', sent[0])
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_ESTABLISHED","id":"x1"}'))
        self.assertEqual(events[-1], {"type": "state", "call_id": cid, "state": "active"})
        b.feed(netstring(b'{"event":true,"class":"call","type":"CALL_CLOSED","id":"x1","param":"486 Busy"}'))
        self.assertEqual(events[-1], {"type": "ended", "call_id": cid, "reason": "busy"})
        b.sock = None


if __name__ == "__main__":
    unittest.main()
