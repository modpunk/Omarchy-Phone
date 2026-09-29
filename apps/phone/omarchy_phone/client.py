"""Thin D-Bus client for phoned, shared by the UI and phonectl."""
from __future__ import annotations

import json

from gi.repository import Gio, GLib

from .daemon import IFACE, OBJECT_PATH, bus_name


class DaemonError(RuntimeError):
    pass


class Client:
    def __init__(self, profile: str = "default"):
        self.name = bus_name(profile)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._sub = 0

    def available(self) -> bool:
        try:
            r = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                   "NameHasOwner", GLib.Variant("(s)", (self.name,)), GLib.VariantType("(b)"),
                                   Gio.DBusCallFlags.NONE, 1000, None)
            return r.unpack()[0]
        except GLib.Error:
            return False

    def call(self, method: str, **args):
        try:
            r = self.bus.call_sync(self.name, OBJECT_PATH, IFACE, "Call",
                                   GLib.Variant("(ss)", (method, json.dumps(args))), GLib.VariantType("(s)"),
                                   Gio.DBusCallFlags.NONE, 5000, None)
        except GLib.Error as e:
            raise DaemonError(f"phoned is not reachable ({self.name}): {e.message}") from None
        out = json.loads(r.unpack()[0])
        if not out.get("ok"):
            raise DaemonError(out.get("error", "error"))
        return out.get("result")

    def subscribe(self, callback):
        """callback(event: dict) for every Event signal."""
        def on_signal(_c, _s, _p, _i, _sig, params):
            try:
                callback(json.loads(params.unpack()[0]))
            except ValueError:
                pass
        self._sub = self.bus.signal_subscribe(self.name, IFACE, "Event", OBJECT_PATH, None,
                                              Gio.DBusSignalFlags.NONE, on_signal)
