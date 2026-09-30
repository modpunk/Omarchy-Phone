#!/usr/bin/env python3
# Preview-only stand-in for a GTK4 app with a text field (the real
# apps/phone dial/search field doesn't exist yet). GTK4 speaks
# text-input-v3 for its Entry/SearchEntry widgets on Wayland, so this is
# what exercises the shell's auto-show/auto-hide path in shell/preview/run.sh.
# Every keystroke that lands in the entry is printed to stdout so the preview
# can grep its log and prove typing (not just visibility) worked.
import sys
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402


def on_activate(app):
    win = Gtk.ApplicationWindow(application=app, title="OSK test field")
    win.set_default_size(360, 240)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.append(Gtk.Label(label="Omarchy Phone OSK test"))
    entry = Gtk.Entry()
    entry.set_placeholder_text("type here")
    entry.connect("changed", lambda e: print("TEXT:" + e.get_text(), flush=True))
    box.append(entry)
    win.set_child(box)
    win.present()
    # Focus the entry once the window is actually up, so a real focus (and
    # therefore a real text-input-v3 enable()) happens, not just a property set.
    GLib.timeout_add(150, lambda: (entry.grab_focus(), False)[1])


app = Gtk.Application(application_id="org.omarchyphone.preview.oskfield")
app.connect("activate", on_activate)
sys.exit(app.run(None))
