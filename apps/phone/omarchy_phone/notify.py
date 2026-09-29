"""freedesktop notifications for incoming and missed calls, with action buttons.

This is the only module that talks to the shell. When docs/shell/INTEGRATION.md defines
dedicated incoming-call hooks, adapt them here.
"""
from __future__ import annotations

import os
from typing import Callable

from gi.repository import Gio, GLib

BUS, PATH, IFACE = "org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications"


class Notifier:
    def __init__(self, on_action: Callable[[str, str], None]):
        """on_action(call_id_or_remote, action) is called when the user taps a notification button."""
        self.on_action = on_action
        self.bus = None
        self.ids: dict[int, str] = {}       # notification id -> call id / remote
        self.by_key: dict[str, int] = {}
        self.enabled = not os.environ.get("OMARCHY_PHONE_NO_NOTIFY")
        if not self.enabled:
            return
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(BUS, IFACE, "ActionInvoked", PATH, None, Gio.DBusSignalFlags.NONE,
                                      self._on_invoked)
            self.bus.signal_subscribe(BUS, IFACE, "NotificationClosed", PATH, None, Gio.DBusSignalFlags.NONE,
                                      self._on_closed)
        except GLib.Error:
            self.bus = None

    def _notify(self, key, summary, body, actions, urgency=1, category="call", resident=False, replaces=0):
        if not self.bus:
            return 0
        hints = {"urgency": GLib.Variant("y", urgency), "category": GLib.Variant("s", category),
                 "desktop-entry": GLib.Variant("s", "org.omarchy.Phone")}
        if resident:
            hints["resident"] = GLib.Variant("b", True)
        try:
            res = self.bus.call_sync(BUS, PATH, IFACE, "Notify",
                                     GLib.Variant("(susssasa{sv}i)", ("Omarchy Phone", replaces, "call-start",
                                                                      summary, body, actions, hints,
                                                                      0 if resident else -1)),
                                     GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            return 0
        nid = res.unpack()[0]
        self.ids[nid] = key
        self.by_key[key] = nid
        return nid

    def incoming(self, call_id: str, who: str, detail: str = "", silent: bool = False):
        actions = ["answer", "Answer", "decline", "Decline", "voicemail", "Voicemail", "default", "Open"]
        self._notify(call_id, f"Incoming call · {who}", detail, actions,
                     urgency=1 if silent else 2, category="call.incoming", resident=not silent)

    def missed(self, remote: str, who: str, detail: str = ""):
        self._notify("missed:" + remote, f"Missed call · {who}", detail,
                     ["callback", "Call back", "default", "Open"], urgency=1, category="call.unanswered")

    def screened(self, remote: str, who: str, detail: str):
        self._notify("screened:" + remote, f"Screened call · {who}", detail,
                     ["allow", "Always allow", "default", "Open"], urgency=0, category="call.unanswered")

    def close(self, key: str):
        nid = self.by_key.pop(key, None)
        if nid and self.bus:
            self.ids.pop(nid, None)
            try:
                self.bus.call_sync(BUS, PATH, IFACE, "CloseNotification", GLib.Variant("(u)", (nid,)),
                                   None, Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass

    def _on_invoked(self, _c, _s, _p, _i, _sig, params):
        nid, action = params.unpack()
        key = self.ids.get(nid)
        if key is not None:
            self.on_action(key, action)

    def _on_closed(self, _c, _s, _p, _i, _sig, params):
        nid = params.unpack()[0]
        key = self.ids.pop(nid, None)
        if key is not None and self.by_key.get(key) == nid:
            del self.by_key[key]
