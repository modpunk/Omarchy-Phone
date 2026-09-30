"""End-to-end SIP calls through real baresip + Asterisk (tests/sipbed/) running in Docker.

The container runs Asterisk and two baresip endpoints (alice = ext 1001 / +1 212 555 0101,
bob = ext 1002 / +1 646 555 0102) on its own 127.0.0.1; only the two baresip ctrl_tcp ports are
published, on the host's 127.0.0.1. Audio is a sine tone in (440 Hz alice, 880 Hz bob) and a WAV
file out, so no microphone or speaker is touched. Test accounts only; no real SIP service.

Skipped when Docker is not usable (or with OMARCHY_PHONE_SKIP_SIPBED=1). The first run builds the
image (compiles baresip; the only network use is fetching sources and packages at build time)
and keeps it; later runs start a container in ~3 s. The container is removed after the tests.
"""
import hashlib
import math
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"

from gi.repository import GLib  # noqa: E402

from omarchy_phone.backends.baresip import BaresipBackend  # noqa: E402
from omarchy_phone.calls import CallManager  # noqa: E402
from omarchy_phone.store import Store  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BED = os.path.join(HERE, "sipbed")
APP = os.path.dirname(HERE)
ALICE, BOB = "+12125550101", "+16465550102"
ALICE_HZ, BOB_HZ = 440, 880


def docker_usable() -> bool:
    if os.environ.get("OMARCHY_PHONE_SKIP_SIPBED") == "1" or not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker(*args, timeout=60, check=True) -> str:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def image_tag() -> str:
    """The image is named after the test bed's contents, so editing a config rebuilds it."""
    h = hashlib.sha256()
    for root, dirs, files in sorted(os.walk(BED)):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, BED).encode() + b"\0" + open(p, "rb").read())
    return "omarchy-phone-sipbed:" + h.hexdigest()[:12]


def spin(cond, timeout=5.0):
    ctx = GLib.MainContext.default()
    end = time.time() + timeout
    while time.time() < end:
        while ctx.pending():
            ctx.iteration(False)
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def rms_blocks(path: str, block_s=0.1) -> list[float]:
    with wave.open(path) as w:
        sr, raw = w.getframerate(), w.readframes(w.getnframes())
    samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
    n = int(sr * block_s)
    return [math.sqrt(sum(v * v for v in samples[i:i + n]) / n) for i in range(0, len(samples) - n + 1, n)]


def tone_levels(path: str, freqs, skip_s=0.3) -> dict:
    """Goertzel magnitude per frequency over the recording (after `skip_s`)."""
    with wave.open(path) as w:
        sr, n = w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    samples = struct.unpack("<%dh" % (len(raw) // 2), raw)[int(sr * skip_s):]
    out = {}
    for f in freqs:
        k = 2 * math.cos(2 * math.pi * f / sr)
        a = b = 0.0
        for v in samples:
            a, b = v + k * a - b, a
        out[f] = math.sqrt(max(a * a + b * b - k * a * b, 0.0)) / max(len(samples), 1)
    return out


class Bed:
    """One throwaway container: start, wait until both endpoints are registered, remove."""

    def __init__(self):
        self.name = f"omarchy-phone-sipbed-{os.getpid()}"
        self.image = os.environ.get("OMARCHY_PHONE_SIPBED_IMAGE") or image_tag()
        self.ports = {}

    def up(self):
        if subprocess.run(["docker", "image", "inspect", self.image], capture_output=True, timeout=30).returncode:
            docker("build", "-q", "-t", self.image, BED, timeout=1800)
        docker("run", "-d", "--rm", "--name", self.name,
               "-p", "127.0.0.1::4444", "-p", "127.0.0.1::4445", self.image)
        for who, port in (("alice", 4444), ("bob", 4445)):
            host, _, hport = docker("port", self.name, f"{port}/tcp").split()[0].rpartition(":")
            assert host == "127.0.0.1", host
            self.ports[who] = int(hport)
        end = time.time() + 30
        while time.time() < end:
            contacts = docker("exec", self.name, "asterisk", "-rx", "pjsip show contacts", check=False)
            if "1001/sip:" in contacts and "1002/sip:" in contacts and all(self._accepts(p) for p in self.ports.values()):
                return
            time.sleep(0.3)
        raise RuntimeError("SIP test bed did not come up:\n" + docker("logs", self.name, check=False))

    @staticmethod
    def _accepts(port):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            return False

    def fetch(self, name: str, dest_dir: str) -> str:
        dest = os.path.join(dest_dir, name)
        docker("cp", f"{self.name}:/sipbed/out/{name}", dest)
        return dest

    def down(self):
        docker("rm", "-f", self.name, check=False, timeout=60)


class Phone:
    def __init__(self, tmp, profile, number, port):
        self.store = Store(os.path.join(tmp, f"{profile}.db"))
        self.store.set("own_number", number)
        self.store.set("backend", "sip")
        self.events = []
        self.backend = BaresipBackend({"host": "127.0.0.1", "port": port})
        self.mgr = CallManager(self.store, [self.backend], emit=self.events.append)

    def call(self):
        calls = self.mgr.live_calls()
        return calls[0] if len(calls) == 1 else None

    def state(self):
        c = self.call()
        return c.state if c else None

    def last_history(self):
        return self.store.history()[0]


@unittest.skipUnless(docker_usable(), "Docker is not available")
class SipCalls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bed = Bed()
        cls.addClassCleanup(cls.bed.down)
        cls.bed.up()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Phone(self.tmp.name, "alice", ALICE, self.bed.ports["alice"])
        self.b = Phone(self.tmp.name, "bob", BOB, self.bed.ports["bob"])
        self.assertTrue(spin(lambda: self.a.mgr.registration.get("sip", {}).get("ok")
                             and self.b.mgr.registration.get("sip", {}).get("ok")))

    def tearDown(self):
        for p in (self.a, self.b):
            for c in p.mgr.live_calls():
                try:
                    p.mgr.hangup(c.id)
                except Exception:
                    pass
        spin(lambda: not self.a.mgr.live_calls() and not self.b.mgr.live_calls(), 3)
        for p in (self.a, self.b):
            p.mgr.stop()
            p.store.close()
        self.tmp.cleanup()

    def ring_bob(self):
        out = self.a.mgr.dial("+1 646 555 0102")
        self.assertTrue(spin(lambda: self.b.state() == "incoming"), "bob never rang")
        self.assertTrue(spin(lambda: self.a.state() == "ringing"))
        return out

    def test_call_hold_mute_dtmf_hangup_with_audio(self):
        self.ring_bob()
        inc = self.b.call()
        self.assertEqual(inc.remote, ALICE)          # caller id arrived as E.164 via Asterisk
        self.assertEqual(inc.name, "Alice")          # display name from the PBX (no contact)
        self.assertTrue(any(e["type"] == "incoming" for e in self.b.events))

        self.b.mgr.answer(inc.id)
        self.assertTrue(spin(lambda: self.a.state() == "active" and self.b.state() == "active"))
        spin(lambda: False, 1.0)                    # let audio flow

        a_id = self.a.call().id
        self.a.mgr.hold(a_id, True)
        self.assertTrue(spin(lambda: self.a.state() == "held" and self.b.state() == "remote_held"))
        self.a.mgr.hold(a_id, False)
        self.assertTrue(spin(lambda: self.a.state() == "active" and self.b.state() == "active"),
                        (self.a.state(), self.b.state(), [e for e in self.a.events + self.b.events if e["type"] == "error"]))

        # quick toggles: baresip would lose the second re-INVITE; the adapter serializes them
        self.a.mgr.hold(a_id, True)
        self.a.mgr.hold(a_id, False)
        self.b.mgr.hold(self.b.call().id, True)
        self.b.mgr.hold(self.b.call().id, False)
        spin(lambda: False, 1.5)
        self.assertEqual((self.a.state(), self.b.state()), ("active", "active"))

        spin(lambda: False, 0.8)
        self.a.mgr.mute(a_id, True)
        self.assertTrue(self.a.call().muted)
        spin(lambda: False, 1.0)                    # bob should hear silence now
        self.a.mgr.mute(a_id, False)
        self.assertFalse(self.a.call().muted)

        self.a.mgr.dtmf(a_id, "12#")
        self.assertTrue(spin(lambda: [e["digit"] for e in self.b.events if e["type"] == "dtmf"] == ["1", "2", "#"]),
                        [e for e in self.b.events if e["type"] == "dtmf"])
        spin(lambda: False, 1.5)                    # audio after the resume re-INVITE

        self.a.mgr.hangup(a_id)
        self.assertTrue(spin(lambda: self.a.state() is None and self.b.state() is None))
        self.assertEqual(self.a.last_history()["status"], "answered")
        self.assertEqual(self.b.last_history()["status"], "answered")

        # Real media: each side recorded the other's tone, after it went through Asterisk.
        spin(lambda: False, 0.5)
        bob_wav, alice_wav = self.bed.fetch("bob-rx.wav", self.tmp.name), self.bed.fetch("alice-rx.wav", self.tmp.name)
        at_bob = tone_levels(bob_wav, (ALICE_HZ, BOB_HZ))
        at_alice = tone_levels(alice_wav, (ALICE_HZ, BOB_HZ))
        # aufile restarts the recording at the resume re-INVITE, so bob's file covers resume..hangup:
        # tone, ~1 s of silence while alice was muted, tone again. Alice kept hearing bob throughout.
        levels = "".join("T" if r > 3000 else "s" if r < 100 else "?" for r in rms_blocks(bob_wav))
        self.assertRegex(levels, r"T{3,}\?*s{7,}\?*T{3,}", levels)
        self.assertNotIn("s", "".join("T" if r > 3000 else "s" if r < 100 else "?"
                                      for r in rms_blocks(alice_wav))[2:-2])
        self.assertGreater(at_bob[ALICE_HZ], 500, at_bob)
        self.assertGreater(at_bob[ALICE_HZ], 20 * at_bob[BOB_HZ], at_bob)
        self.assertGreater(at_alice[BOB_HZ], 500, at_alice)
        self.assertGreater(at_alice[BOB_HZ], 20 * at_alice[ALICE_HZ], at_alice)

    def test_decline_is_busy_for_the_caller(self):
        self.ring_bob()
        self.b.mgr.decline(self.b.call().id)
        self.assertTrue(spin(lambda: self.a.state() is None and self.b.state() is None))
        self.assertEqual(self.a.last_history()["status"], "busy")
        self.assertEqual(self.b.last_history()["status"], "rejected")

    def test_caller_hangs_up_before_answer(self):
        self.ring_bob()
        self.a.mgr.hangup(self.a.call().id)
        self.assertTrue(spin(lambda: self.a.state() is None and self.b.state() is None))
        self.assertEqual(self.a.last_history()["status"], "cancelled")
        self.assertEqual(self.b.last_history()["status"], "missed")

    def test_screened_caller_is_rejected_before_ringing(self):
        self.b.store.add_list_entry("block", ALICE)
        self.a.mgr.dial(BOB)
        self.assertTrue(spin(lambda: self.a.state() is None, 5), self.a.state())
        self.assertEqual(self.a.last_history()["status"], "busy")
        self.assertEqual(self.b.last_history()["status"], "blocked")

    def test_echo_service_returns_our_audio(self):
        self.a.mgr.dial("sip:600@127.0.0.1")        # Asterisk Echo() on the test PBX
        self.assertTrue(spin(lambda: self.a.state() == "active"))
        spin(lambda: False, 1.5)
        self.a.mgr.hangup(self.a.call().id)
        self.assertTrue(spin(lambda: self.a.state() is None))
        spin(lambda: False, 0.5)
        lv = tone_levels(self.bed.fetch("alice-rx.wav", self.tmp.name), (ALICE_HZ, BOB_HZ))
        self.assertGreater(lv[ALICE_HZ], 500, lv)
        self.assertGreater(lv[ALICE_HZ], 20 * lv[BOB_HZ], lv)

    @unittest.skipUnless(os.environ.get("OMARCHY_PHONE_SANDBOX"), "needs the private bus of scripts/test.sh")
    def test_phoned_daemons_over_dbus(self):
        """The real daemons (`phoned --backend sip`) driven through their D-Bus API."""
        from omarchy_phone.client import Client
        env = dict(os.environ, PYTHONPATH=APP)
        procs = []
        for profile, number, who in (("sipa", ALICE, "alice"), ("sipb", BOB, "bob")):
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "omarchy_phone.daemon", "--profile", profile, "--backend", "sip",
                 "--number", number, "--baresip", f"127.0.0.1:{self.bed.ports[who]}"],
                cwd=APP, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE))
        # this test drives the daemons, not the in-process phones; free their ctrl_tcp slots
        for p in (self.a, self.b):
            p.backend.stop()

        def cleanup():
            for p in procs:
                p.terminate()
                p.wait(5)
        self.addCleanup(cleanup)
        ca, cb = Client("sipa"), Client("sipb")

        def wait(pred, timeout=8):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    if pred():
                        return True
                except Exception:
                    pass
                time.sleep(0.1)
            return False

        self.assertTrue(wait(lambda: ca.call("state")["registration"]["sip"]["ok"]
                             and cb.call("state")["registration"]["sip"]["ok"]))
        ca.call("dial", address="+1 646 555 0102")
        self.assertTrue(wait(lambda: cb.call("state")["calls"][0]["state"] == "incoming"))
        cb.call("answer", call_id=cb.call("state")["calls"][0]["id"])
        self.assertTrue(wait(lambda: ca.call("state")["calls"][0]["state"] == "active"))
        ca.call("dtmf", call_id=ca.call("state")["calls"][0]["id"], digits="5")
        ca.call("hangup")
        self.assertTrue(wait(lambda: not ca.call("state")["calls"] and not cb.call("state")["calls"]))
        self.assertEqual(cb.call("history", limit=1)[0]["status"], "answered")


if __name__ == "__main__":
    unittest.main()
