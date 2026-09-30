"""shell/bin/ophone-pin: hash/verify round trip, wrong-PIN rejection, file
permissions of `set`. Run through shell/tests/run.sh (or plain unittest;
no D-Bus needed for this file).

ophone-pin has no .py extension (it's an installed script, like ophone-ctl /
ophone-sys), so it's loaded by path with importlib rather than imported
normally.
"""
from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin", "ophone-pin")


def _load_module():
    loader = SourceFileLoader("ophone_pin", BIN)
    spec = importlib.util.spec_from_loader("ophone_pin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ophone_pin = _load_module()


class HashRoundTrip(unittest.TestCase):
    def test_hash_then_verify_matches(self):
        h = ophone_pin.hash_pin("1234")
        self.assertTrue(ophone_pin.verify_pin("1234", h))

    def test_wrong_pin_rejected(self):
        h = ophone_pin.hash_pin("1234")
        self.assertFalse(ophone_pin.verify_pin("4321", h))
        self.assertFalse(ophone_pin.verify_pin("12345", h))
        self.assertFalse(ophone_pin.verify_pin("", h))

    def test_hash_is_salted(self):
        # Same PIN, two calls -> different salt -> different stored string.
        h1 = ophone_pin.hash_pin("1234")
        h2 = ophone_pin.hash_pin("1234")
        self.assertNotEqual(h1, h2)
        self.assertTrue(ophone_pin.verify_pin("1234", h1))
        self.assertTrue(ophone_pin.verify_pin("1234", h2))

    def test_garbage_stored_value_rejected_not_crashed(self):
        self.assertFalse(ophone_pin.verify_pin("1234", "not a hash"))
        self.assertFalse(ophone_pin.verify_pin("1234", ""))
        self.assertFalse(ophone_pin.verify_pin("1234", "scrypt$x$y$z$00$00"))


class ReadWriteFile(unittest.TestCase):
    def test_write_then_read_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "pin-hash")
            ophone_pin.write_hash_file(path, ophone_pin.hash_pin("2468"))
            stored = ophone_pin.read_hash_file(path)
            self.assertIsNotNone(stored)
            self.assertTrue(ophone_pin.verify_pin("2468", stored))

    def test_write_sets_mode_0640(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pin-hash")
            ophone_pin.write_hash_file(path, ophone_pin.hash_pin("2468"))
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o640)

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(ophone_pin.read_hash_file("/nonexistent/path/pin-hash"))


class CliEndToEnd(unittest.TestCase):
    """Exercises the actual CLI subprocess: `set` (unprivileged test mode)
    then `verify` reading the PIN from stdin, exactly like pam_exec's
    expose_authtok delivers it."""

    def _run(self, args, stdin=None, env=None):
        full_env = dict(os.environ)
        full_env.update(env or {})
        return subprocess.run([sys.executable, BIN] + args, input=stdin, capture_output=True, text=True, env=full_env)

    def test_set_then_verify_correct_and_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pin-hash")
            env = {"OPHONE_PIN_FILE": path, "OPHONE_PIN_ALLOW_UNPRIVILEGED": "1", "OPHONE_PIN_GROUP": ""}
            r = self._run(["set"], stdin="4242\n4242\n", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)

            ok = self._run(["verify"], stdin="4242\n", env=env)
            self.assertEqual(ok.returncode, 0)

            bad = self._run(["verify"], stdin="0000\n", env=env)
            self.assertEqual(bad.returncode, 1)

    def test_set_rejects_mismatched_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pin-hash")
            env = {"OPHONE_PIN_FILE": path, "OPHONE_PIN_ALLOW_UNPRIVILEGED": "1"}
            r = self._run(["set"], stdin="1111\n2222\n", env=env)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(path))

    def test_set_rejects_non_numeric(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pin-hash")
            env = {"OPHONE_PIN_FILE": path, "OPHONE_PIN_ALLOW_UNPRIVILEGED": "1"}
            r = self._run(["set"], stdin="abcd\nabcd\n", env=env)
            self.assertNotEqual(r.returncode, 0)

    def test_verify_with_no_file_denies(self):
        r = self._run(["verify"], stdin="1234\n", env={"OPHONE_PIN_FILE": "/nonexistent/pin-hash"})
        self.assertEqual(r.returncode, 1)

    def test_set_refuses_without_root_or_override(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "pin-hash")
            env = dict(os.environ)
            env.pop("OPHONE_PIN_ALLOW_UNPRIVILEGED", None)
            env["OPHONE_PIN_FILE"] = path
            r = subprocess.run([sys.executable, BIN, "set"], input="1234\n1234\n", capture_output=True, text=True, env=env)
            if os.geteuid() != 0:
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
