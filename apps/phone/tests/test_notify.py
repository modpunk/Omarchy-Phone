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

    def tearDown(self):
        self.mgr.stop()
        self.store.close()
        self.shell.stop()
        self.tmp.cleanup()

    def test_incoming_accept_pill_and_close(self):
        self.assertTrue(self.notifier.shell_present())
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


if __name__ == "__main__":
    unittest.main()
