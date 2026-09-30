"""phoned: the Omarchy Phone session daemon.

Owns the store, backends and CallManager and exposes them on the session bus:

  bus name   org.omarchy.Phone.Daemon            (+ ".<profile>" for extra local instances)
  object     /org/omarchy/Phone
  interface  org.omarchy.Phone1
    method Call(s method, s json_args) -> (s json_result)
    signal Event(s json)

See docs/phone/API.md for the method list.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys

from gi.repository import Gio, GLib

from . import keyring, numbers
from .audio import AudioRouter
from .backends import BackendError, create
from .calls import CallManager
from .notify import Notifier
from .sip_account import SipAccount, to_baresip_line, validate
from .store import Store
from .vcard import Contact

BUS_NAME = "org.omarchy.Phone.Daemon"
OBJECT_PATH = "/org/omarchy/Phone"
IFACE = "org.omarchy.Phone1"
XML = f"""
<node>
  <interface name="{IFACE}">
    <method name="Call">
      <arg type="s" name="method" direction="in"/>
      <arg type="s" name="args" direction="in"/>
      <arg type="s" name="result" direction="out"/>
    </method>
    <signal name="Event"><arg type="s" name="event"/></signal>
  </interface>
</node>
"""


def bus_name(profile: str = "default") -> str:
    return BUS_NAME if profile in ("", "default") else f"{BUS_NAME}.{re.sub(r'[^A-Za-z0-9_]', '_', profile)}"


def db_path(profile: str) -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "omarchy-phone", "phone.db" if profile in ("", "default") else f"{profile}.db")


class PhoneService:
    def __init__(self, profile="default", backend="loopback", number="", display="", ui_cmd=None, baresip=""):
        self.profile = profile
        self.store = Store(db_path(profile))
        if number:
            self.store.set("own_number", numbers.normalize(number, self.store.get("region")) or number)
        self.store.set("backend", backend)
        self.conn: Gio.DBusConnection | None = None
        self.ui_cmd = ui_cmd
        self.audio = AudioRouter()
        self.notifier = Notifier(self._on_notification)
        config = {"profile": profile, "number": self.store.get("own_number"), "display": display or profile}
        if baresip:  # host:port of baresip's ctrl_tcp
            host, _, port = baresip.rpartition(":")
            config.update(host=host or "127.0.0.1", port=int(port))
        if backend == "sip":
            line = self._sip_account_line()
            if line:
                config["account_line"] = line
        backends = [create(backend, config)]
        if backend != "loopback":
            backends.append(create("loopback", {"profile": profile, "number": self.store.get("own_number"),
                                                "display": display or profile}))
        self.mgr = CallManager(self.store, backends, notifier=self.notifier, audio=self.audio, emit=self.broadcast)

    def _sip_account_line(self) -> str | None:
        """Rebuild the baresip account line from Store (non-secret fields) + the keyring (password),
        for the "sip" backend to provision at connect. Never persisted anywhere as a whole line."""
        saved = self.store.get("sip_account")
        if not saved:
            return None
        try:
            password = keyring.get_password(self.profile) or ""
        except keyring.KeyringError as e:
            self.broadcast({"type": "error", "detail": f"SIP password unavailable: {e}"})
            return None
        return to_baresip_line(SipAccount.from_dict(saved), password)

    # ------------------------------------------------------------ events
    def broadcast(self, event: dict):
        if event.get("type") == "ended":
            GLib.idle_add(lambda: self.broadcast({"type": "history"}) and False)
        if event.get("type") == "incoming" and not self.notifier.shell_present():
            self._ensure_ui(event["call"]["id"])  # the phone shell draws its own call surface
        if self.conn:
            self.conn.emit_signal(None, OBJECT_PATH, IFACE, "Event", GLib.Variant("(s)", (json.dumps(event),)))

    def _on_notification(self, key, action):
        if action in ("default", "callback", "accept", "answer"):
            self._ensure_ui()  # bring the window up (in-call page once answered)
        self.mgr.notification_action(key, action)

    def _ensure_ui(self, call_id=None):
        """Bring up the UI for an incoming call. The UI is a single-instance GtkApplication, so
        running it again just forwards the arguments to the running window."""
        if not self.ui_cmd or os.environ.get("OMARCHY_PHONE_NO_UI_LAUNCH"):
            return
        cmd = shlex.split(self.ui_cmd) + ["--profile", self.profile]
        if call_id:
            cmd += ["--incoming", call_id]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    # ------------------------------------------------------------ D-Bus
    def export(self, conn: Gio.DBusConnection):
        self.conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object(OBJECT_PATH, node.interfaces[0], self._on_method, None, None)

    def _on_method(self, conn, sender, path, iface, method, params, invocation):
        name, raw = params.unpack()
        try:
            args = json.loads(raw) if raw else {}
            result = self.call(name, args)
            invocation.return_value(GLib.Variant("(s)", (json.dumps({"ok": True, "result": result}),)))
        except Exception as e:  # report every failure to the caller, keep the daemon alive
            invocation.return_value(GLib.Variant("(s)", (json.dumps({"ok": False, "error": str(e),
                                                                      "kind": type(e).__name__}),)))

    def call(self, name: str, a: dict):
        fn = getattr(self, "m_" + name, None)
        if fn is None:
            raise AttributeError(f"unknown method {name!r}")
        return fn(**a)

    # ------------------------------------------------------------ methods: calls
    def m_state(self):
        s = self.mgr.state()
        s["profile"] = self.profile
        s["own_number"] = self.store.get("own_number")
        return s

    def m_dial(self, address, video=False):
        return self.mgr.dial(address, video)

    def m_answer(self, call_id, video=False):
        self.mgr.answer(call_id, video)

    def m_decline(self, call_id, voicemail=False):
        self.mgr.decline(call_id, voicemail)

    def m_hangup(self, call_id=None):
        ids = [call_id] if call_id else [c.id for c in self.mgr.live_calls()]
        for cid in ids:
            self.mgr.hangup(cid)

    def m_hold(self, call_id, on=True):
        self.mgr.hold(call_id, on)

    def m_mute(self, on=True, call_id=None):
        self.mgr.mute(call_id, on)

    def m_video(self, call_id, on=True):
        self.mgr.video(call_id, on)

    def m_dtmf(self, call_id, digits):
        self.mgr.dtmf(call_id, digits)

    def m_merge(self, call_ids=None):
        return self.mgr.merge(call_ids)

    def m_split(self, call_id):
        self.mgr.split(call_id)

    def m_speaker(self, on=True):
        return self.mgr.set_speaker(on)

    def m_routes(self):
        return self.audio.routes()

    def m_route(self, id):
        return self.mgr.set_route(int(id))

    def m_simulate_incoming(self, remote, display="", video=False):
        return self.mgr.simulate_incoming(remote, display, video)

    def m_directory(self):
        b = self.mgr.backends.get("loopback")
        return b.directory() if b else []

    def m_show(self, page="keypad", number=""):
        self.broadcast({"type": "show", "page": page, "number": number})

    # ------------------------------------------------------------ methods: contacts
    def _changed(self, what):
        self.broadcast({"type": what})

    def m_contacts(self, query="", group=None):
        return [c.to_dict() for c in self.store.contacts(query, group)]

    def m_favorites(self):
        return [c.to_dict() for c in self.store.favorites()]

    def m_groups(self):
        return self.store.groups()

    def m_contact(self, id):
        c = self.store.contact(int(id))
        return c.to_dict() if c else None

    def m_lookup(self, address):
        c = self.store.contact_for_number(numbers.normalize_address(address, self.store.get("region")) or address)
        return c.to_dict() if c else None

    def m_save_contact(self, contact):
        region = self.store.get("region")
        c = Contact.from_dict(contact)
        c.numbers = [(lbl, numbers.normalize_address(v, region) or v) for lbl, v in c.numbers if v.strip()]
        cid = self.store.save_contact(c)
        self._changed("contacts")
        return cid

    def m_delete_contact(self, id):
        self.store.delete_contact(int(id))
        self._changed("contacts")

    def m_favorite(self, id, on=True):
        self.store.set_favorite(int(id), on)
        self._changed("contacts")

    def m_set_groups(self, id, groups):
        self.store.set_groups(int(id), groups)
        self._changed("contacts")

    def m_import_vcard(self, text=None, path=None):
        if path:
            with open(os.path.expanduser(path), encoding="utf-8", errors="replace") as f:
                text = f.read()
        added, updated = self.store.import_vcard(text or "")
        self._changed("contacts")
        return {"added": added, "updated": updated}

    def m_export_vcard(self, path=None, ids=None, version="3.0"):
        text = self.store.export_vcard(ids, version)
        if path:
            path = os.path.expanduser(path)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return {"path": path, "count": text.count("BEGIN:VCARD")}
        return text

    # ------------------------------------------------------------ methods: history, screening, settings
    def m_history(self, limit=200, missed=False):
        return self.store.history(limit, missed)

    def m_clear_history(self):
        self.store.clear_history()
        self._changed("history")

    def m_lists(self, kind=None):
        return self.store.list_entries(kind)

    def m_list_add(self, kind, pattern, action=None, note=""):
        region = self.store.get("region")
        if not any(ch in pattern for ch in "*?[") and not numbers.is_uri(pattern):
            pattern = numbers.normalize(pattern, region) or pattern
        self.store.add_list_entry(kind, pattern, action, note)
        self._changed("lists")
        return pattern

    def m_list_remove(self, kind, pattern):
        self.store.remove_list_entry(kind, pattern)
        self._changed("lists")

    def m_settings(self):
        return self.store.settings()

    def m_set(self, key, value):
        if key == "sip_account":
            raise ValueError("use save_sip_account / delete_sip_account (the password can't go through set)")
        self.store.set(key, value)
        self._changed("settings")
        if key == "dnd":
            self.broadcast({"type": "dnd", "on": bool(value)})

    def m_dnd(self, on=None):
        if on is None:
            on = not self.store.get("dnd")
        self.m_set("dnd", bool(on))
        return bool(on)

    def m_detect(self, text):
        return [{"start": m.start, "end": m.end, "raw": m.raw, "e164": m.e164,
                 "display": numbers.format_number(m.e164, self.store.get("region"))}
                for m in numbers.find_numbers(text, self.store.get("region"))]

    # ------------------------------------------------------------ methods: SIP account, registration
    def m_registration(self, backend=None, refresh=False):
        if refresh:
            self.mgr.refresh_registration(backend)
        return self.mgr.registration if backend is None else self.mgr.registration.get(backend, {})

    def m_sip_account(self):
        saved = self.store.get("sip_account")
        return dict(saved) if saved else None

    def m_save_sip_account(self, account, password=None):
        existing = self.store.get("sip_account") or {}
        acc = SipAccount.from_dict(account)
        if not acc.domain and "@" in acc.username:
            acc.username, acc.domain = acc.username.split("@", 1)
        has_password = bool(existing.get("has_password")) and not password  # blank password = keep it
        errors = validate(acc, require_password=not has_password, password=password)
        if errors:
            raise ValueError("; ".join(errors))
        if password:
            keyring.set_password(self.profile, password)
            has_password = True
        d = acc.to_dict()
        d["has_password"] = has_password
        self.store.set("sip_account", d)
        self._changed("settings")
        self._push_sip_account()
        return d

    def m_delete_sip_account(self):
        if self.store.get("sip_account"):
            self.store.set("sip_account", None)
            try:
                keyring.clear_password(self.profile)
            except keyring.KeyringError as e:
                self.broadcast({"type": "error", "detail": str(e)})
            if "sip" in self.mgr.backends:
                self.mgr.clear_account("sip")
            self._changed("settings")

    def _push_sip_account(self):
        """Push the just-saved account to a live "sip" backend now, instead of waiting for the
        next daemon restart to pick it up via `_sip_account_line()`."""
        b = self.mgr.backends.get("sip")
        if not b:
            return
        line = self._sip_account_line()
        if line:
            self.mgr.apply_account("sip", line)

    def shutdown(self):
        self.mgr.stop()
        self.store.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="phoned", description="Omarchy Phone daemon")
    ap.add_argument("--profile", default=os.environ.get("OMARCHY_PHONE_PROFILE", "default"),
                    help="instance name; extra instances let you call yourself over loopback")
    ap.add_argument("--backend", default="loopback", choices=["loopback", "sip"])
    ap.add_argument("--number", default="", help="this instance's own number (loopback directory, spoof filter)")
    ap.add_argument("--baresip", default=os.environ.get("OMARCHY_PHONE_BARESIP", ""), metavar="HOST:PORT",
                    help="baresip ctrl_tcp address for --backend sip (default 127.0.0.1:4444)")
    ap.add_argument("--display", default="", help="display name sent to loopback peers")
    ap.add_argument("--ui-cmd", default=os.environ.get("OMARCHY_PHONE_UI_CMD", ""),
                    help="command that opens the UI (for incoming calls)")
    args = ap.parse_args(argv)

    loop = GLib.MainLoop()
    svc = PhoneService(args.profile, args.backend, args.number, args.display, args.ui_cmd or None, args.baresip)

    def on_bus(conn, _name):
        svc.export(conn)

    def on_lost(conn, name):
        if conn is not None and svc.conn is None:
            print(f"phoned: could not own {name} (already running?)", file=sys.stderr)
        loop.quit()

    Gio.bus_own_name(Gio.BusType.SESSION, bus_name(args.profile), Gio.BusNameOwnerFlags.NONE,
                     on_bus, lambda *_: print(f"phoned: {bus_name(args.profile)} ready", flush=True), on_lost)
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: loop.quit() or False)
    try:
        loop.run()
    finally:
        svc.shutdown()


if __name__ == "__main__":
    main()
