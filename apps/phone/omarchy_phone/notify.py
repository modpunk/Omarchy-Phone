"""freedesktop notifications for incoming and missed calls, with action buttons.

This is the only module that talks to the shell. It follows docs/shell/INTEGRATION.md: the
Omarchy Phone shell is the notification server, turns `category=call.incoming` into a
full-screen call surface (actions accept/decline/silence, hints x-ophone-*), and shows a
status-bar pill for a resident `category=call` notification. On any other desktop the same
notifications are ordinary cards with buttons, and the app's own incoming page is used.
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
        self._closing: set[str] = set()
        self.server: str | None = None   # notification server name, filled in asynchronously
        self.enabled = not os.environ.get("OMARCHY_PHONE_NO_NOTIFY")
        if not self.enabled:
            return
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.bus.signal_subscribe(BUS, IFACE, "ActionInvoked", PATH, None, Gio.DBusSignalFlags.NONE,
                                      self._on_invoked)
            self.bus.signal_subscribe(BUS, IFACE, "NotificationClosed", PATH, None, Gio.DBusSignalFlags.NONE,
                                      self._on_closed)
            self._query_server()
        except GLib.Error:
            self.bus = None

    def _notify(self, key, summary, body, actions, urgency=1, category="call", resident=False, extra=None):
        if not self.bus:
            return 0
        hints = {"urgency": GLib.Variant("y", urgency), "category": GLib.Variant("s", category),
                 "desktop-entry": GLib.Variant("s", "org.omarchy.Phone")}
        if resident:
            hints["resident"] = GLib.Variant("b", True)
        for k, v in (extra or {}).items():
            hints[k] = GLib.Variant("s", v)
        replaces = self.by_key.get(key, 0)
        self._closing.discard(key)
        # async: the daemon must never block on a slow (or same-process) notification server
        self.bus.call(BUS, PATH, IFACE, "Notify",
                      GLib.Variant("(susssasa{sv}i)", ("Phone", replaces, "call-start", summary, body, actions,
                                                       hints, 0 if resident else -1)),
                      GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 5000, None, self._notified, key)

    def _notified(self, bus, res, key):
        try:
            nid = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        self.ids[nid] = key
        self.by_key[key] = nid
        if key in self._closing:  # closed before the server answered
            self._closing.discard(key)
            self.close(key)

    def _query_server(self):
        def done(bus, res):
            try:
                name = bus.call_finish(res).unpack()[0].lower()
            except GLib.Error:
                name = ""
            self.server = name
        self.bus.call(BUS, PATH, IFACE, "GetServerInformation", None, GLib.VariantType("(ssss)"),
                      Gio.DBusCallFlags.NONE, 2000, None, done)

    def shell_present(self) -> bool:
        """True when the Omarchy Phone shell (QuickShell) is the notification server: it draws its
        own full-screen incoming-call surface (docs/shell/INTEGRATION.md section 2)."""
        if os.environ.get("OMARCHY_PHONE_SHELL"):
            return os.environ["OMARCHY_PHONE_SHELL"] not in ("0", "")
        return "quickshell" in (self.server or "") or "omarchy" in (self.server or "")

    def incoming(self, call_id: str, who: str, number: str = "", detail: str = "", video: bool = False,
                 silent: bool = False):
        # action ids follow the shell contract: accept / decline / silence (+ our voicemail)
        actions = ["accept", "Accept", "decline", "Decline", "silence", "Silence",
                   "voicemail", "Voicemail", "default", "Open"]
        body = " · ".join(b for b in (number, "Wi-Fi call", detail) if b)
        extra = {"x-ophone-caller": who, "x-ophone-number": " · ".join(b for b in (number, detail) if b) or "Wi-Fi call"}
        if video:
            extra["x-ophone-video"] = "true"
        if silent:  # screened to "silent": an ordinary card, not the full-screen ringing surface
            self._notify(call_id, f"Silenced call · {who}", body, actions, urgency=1,
                         category="call.silenced", resident=True, extra=extra)
            return
        self._notify(call_id, who, body, actions, urgency=2, category="call.incoming", resident=True, extra=extra)

    def ongoing(self, call_id: str, who: str, detail: str = ""):
        """Status-bar call pill (category "call"); tapping it invokes "default"."""
        self._notify("ongoing:" + call_id, who, detail or "Call in progress", ["default", "Return to call"],
                     urgency=1, category="call", resident=True)

    def missed(self, remote: str, who: str, detail: str = ""):
        self._notify("missed:" + remote, f"Missed call · {who}", detail,
                     ["callback", "Call back", "default", "Open"], urgency=1, category="call.unanswered")

    def screened(self, remote: str, who: str, detail: str):
        self._notify("screened:" + remote, f"Screened call · {who}", detail,
                     ["allow", "Always allow", "default", "Open"], urgency=0, category="call.unanswered")

    def close(self, key: str):
        nid = self.by_key.pop(key, None)
        if not self.bus:
            return
        if nid is None:
            self._closing.add(key)  # Notify reply may still be in flight
            return
        self.ids.pop(nid, None)
        self.bus.call(BUS, PATH, IFACE, "CloseNotification", GLib.Variant("(u)", (nid,)),
                      None, Gio.DBusCallFlags.NONE, 2000, None, None)

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
