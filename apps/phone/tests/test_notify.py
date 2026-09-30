"""Shell integration (docs/shell/INTEGRATION.md) against a fake notification server.

Needs a private session bus: run through scripts/sandbox.sh (scripts/test.sh does). Skipped
when the name org.freedesktop.Notifications is already owned, e.g. on a real desktop session.
"""
import os
import tempfile
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"
os.environ.pop("OMARCHY_PHONE_NO_NOTIFY", None)

from gi.repository import Gio, GLib  # noqa: E402

from omarchy_phone.backends.loopback import LoopbackBackend  # noqa: E402
from omarchy_phone.calls import CallManager  # noqa: E402
from omarchy_phone.notify import Notifier  # noqa: E402
from omarchy_phone.store import Store  # noqa: E402
from omarchy_phone.vcard import Contact  # noqa: E402
from tests.test_calls import spin  # noqa: E402

XML = """<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
<arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>"""


class FakeShell:
    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.notes, self.closed, self.next = {}, [], 1
        self.owned = None
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        self.reg = self.bus.register_object("/org/freedesktop/Notifications", info, self._call, None, None)
        self.own = Gio.bus_own_name_on_connection(self.bus, "org.freedesktop.Notifications",
                                                   Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
                                                   lambda *_: setattr(self, "owned", True),
                                                   lambda *_: setattr(self, "owned", False))
        spin(lambda: self.owned is not None)

    def _call(self, _c, _s, _p, _i, method, params, inv):
        if method == "Notify":
            app, replaces, icon, summary, body, actions, hints, _t = params.unpack()
            nid = replaces or self.next
            self.next += not replaces
            self.notes[nid] = {"summary": summary, "body": body, "actions": actions[::2], "hints": hints}
            inv.return_value(GLib.Variant("(u)", (nid,)))
        elif method == "CloseNotification":
            self.closed.append(params.unpack()[0])
            inv.return_value(None)
        else:
            inv.return_value(GLib.Variant("(ssss)", ("quickshell", "omarchy-phone", "0", "1.2")))

    def invoke(self, nid, action):
        self.bus.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                             "ActionInvoked", GLib.Variant("(us)", (nid, action)))

    def by_category(self, cat):
        return [(n, v) for n, v in self.notes.items() if v["hints"].get("category") == cat]

    def stop(self):
        Gio.bus_unown_name(self.own)
        self.bus.unregister_object(self.reg)


def _lock_path():
    return os.path.join(os.environ["XDG_RUNTIME_DIR"], "omarchy-phone", "locked")


def _set_locked(state):
    """state: True (locked), False (unlocked), or None (delete the file -- unknown state, which
    docs/phone/DESIGN.md's privacy section and Notifier.locked_mode() both treat as locked)."""
    path = _lock_path()
    if state is None:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("off" if state is False else "on")


@unittest.skipUnless(os.environ.get("OMARCHY_PHONE_SANDBOX"), "needs scripts/sandbox.sh (private session bus)")
class ShellContract(unittest.TestCase):
    def setUp(self):
        self.shell = FakeShell()
        if not self.shell.owned:
            self.shell.stop()
            self.skipTest("a real notification daemon owns the name")
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "p.db"))
        self.store.save_contact(Contact(name="Ada Lovelace", numbers=[("cell", "+12125550100")]))
        self.backend = LoopbackBackend({"profile": "t", "dir": os.path.join(self.tmp.name, "reg")})
        self.notifier = Notifier(lambda k, a: self.mgr.notification_action(k, a))
        self.mgr = CallManager(self.store, [self.backend], notifier=self.notifier)
        spin(lambda: self.notifier.server is not None)
        _set_locked(None)  # unknown lock state unless a test says otherwise

    def tearDown(self):
        self.mgr.stop()
        self.store.close()
        self.shell.stop()
        self.tmp.cleanup()
        _set_locked(None)

    def test_incoming_accept_pill_and_close(self):
        self.assertTrue(self.notifier.shell_present())
        _set_locked(False)  # unlocked: full caller name is safe to show
        cid = self.mgr.simulate_incoming("+12125550100", video=True)
        self.assertTrue(spin(lambda: self.shell.by_category("call.incoming")))
        [(nid, n)] = self.shell.by_category("call.incoming")
        self.assertEqual(n["summary"], "Ada Lovelace")
        self.assertEqual(n["hints"]["x-ophone-caller"], "Ada Lovelace")
        self.assertEqual(n["hints"]["x-ophone-number"], "(212) 555-0100")
        self.assertEqual(n["hints"]["x-ophone-video"], "true")
        self.assertTrue(n["hints"]["resident"])
        self.assertEqual(n["hints"]["urgency"], 2)
        self.assertEqual(n["actions"][:3], ["accept", "decline", "silence"])

        self.shell.invoke(nid, "accept")
        self.assertTrue(spin(lambda: self.mgr.calls[cid].state == "active"))
        self.assertTrue(spin(lambda: nid in self.shell.closed))
        self.assertTrue(spin(lambda: self.shell.by_category("call")))
        [(pill, p)] = self.shell.by_category("call")
        self.assertEqual(p["actions"], ["default"])
        self.mgr.hangup(cid)
        self.assertTrue(spin(lambda: pill in self.shell.closed))

    def test_decline_and_missed(self):
        cid = self.mgr.simulate_incoming("+12125550100")
        self.assertTrue(spin(lambda: self.shell.by_category("call.incoming")))
        [(nid, _)] = self.shell.by_category("call.incoming")
        self.shell.invoke(nid, "decline")
        self.assertTrue(spin(lambda: cid not in self.mgr.calls))
        self.assertEqual(self.store.history()[0]["status"], "rejected")

        cid = self.mgr.simulate_incoming("+13125550142")
        self.backend.hangup(cid)             # caller gives up
        self.assertTrue(spin(lambda: self.shell.by_category("call.unanswered")))

    def test_silenced_calls_do_not_take_the_screen(self):
        self.store.set("unknown_action", "silent")
        self.mgr.simulate_incoming("+13125550142")
        self.assertTrue(spin(lambda: self.shell.by_category("call.silenced")))
        self.assertFalse(self.shell.by_category("call.incoming"))

    # --- lock-screen caller privacy (docs/phone/DESIGN.md "Privacy and security"): the caller
    # name must never reach the summary or the x-ophone-caller hint unless the shell has
    # explicitly said the device is unlocked ($XDG_RUNTIME_DIR/omarchy-phone/locked == "off").

    def test_incoming_hides_caller_name_when_locked(self):
        _set_locked(True)
        self.mgr.simulate_incoming("+12125550100")
        self.assertTrue(spin(lambda: self.shell.by_category("call.incoming")))
        [(_, n)] = self.shell.by_category("call.incoming")
        self.assertEqual(n["summary"], "Incoming call")
        self.assertEqual(n["hints"]["x-ophone-caller"], "Incoming call")
        # the number itself is still shown -- only the name is gated
        self.assertEqual(n["hints"]["x-ophone-number"], "(212) 555-0100")

    def test_incoming_hides_caller_name_when_lock_state_unknown(self):
        _set_locked(None)  # no file at all: the shell has never reported a lock state
        self.mgr.simulate_incoming("+12125550100")
        self.assertTrue(spin(lambda: self.shell.by_category("call.incoming")))
        [(_, n)] = self.shell.by_category("call.incoming")
        self.assertEqual(n["summary"], "Incoming call")
        self.assertEqual(n["hints"]["x-ophone-caller"], "Incoming call")

    def test_incoming_shows_caller_name_when_unlocked(self):
        _set_locked(False)
        self.mgr.simulate_incoming("+12125550100")
        self.assertTrue(spin(lambda: self.shell.by_category("call.incoming")))
        [(_, n)] = self.shell.by_category("call.incoming")
        self.assertEqual(n["summary"], "Ada Lovelace")
        self.assertEqual(n["hints"]["x-ophone-caller"], "Ada Lovelace")

    def test_silenced_call_title_hides_caller_name_when_locked(self):
        _set_locked(True)
        self.store.set("unknown_action", "silent")
        self.mgr.simulate_incoming("+13125550142")
        self.assertTrue(spin(lambda: self.shell.by_category("call.silenced")))
        [(_, n)] = self.shell.by_category("call.silenced")
        self.assertEqual(n["summary"], "Silenced call")
        self.assertEqual(n["hints"]["x-ophone-caller"], "Incoming call")


class LockedMode(unittest.TestCase):
    """Notifier.locked_mode() itself, independent of the D-Bus/shell plumbing above."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._orig
        self.tmp.cleanup()

    def test_missing_file_is_locked(self):
        self.assertTrue(Notifier.locked_mode())

    def test_explicit_off_is_unlocked(self):
        _set_locked(False)
        self.assertFalse(Notifier.locked_mode())

    def test_explicit_on_is_locked(self):
        _set_locked(True)
        self.assertTrue(Notifier.locked_mode())

    def test_garbage_contents_default_to_locked(self):
        path = _lock_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("banana")
        self.assertTrue(Notifier.locked_mode())


if __name__ == "__main__":
    unittest.main()
