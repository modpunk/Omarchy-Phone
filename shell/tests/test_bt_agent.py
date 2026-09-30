"""shell/bin/ophone-btagentd against a mock org.bluez + a fake notification
server, both on a private D-Bus session bus (run through shell/tests/run.sh,
which starts one with dbus-run-session -- the same isolation apps/phone's
own tests use, see apps/phone/tests/test_notify.py's FakeShell).

ophone-btagentd is exercised as a real subprocess (it runs its own
GLib.MainLoop), talking over the shared private bus exactly like bluetoothd
and the shell would -- this test IS "bluetoothd" and "the shell" at once.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest

from gi.repository import Gio, GLib

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin", "ophone-btagentd")

NOTIFY_BUS, NOTIFY_PATH, NOTIFY_IFACE = (
    "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
)

AGENT_MANAGER_XML = """<node><interface name="org.bluez.AgentManager1">
  <method name="RegisterAgent"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
  <method name="RequestDefaultAgent"><arg type="o" direction="in"/></method>
  <method name="UnregisterAgent"><arg type="o" direction="in"/></method>
</interface></node>"""

PROPERTIES_XML = """<node><interface name="org.freedesktop.DBus.Properties">
  <method name="Get"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
</interface></node>"""

NOTIFICATIONS_XML = """<node><interface name="org.freedesktop.Notifications">
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/>
<arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>"""


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


class FakeBluez:
    """Just enough of org.bluez.AgentManager1 + a Device1's Properties.Get to
    let ophone-btagentd register itself and label a device."""

    def __init__(self, bus):
        self.bus = bus
        self.registered: dict[str, str] = {}
        self.default_agent = None
        self.agent_owner = None   # unique bus name of whoever called RegisterAgent
        self.device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        info = Gio.DBusNodeInfo.new_for_xml(AGENT_MANAGER_XML).interfaces[0]
        self._reg1 = bus.register_object("/org/bluez", info, self._call, None, None)
        pinfo = Gio.DBusNodeInfo.new_for_xml(PROPERTIES_XML).interfaces[0]
        self._reg2 = bus.register_object(self.device_path, pinfo, self._props_call, None, None)

        self.owned = None
        self._own = Gio.bus_own_name_on_connection(
            bus, "org.bluez", Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
            lambda *_: setattr(self, "owned", True), lambda *_: setattr(self, "owned", False))
        spin(lambda: self.owned is not None)

    def teardown(self):
        Gio.bus_unown_name(self._own)
        self.bus.unregister_object(self._reg1)
        self.bus.unregister_object(self._reg2)

    def _call(self, connection, sender, path, iface, method, params, invocation):
        if method == "RegisterAgent":
            agent_path, capability = params.unpack()
            self.registered[agent_path] = capability
            self.agent_owner = sender
            invocation.return_value(None)
        elif method == "RequestDefaultAgent":
            (agent_path,) = params.unpack()
            self.default_agent = agent_path
            invocation.return_value(None)
        elif method == "UnregisterAgent":
            (agent_path,) = params.unpack()
            self.registered.pop(agent_path, None)
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _props_call(self, connection, sender, path, iface, method, params, invocation):
        _interface_name, prop = params.unpack()
        if prop == "Alias":
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", "Test Keyboard"),)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", "no such property")


class FakeNotifications:
    """Fake org.freedesktop.Notifications: records Notify() calls and lets the
    test fire ActionInvoked/NotificationClosed back, the same shape as a real
    notification daemon (or the shell's own NotificationServer)."""

    def __init__(self, bus):
        self.bus = bus
        self.notes: dict[int, dict] = {}
        self.next_id = 1
        info = Gio.DBusNodeInfo.new_for_xml(NOTIFICATIONS_XML).interfaces[0]
        self._reg = bus.register_object(NOTIFY_PATH, info, self._call, None, None)
        self.owned = None
        self._own = Gio.bus_own_name_on_connection(
            bus, NOTIFY_BUS, Gio.BusNameOwnerFlags.DO_NOT_QUEUE,
            lambda *_: setattr(self, "owned", True), lambda *_: setattr(self, "owned", False))
        spin(lambda: self.owned is not None)

    def teardown(self):
        Gio.bus_unown_name(self._own)
        self.bus.unregister_object(self._reg)

    def _call(self, connection, sender, path, iface, method, params, invocation):
        if method == "Notify":
            app, replaces, icon, summary, body, actions, hints, _timeout = params.unpack()
            nid = replaces or self.next_id
            self.next_id += 0 if replaces else 1
            self.notes[nid] = {"summary": summary, "body": body, "actions": actions[::2], "hints": hints}
            invocation.return_value(GLib.Variant("(u)", (nid,)))
        elif method == "CloseNotification":
            invocation.return_value(None)
        else:
            invocation.return_value(GLib.Variant("(ssss)", ("test", "ophone-tests", "0", "1.2")))

    def invoke(self, nid: int, action: str):
        self.bus.emit_signal(None, NOTIFY_PATH, NOTIFY_IFACE, "ActionInvoked", GLib.Variant("(us)", (nid, action)))

    def close(self, nid: int, reason: int = 3):
        self.bus.emit_signal(None, NOTIFY_PATH, NOTIFY_IFACE, "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))


class BtAgentTest(unittest.TestCase):
    def setUp(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bluez = FakeBluez(self.bus)
        self.notes = FakeNotifications(self.bus)
        env = dict(os.environ)
        env.update({"OPHONE_BT_BUS": "session", "OPHONE_BT_TIMEOUT": "2", "OPHONE_BT_QUIET": "1"})
        self.proc = subprocess.Popen([sys.executable, BIN], env=env)
        # LIFO: stop the agent process first, then tear down the fakes it was
        # talking to, so a slow-to-die agent can't retrigger a fake's handler
        # after that fake's D-Bus objects are gone.
        self.addCleanup(self.bluez.teardown)
        self.addCleanup(self.notes.teardown)
        self.addCleanup(self._stop_agent)
        self.assertTrue(spin(lambda: self.bluez.default_agent is not None, timeout=8), "agent never registered")
        self.agent_path = self.bluez.default_agent
        self.agent_owner = self.bluez.agent_owner

    def _stop_agent(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=3)
        # Let GDBus notice the peer vanished before the next test's FakeBluez
        # re-registers the same object paths on this (cached, shared) connection.
        spin(lambda: False, timeout=0.2)

    def _call_agent(self, method, variant):
        result: dict = {}

        def done(conn, res, _data=None):
            try:
                result["reply"] = conn.call_finish(res)
            except GLib.Error as e:
                result["error"] = e

        self.bus.call(self.agent_owner, self.agent_path, "org.bluez.Agent1", method, variant, None,
                       Gio.DBusCallFlags.NONE, -1, None, done)
        return result

    def _one_pending_notification_id(self):
        self.assertTrue(spin(lambda: len(self.notes.notes) == 1), "agent never asked the user")
        return next(iter(self.notes.notes))

    # -- the actual F5/F6 fix: nothing is accepted without an explicit tap --

    def test_request_confirmation_accept(self):
        result = self._call_agent("RequestConfirmation", GLib.Variant("(ou)", (self.bluez.device_path, 123456)))
        nid = self._one_pending_notification_id()
        self.assertEqual(self.notes.notes[nid]["actions"], ["pair", "reject"])
        self.notes.invoke(nid, "pair")
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertNotIn("error", result, "an explicit Pair tap must be accepted")

    def test_request_confirmation_reject(self):
        result = self._call_agent("RequestConfirmation", GLib.Variant("(ou)", (self.bluez.device_path, 123456)))
        nid = self._one_pending_notification_id()
        self.notes.invoke(nid, "reject")
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertIn("error", result)
        self.assertIn("Rejected", result["error"].message)

    def test_request_confirmation_times_out_rejected(self):
        # OPHONE_BT_TIMEOUT=2 in setUp: an unanswered prompt must deny, not
        # silently accept the way the default NoInputNoOutput agent would.
        result = self._call_agent("RequestConfirmation", GLib.Variant("(ou)", (self.bluez.device_path, 1)))
        self._one_pending_notification_id()
        self.assertTrue(spin(lambda: "reply" in result or "error" in result, timeout=6))
        self.assertIn("error", result)

    def test_request_authorization_accept(self):
        # The Just-Works path the security review calls out (F5/F6): no
        # passkey to compare, so the old default agent auto-accepted this.
        result = self._call_agent("RequestAuthorization", GLib.Variant("(o)", (self.bluez.device_path,)))
        nid = self._one_pending_notification_id()
        self.notes.invoke(nid, "pair")
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertNotIn("error", result)

    def test_authorize_service_reject(self):
        result = self._call_agent(
            "AuthorizeService", GLib.Variant("(os)", (self.bluez.device_path, "0000110b-0000-1000-8000-00805f9b34fb")))
        nid = self._one_pending_notification_id()
        self.notes.invoke(nid, "reject")
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertIn("error", result)

    def test_dismissing_the_notification_denies(self):
        # Closed without a button tap (e.g. the shade's "Clear") must not be
        # treated as acceptance.
        result = self._call_agent("RequestConfirmation", GLib.Variant("(ou)", (self.bluez.device_path, 42)))
        nid = self._one_pending_notification_id()
        self.notes.close(nid)
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertIn("error", result)

    def test_cancel_rejects_the_pending_request(self):
        result = self._call_agent("RequestConfirmation", GLib.Variant("(ou)", (self.bluez.device_path, 42)))
        self._one_pending_notification_id()
        cancel = self._call_agent("Cancel", GLib.Variant("()", ()))
        self.assertTrue(spin(lambda: "reply" in cancel or "error" in cancel))
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertIn("error", result)

    # -- no on-screen numeric keyboard yet: refuse rather than fabricate --

    def test_request_passkey_not_implemented_is_rejected(self):
        result = self._call_agent("RequestPasskey", GLib.Variant("(o)", (self.bluez.device_path,)))
        self.assertTrue(spin(lambda: "reply" in result or "error" in result))
        self.assertIn("error", result)
        self.assertEqual(len(self.notes.notes), 0, "must not prompt for something it can't act on")


if __name__ == "__main__":
    unittest.main()
