"""Omarchy Phone UI: GTK4 + libadwaita, touch-first at 375x667.

The UI holds no call state of its own; it renders what phoned reports and sends user
intents back over D-Bus. Run `bin/omarchy-phone` (it starts phoned if needed).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk  # noqa: E402

from . import numbers  # noqa: E402
from .client import Client, DaemonError  # noqa: E402

APP_ID = "org.omarchy.Phone"
HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
.keypad-display { font-size: 28px; font-weight: 300; }
.keypad-display text { min-height: 44px; }
.key { min-width: 76px; min-height: 60px; border-radius: 999px; padding: 0; }
.key .digit { font-size: 26px; font-weight: 400; }
.key .letters { font-size: 9px; letter-spacing: 2px; opacity: .6; }
.call-btn { min-width: 68px; min-height: 68px; border-radius: 999px;
            background: #2ec27e; color: white; }
.call-btn:hover { background: #33d17a; }
.end-btn { min-width: 68px; min-height: 68px; border-radius: 999px;
           background: #e01b24; color: white; }
.end-btn:hover { background: #f01e28; }
.round { min-width: 64px; min-height: 64px; border-radius: 999px; }
menubutton.round > button { min-width: 64px; min-height: 64px; border-radius: 999px; }
.round:checked { background: alpha(currentColor, .85); color: @window_bg_color; }
.ctl-label { font-size: 11px; opacity: .8; }
.caller { font-size: 26px; font-weight: 600; }
.call-status { font-size: 15px; opacity: .75; font-variant-numeric: tabular-nums; }
.screen-reason { font-size: 13px; padding: 4px 10px; border-radius: 999px;
                 background: alpha(#e5a50a, .2); }
.video-area { background: #111; border-radius: 12px; color: #ddd; min-height: 150px; }
.fav-tile { padding: 8px 4px; border-radius: 12px; }
.missed { color: #e01b24; }
.chip { border-radius: 999px; padding: 4px 12px; }
"""

KEYS = [("1", ""), ("2", "ABC"), ("3", "DEF"), ("4", "GHI"), ("5", "JKL"), ("6", "MNO"),
        ("7", "PQRS"), ("8", "TUV"), ("9", "WXYZ"), ("*", ""), ("0", "+"), ("#", "")]
STATUS_TEXT = {"answered": "", "missed": "Missed", "rejected": "Declined", "blocked": "Blocked",
               "voicemail": "Voicemail", "cancelled": "Cancelled", "busy": "Busy", "failed": "Failed",
               "no_answer": "No answer", "calling": "", "ringing": ""}
ACTION_LABELS = [("ring", "Ring"), ("silent", "Silence"), ("voicemail", "Send to voicemail"), ("reject", "Reject")]


def ago(ts: float) -> str:
    d = time.time() - (ts or 0)
    if d < 60:
        return "now"
    if d < 3600:
        return f"{int(d // 60)}m"
    if d < 86400:
        return f"{int(d // 3600)}h"
    return time.strftime("%b %d", time.localtime(ts))


def duration(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def pretty(addr: str, region="US") -> str:
    return numbers.format_number(addr, region) if addr.startswith("+") else addr


def icon_button(icon, tooltip, cb, *css):
    b = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    for c in css or ("flat",):
        b.add_css_class(c)
    b.connect("clicked", lambda *_: cb())
    return b


def clear(box):
    child = box.get_first_child()
    while child:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


class PhoneWindow(Adw.ApplicationWindow):
    def __init__(self, app, client: Client):
        super().__init__(application=app, title="Phone", default_width=375, default_height=667)
        self.set_size_request(320, 480)
        self.c = client
        self.region = "US"
        self.settings = {}
        self.calls: list[dict] = []
        self.history_filter = "all"
        self.contacts_cache: list[dict] = []
        self.timer = 0
        self.dtmf_open = False

        self.toasts = Adw.ToastOverlay()
        self.nav = Adw.NavigationView()
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)
        self.nav.add(self._main_page())
        self.connect("notify::is-active", self._on_active)
        self.refresh_all()

    # ============================================================ helpers
    def rpc(self, method, **kw):
        try:
            return self.c.call(method, **kw)
        except DaemonError as e:
            self.toast(str(e))
            return None

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=3))

    def copy(self, text):
        self.get_clipboard().set(text)
        self.toast(f"Copied {text}")

    def dial(self, address, video=False):
        r = self.rpc("dial", address=address, video=video)
        if r:
            self.refresh_calls()

    def confirm_call(self, addr):
        """Tap-to-call on a number detected in text: confirm first (a mis-tap should not dial)."""
        d = Adw.AlertDialog(heading=pretty(addr, self.region), body="Detected phone number")
        for rid, label in (("cancel", "Cancel"), ("copy", "Copy"), ("video", "Video"), ("call", "Call")):
            d.add_response(rid, label)
        d.set_response_appearance("call", Adw.ResponseAppearance.SUGGESTED)
        d.set_default_response("call")
        d.set_close_response("cancel")

        def done(dlg, res):
            r = dlg.choose_finish(res)
            if r in ("call", "video"):
                self.dial(addr, video=r == "video")
            elif r == "copy":
                self.copy(addr)
        d.choose(self, None, done)

    def on_link(self, _label, uri):
        if uri.startswith("tel:"):
            self.confirm_call(uri[4:])
            return True
        return False

    # ============================================================ main page
    def _main_page(self):
        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self._favorites(), "favorites", "Favorites", "starred-symbolic")
        self.stack.add_titled_with_icon(self._recents(), "recents", "Recents", "document-open-recent-symbolic")
        self.stack.add_titled_with_icon(self._contacts(), "contacts", "Contacts", "system-users-symbolic")
        self.stack.add_titled_with_icon(self._keypad(), "keypad", "Keypad", "input-dialpad-symbolic")
        self.stack.set_visible_child_name("keypad")

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="Phone")
        header.set_title_widget(self.title)
        self.dnd_btn = Gtk.ToggleButton(icon_name="notifications-disabled-symbolic", tooltip_text="Do not disturb")
        self.dnd_handler = self.dnd_btn.connect("toggled", lambda b: self.rpc("dnd", on=b.get_active()))
        header.pack_start(self.dnd_btn)
        menu = Gio.Menu()
        menu.append("New contact", "win.new-contact")
        menu.append("Import vCard…", "win.import")
        menu.append("Export vCard…", "win.export")
        menu.append("Settings", "win.settings")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        for name, cb in (("new-contact", lambda: self.edit_contact(None)), ("import", self.import_vcard),
                         ("export", self.export_vcard), ("settings", self.open_settings)):
            act = Gio.SimpleAction(name=name)
            act.connect("activate", lambda *_a, cb=cb: cb())
            self.add_action(act)

        self.banner = Adw.Banner(title="Call in progress", button_label="Return")
        self.banner.connect("button-clicked", lambda *_: self.show_call_page())

        bar = Adw.ViewSwitcherBar(stack=self.stack, reveal=True)
        tv = Adw.ToolbarView()
        tv.add_top_bar(header)
        tv.add_top_bar(self.banner)
        tv.set_content(self.stack)
        tv.add_bottom_bar(bar)
        self.stack.connect("notify::visible-child-name", lambda *_: self._on_tab())
        return Adw.NavigationPage(title="Phone", tag="main", child=tv)

    def _on_tab(self):
        name = self.stack.get_visible_child_name() or ""
        self.title.set_title({"favorites": "Favorites", "recents": "Recents", "contacts": "Contacts"}.get(name, "Phone"))

    def select_tab(self, name):
        self.nav.pop_to_tag("main")
        self.stack.set_visible_child_name(name)

    # ------------------------------------------------------------ favorites
    def _favorites(self):
        self.fav_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=3,
                                   max_children_per_line=3, homogeneous=True, row_spacing=6, column_spacing=6,
                                   margin_top=12, margin_start=12, margin_end=12, valign=Gtk.Align.START)
        self.fav_empty = Adw.StatusPage(icon_name="starred-symbolic", title="No favorites",
                                        description="Star a contact to call them with one tap.")
        self.fav_stack = Gtk.Stack()
        self.fav_stack.add_named(Gtk.ScrolledWindow(child=self.fav_box, vexpand=True), "list")
        self.fav_stack.add_named(self.fav_empty, "empty")
        return self.fav_stack

    def refresh_favorites(self):
        favs = self.rpc("favorites") or []
        clear(self.fav_box)
        self.fav_stack.set_visible_child_name("list" if favs else "empty")
        for c in favs:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.append(Adw.Avatar(size=64, text=c["name"], show_initials=True))
            box.append(Gtk.Label(label=c["name"].split(" ")[0], ellipsize=3, max_width_chars=10))
            btn = Gtk.Button(child=box, tooltip_text=f"Call {c['name']}")
            btn.add_css_class("flat")
            btn.add_css_class("fav-tile")
            if c["numbers"]:
                btn.connect("clicked", lambda *_a, n=c["numbers"][0][1]: self.dial(n))
            lp = Gtk.GestureLongPress()
            lp.connect("pressed", lambda *_a, cid=c["id"]: self.show_contact(cid))
            btn.add_controller(lp)
            self.fav_box.append(btn)

    # ------------------------------------------------------------ recents
    def _recents(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tg = Adw.ToggleGroup(margin_top=8, margin_bottom=4, margin_start=48, margin_end=48)
        tg.add(Adw.Toggle(name="all", label="All"))
        tg.add(Adw.Toggle(name="missed", label="Missed"))
        tg.set_active_name("all")
        tg.connect("notify::active-name", lambda g, _p: self._set_history_filter(g.get_active_name()))
        box.append(tg)
        self.recents_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recents_list.add_css_class("boxed-list")
        self.recents_list.set_margin_start(12)
        self.recents_list.set_margin_end(12)
        self.recents_list.set_margin_bottom(12)
        self.recents_list.set_placeholder(Adw.StatusPage(icon_name="document-open-recent-symbolic",
                                                         title="No calls yet"))
        box.append(Gtk.ScrolledWindow(child=self.recents_list, vexpand=True))
        return box

    def _set_history_filter(self, f):
        self.history_filter = f
        self.refresh_recents()

    def refresh_recents(self):
        rows = self.rpc("history", missed=self.history_filter == "missed") or []
        clear(self.recents_list)
        for h in rows:
            name = h["name"] or pretty(h["remote"], self.region) or "Unknown"
            status = STATUS_TEXT.get(h["status"], h["status"])
            icon = "call-incoming-symbolic" if h["direction"] == "in" else "call-outgoing-symbolic"
            if h["status"] in ("missed", "blocked", "rejected", "voicemail"):
                icon = "call-missed-symbolic"
            reason = h["reason"] or ""
            if status and reason.lower().startswith(status.lower()):
                status = ""  # "Blocked (+1900*)" already says it
            bits = [b for b in (status, duration(h["duration"]) if h["duration"] else "",
                                "video" if h["video"] else "", reason, ago(h["started"])) if b]
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=GLib.markup_escape_text(" · ".join(bits)),
                                activatable=True)
            img = Gtk.Image(icon_name=icon)
            if h["status"] in ("missed",):
                img.add_css_class("missed")
                row.add_css_class("missed-row")
            row.add_prefix(img)
            row.connect("activated", lambda *_a, r=h["remote"]: self.dial(r))
            row.add_suffix(self._number_menu(h["remote"], h["name"]))
            self.recents_list.append(row)

    def _number_menu(self, remote, name=""):
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        known = self.rpc("lookup", address=remote) if remote else None
        items = [("Call", lambda: self.dial(remote)), ("Video call", lambda: self.dial(remote, True)),
                 ("Copy number", lambda: self.copy(remote))]
        if known:
            items.append(("Open contact", lambda: self.show_contact(known["id"])))
        else:
            items.append(("Add to contacts", lambda: self.edit_contact(None, number=remote,
                                                                         name="" if name == pretty(remote) else name)))
        items += [("Always allow", lambda: self._list_add("allow", remote)),
                  ("Block", lambda: self._list_add("block", remote)),
                  ("Report spam", lambda: self._list_add("spam", remote))]
        for label, cb in items:
            b = Gtk.Button(label=label, halign=Gtk.Align.FILL)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, cb=cb: (pop.popdown(), cb()))
            box.append(b)
        pop.set_child(box)
        mb = Gtk.MenuButton(icon_name="view-more-symbolic", popover=pop, valign=Gtk.Align.CENTER,
                            tooltip_text="More")
        mb.add_css_class("flat")
        return mb

    def _list_add(self, kind, remote):
        p = self.rpc("list_add", kind=kind, pattern=remote)
        if p:
            self.toast({"allow": "Always allowed", "block": "Blocked", "spam": "Reported as spam"}[kind] + f": {pretty(p)}")

    # ------------------------------------------------------------ contacts
    def _contacts(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        top = Gtk.Box(spacing=6, margin_top=8, margin_start=12, margin_end=12)
        self.search = Gtk.SearchEntry(placeholder_text="Search name or number", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.refresh_contacts())
        self.group_model = Gtk.StringList.new(["All"])
        self.group_dd = Gtk.DropDown(model=self.group_model, tooltip_text="Group")
        self.group_dd.connect("notify::selected", lambda *_: self.refresh_contacts())
        top.append(self.search)
        top.append(self.group_dd)
        box.append(top)
        self.contacts_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=12, margin_end=12,
                                         margin_bottom=12)
        self.contacts_list.add_css_class("boxed-list")
        empty = Adw.StatusPage(icon_name="system-users-symbolic", title="No contacts",
                               description="Import a vCard file from the menu, or add one.")
        self.contacts_list.set_placeholder(empty)
        box.append(Gtk.ScrolledWindow(child=self.contacts_list, vexpand=True))
        return box

    def refresh_groups(self):
        groups = self.rpc("groups") or []
        cur = self.group_dd.get_selected_item()
        cur = cur.get_string() if cur else "All"
        self.group_model.splice(0, self.group_model.get_n_items(), ["All"] + groups)
        if cur in groups:
            self.group_dd.set_selected(groups.index(cur) + 1)

    def refresh_contacts(self):
        item = self.group_dd.get_selected_item()
        group = item.get_string() if item and self.group_dd.get_selected() > 0 else None
        cs = self.rpc("contacts", query=self.search.get_text(), group=group) or []
        self.contacts_cache = cs
        clear(self.contacts_list)
        for c in cs:
            sub = pretty(c["numbers"][0][1], self.region) if c["numbers"] else (c["org"] or "")
            row = Adw.ActionRow(title=GLib.markup_escape_text(c["name"]), subtitle=GLib.markup_escape_text(sub),
                                activatable=True)
            row.add_prefix(Adw.Avatar(size=36, text=c["name"], show_initials=True))
            if c["favorite"]:
                row.add_suffix(Gtk.Image(icon_name="starred-symbolic"))
            if c["numbers"]:
                row.add_suffix(icon_button("call-start-symbolic", "Call", lambda n=c["numbers"][0][1]: self.dial(n)))
            row.connect("activated", lambda *_a, cid=c["id"]: self.show_contact(cid))
            self.contacts_list.append(row)

    def show_contact(self, cid):
        c = self.rpc("contact", id=cid)
        if not c:
            return
        page = Adw.PreferencesPage()
        head = Adw.PreferencesGroup()
        hb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_bottom=6)
        hb.append(Adw.Avatar(size=96, text=c["name"], show_initials=True))
        name = Gtk.Label(label=c["name"], wrap=True, justify=Gtk.Justification.CENTER)
        name.add_css_class("title-1")
        hb.append(name)
        if c["org"]:
            hb.append(Gtk.Label(label=c["org"], css_classes=["dim-label"]))
        head.add(hb)
        page.add(head)

        nums = Adw.PreferencesGroup(title="Numbers")
        for label, value in c["numbers"]:
            row = Adw.ActionRow(title=GLib.markup_escape_text(pretty(value, self.region)), subtitle=label,
                                activatable=True, title_selectable=True)
            row.connect("activated", lambda *_a, v=value: self.dial(v))
            row.add_suffix(icon_button("edit-copy-symbolic", "Copy", lambda v=value: self.copy(v)))
            row.add_suffix(icon_button("camera-video-symbolic", "Video call", lambda v=value: self.dial(v, True)))
            row.add_suffix(icon_button("call-start-symbolic", "Call", lambda v=value: self.dial(v)))
            nums.add(row)
        page.add(nums)

        more = Adw.PreferencesGroup()
        fav = Adw.SwitchRow(title="Favorite", active=c["favorite"])
        fav.connect("notify::active", lambda r, _p: self.rpc("favorite", id=cid, on=r.get_active()))
        more.add(fav)
        groups = Adw.EntryRow(title="Groups (comma separated)", text=", ".join(c["groups"]), show_apply_button=True)
        groups.connect("apply", lambda r: self.rpc("set_groups", id=cid,
                                                   groups=[g.strip() for g in r.get_text().split(",") if g.strip()]))
        more.add(groups)
        for e in c["emails"]:
            more.add(Adw.ActionRow(title=GLib.markup_escape_text(e), subtitle="email", title_selectable=True))
        page.add(more)

        if c["note"]:
            ng = Adw.PreferencesGroup(title="Notes")
            note = Gtk.Label(use_markup=True, wrap=True, xalign=0, selectable=True,
                             label=numbers.linkify(c["note"], self.region))
            note.connect("activate-link", self.on_link)   # tap-to-call on numbers inside notes
            ng.add(note)
            page.add(ng)

        actions = Adw.PreferencesGroup()
        for title, cb, css in (("Edit", lambda: self.edit_contact(c), None),
                               ("Share as vCard…", lambda: self.export_vcard([cid]), None),
                               ("Block all numbers", lambda: [self._list_add("block", v) for _, v in c["numbers"]],
                                "destructive-action"),
                               ("Delete contact", lambda: self._delete_contact(cid), "destructive-action")):
            br = Adw.ButtonRow(title=title)
            if css:
                br.add_css_class(css)
            br.connect("activated", lambda *_a, cb=cb: cb())
            actions.add(br)
        page.add(actions)
        self._push(c["name"], "contact", page)

    def _delete_contact(self, cid):
        self.rpc("delete_contact", id=cid)
        self.nav.pop()

    def _push(self, title, tag, child, header=True):
        if header:
            tv = Adw.ToolbarView()
            tv.add_top_bar(Adw.HeaderBar())
            tv.set_content(child)
            child = tv
        page = Adw.NavigationPage(title=title, tag=tag, child=child)
        self.nav.push(page)
        return page

    def edit_contact(self, c, number="", name=""):
        c = c or {"id": None, "name": name, "numbers": [["cell", number]] if number else [], "groups": [],
                  "note": "", "org": "", "emails": [], "favorite": False, "given": "", "family": "", "uid": ""}
        page = Adw.PreferencesPage()
        g = Adw.PreferencesGroup()
        name_row = Adw.EntryRow(title="Name", text=c["name"])
        org_row = Adw.EntryRow(title="Company", text=c.get("org", ""))
        g.add(name_row)
        g.add(org_row)
        page.add(g)
        ng = Adw.PreferencesGroup(title="Phone numbers or SIP addresses")
        num_rows = []
        existing = list(c["numbers"]) + [["cell", ""]]
        for label, value in existing[:max(3, len(existing))]:
            r = Adw.EntryRow(title=label.capitalize(), text=pretty(value, self.region) if value else "")
            r.set_input_purpose(Gtk.InputPurpose.PHONE)
            paste = icon_button("edit-paste-symbolic", "Paste number", lambda r=r: self._paste_into(r))
            r.add_suffix(paste)
            num_rows.append((label, r))
            ng.add(r)
        page.add(ng)
        og = Adw.PreferencesGroup()
        groups_row = Adw.EntryRow(title="Groups (comma separated)", text=", ".join(c["groups"]))
        note_row = Adw.EntryRow(title="Note", text=c.get("note", ""))
        og.add(groups_row)
        og.add(note_row)
        page.add(og)

        def save(*_):
            d = dict(c)
            d["name"] = name_row.get_text().strip()
            d["org"] = org_row.get_text().strip()
            d["numbers"] = [[lbl, r.get_text()] for lbl, r in num_rows if r.get_text().strip()]
            d["groups"] = [x.strip() for x in groups_row.get_text().split(",") if x.strip()]
            d["note"] = note_row.get_text()
            if not d["name"] and not d["numbers"]:
                self.toast("Add a name or a number")
                return
            cid = self.rpc("save_contact", contact=d)
            if cid:
                self.nav.pop()
                if c["id"]:
                    self.nav.pop()
                self.show_contact(cid)

        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        sb = Gtk.Button(label="Save")
        sb.add_css_class("suggested-action")
        sb.connect("clicked", save)
        hb.pack_end(sb)
        tv.add_top_bar(hb)
        tv.set_content(page)
        self._push("Edit contact" if c["id"] else "New contact", "edit", tv, header=False)

    def _paste_into(self, entry):
        def got(clip, res):
            try:
                text = clip.read_text_finish(res) or ""
            except GLib.Error:
                text = ""
            n = numbers.first_number(text, self.region)
            if n:
                entry.set_text(pretty(n, self.region))
            else:
                self.toast("No phone number on the clipboard")
        self.get_clipboard().read_text_async(None, got)

    # ------------------------------------------------------------ keypad
    def _keypad(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=16, margin_end=16,
                        margin_bottom=12, margin_top=4, valign=Gtk.Align.END, vexpand=True)
        self.chip = Gtk.Button(halign=Gtk.Align.CENTER, visible=False)
        self.chip.add_css_class("chip")
        self.chip.add_css_class("suggested-action")
        self.chip.connect("clicked", lambda *_: self._chip_clicked())
        outer.append(self.chip)

        self.entry = Gtk.Entry(xalign=0.5, has_frame=False, input_purpose=Gtk.InputPurpose.PHONE,
                               placeholder_text="Enter number")
        self.entry.add_css_class("keypad-display")
        self.entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "edit-paste-symbolic")
        self.entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Paste number")
        self.entry.connect("icon-press", lambda *_: self._paste_into_keypad())
        self.entry.connect("activate", lambda *_: self._keypad_call(False))
        self.entry.connect("changed", lambda *_: self._keypad_changed())
        lp = Gtk.GestureLongPress()
        lp.connect("pressed", lambda *_: self.entry.get_text() and self.copy(self._keypad_address() or self.entry.get_text()))
        self.entry.add_controller(lp)
        outer.append(self.entry)
        self.match = Gtk.Label(css_classes=["dim-label"], ellipsize=3)
        outer.append(self.match)

        grid = Gtk.Grid(column_spacing=18, row_spacing=10, halign=Gtk.Align.CENTER, margin_top=6)
        for i, (digit, letters) in enumerate(KEYS):
            b = Gtk.Button()
            vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            vb.append(Gtk.Label(label=digit, css_classes=["digit"]))
            vb.append(Gtk.Label(label=letters or " ", css_classes=["letters"]))
            b.set_child(vb)
            b.add_css_class("key")
            b.connect("clicked", lambda _b, d=digit: self._press(d))
            if digit == "0":
                g = Gtk.GestureLongPress()
                g.connect("pressed", lambda *_: self._press("+", replace_last="0"))
                b.add_controller(g)
            grid.attach(b, i % 3, i // 3, 1, 1)
        outer.append(grid)

        row = Gtk.CenterBox(margin_top=10)
        row.set_start_widget(icon_button("camera-video-symbolic", "Video call", lambda: self._keypad_call(True),
                                         "round", "flat"))
        call = icon_button("call-start-symbolic", "Call", lambda: self._keypad_call(False), "call-btn")
        row.set_center_widget(call)
        back = icon_button("edit-clear-symbolic", "Delete (hold to clear)", self._backspace, "round", "flat")
        g = Gtk.GestureLongPress()
        g.connect("pressed", lambda *_: self.entry.set_text(""))
        back.add_controller(g)
        row.set_end_widget(back)
        outer.append(row)
        return outer

    def _press(self, d, replace_last=None):
        t = self.entry.get_text()
        if replace_last and t.endswith(replace_last):
            t = t[:-1]
        self.entry.set_text(t + d)
        self.entry.set_position(-1)
        for c in self.calls:
            if c["state"] == "active" and self.dtmf_open:
                self.rpc("dtmf", call_id=c["id"], digits=d)

    def _backspace(self):
        t = self.entry.get_text()
        digits = numbers.digits_only(t)
        if not t:
            return
        # remove the last typed character, then re-format
        raw = t[:-1] if not digits or not t[-1].isdigit() else None
        if raw is None:
            raw = t[:t.rfind(digits[-1])]
        self.entry.set_text(raw)

    def _keypad_changed(self):
        t = self.entry.get_text()
        if getattr(self, "_formatting", False):
            return
        if t and not numbers.is_uri(t) and not t.startswith("loop:"):
            f = numbers.format_as_you_type(t, self.region)
            if f != t:
                self._formatting = True
                self.entry.set_text(f)
                self.entry.set_position(-1)
                self._formatting = False
        addr = self._keypad_address()
        who = self.rpc("lookup", address=addr) if addr else None
        self.match.set_label(who["name"] if who else "")

    def _keypad_address(self):
        t = self.entry.get_text().strip()
        if t.startswith("loop:"):
            return t
        return numbers.normalize_address(t, self.region)

    def _keypad_call(self, video):
        t = self.entry.get_text().strip()
        if not t:  # empty keypad + call = redial the last number, like most phones
            h = self.rpc("history", limit=1) or []
            if h:
                self.entry.set_text(pretty(h[0]["remote"], self.region))
            return
        addr = self._keypad_address()
        if not addr:
            self.toast("That doesn't look like a phone number")
            return
        self.dial(addr, video)
        self.entry.set_text("")

    def _paste_into_keypad(self):
        self._paste_into(self.entry)

    def _on_active(self, *_):
        if not self.is_active() or not self.settings.get("clipboard_detect"):
            return
        # opt-in clipboard detection, only while the phone window is focused

        def got(clip, res):
            try:
                text = clip.read_text_finish(res) or ""
            except GLib.Error:
                text = ""
            n = numbers.first_number(text, self.region) if len(text) < 4000 else None
            self._chip_number = n
            self.chip.set_visible(bool(n))
            if n:
                self.chip.set_label(f"Call {pretty(n, self.region)}")
        self.get_clipboard().read_text_async(None, got)

    def _chip_clicked(self):
        n = getattr(self, "_chip_number", None)
        self.chip.set_visible(False)
        if n:
            self.dial(n)

    # ============================================================ calls
    def refresh_calls(self):
        st = self.rpc("state")
        if st is None:
            return
        self.calls = st["calls"]
        self.speaker = st.get("speaker", False)
        live = [c for c in self.calls if c["state"] != "incoming"]
        ringing = [c for c in self.calls if c["state"] == "incoming"]
        self.banner.set_revealed(bool(live))
        if live:
            self.banner.set_title(f"{live[0]['name']} · {self._status(live[0])}")
        top = self.nav.get_visible_page()
        tag = top.get_tag() if top else ""
        if ringing:
            self.show_incoming(ringing[0])
        elif tag == "incoming":
            self.nav.pop_to_tag("main")
        first, self._first_refresh = getattr(self, "_first_refresh", True), False
        if live and not ringing:
            if tag in ("incall", "incoming", "main") and (tag != "main" or first or self._just_dialed()):
                self.show_call_page()
            elif tag == "incall":
                self._render_call()
        elif not live and self.nav.find_page("incall"):
            self.nav.pop_to_tag("main")
            self._stop_timer()

    def _just_dialed(self):
        return any(c["state"] in ("dialing", "ringing") or time.time() - (c.get("answered") or 0) < 2
                   for c in self.calls if c["state"] != "incoming")

    def _status(self, c):
        s = c["state"]
        if s == "active":
            return duration(time.time() - (c.get("answered") or time.time()))
        return {"dialing": "Calling…", "ringing": "Ringing…", "held": "On hold",
                "remote_held": "They put you on hold", "incoming": "Incoming"}.get(s, s)

    # ------------------------------------------------------------ incoming
    def show_incoming(self, call):
        page = self.nav.find_page("incoming")
        if page and getattr(page, "call_id", None) == call["id"]:
            return
        if page:
            self.nav.pop_to_tag("main")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=48, margin_bottom=32,
                      margin_start=24, margin_end=24)
        box.append(Adw.Avatar(size=120, text=call["name"], show_initials=True, halign=Gtk.Align.CENTER))
        name = Gtk.Label(label=call["name"], wrap=True, justify=Gtk.Justification.CENTER, css_classes=["caller"])
        box.append(name)
        known = call.get("contact_id") is not None
        sub = call["display"] if call["display"] != call["name"] else ""
        if not known and call["remote"]:
            sub = (sub + " · " if sub else "") + "Not in contacts"
        box.append(Gtk.Label(label=sub or " ", css_classes=["call-status"]))
        kind = "Incoming video call" if call["video"] else "Incoming call"
        others = [c for c in self.calls if c["id"] != call["id"] and c["state"] != "incoming"]
        if others:
            kind += " · your current call will be held"
        box.append(Gtk.Label(label=kind, css_classes=["dim-label"]))
        reason = (call.get("screening") or {}).get("reason")
        if reason or call.get("silent"):
            lbl = Gtk.Label(label=("Silenced · " if call.get("silent") else "") + (reason or ""), halign=Gtk.Align.CENTER,
                            css_classes=["screen-reason"])
            box.append(lbl)
        box.append(Gtk.Box(vexpand=True))

        def labelled(widget, text):
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            v.append(widget)
            v.append(Gtk.Label(label=text, css_classes=["ctl-label"]))
            return v

        minor = Gtk.Box(spacing=24, halign=Gtk.Align.CENTER)
        minor.append(labelled(icon_button("mail-send-symbolic", "Send to voicemail",
                                          lambda: self.rpc("decline", call_id=call["id"], voicemail=True), "round"),
                              "Voicemail"))
        minor.append(labelled(icon_button("camera-video-symbolic", "Answer with video",
                                          lambda: self.rpc("answer", call_id=call["id"], video=True), "round"),
                              "Video"))
        minor.append(labelled(icon_button("action-unavailable-symbolic", "Block this number",
                                          lambda: (self._list_add("block", call["remote"]),
                                                   self.rpc("decline", call_id=call["id"])), "round"), "Block"))
        box.append(minor)
        major = Gtk.Box(spacing=96, halign=Gtk.Align.CENTER, margin_top=24)
        major.append(labelled(icon_button("call-stop-symbolic", "Decline",
                                          lambda: self.rpc("decline", call_id=call["id"]), "end-btn"), "Decline"))
        major.append(labelled(icon_button("call-start-symbolic", "Answer",
                                          lambda: self.rpc("answer", call_id=call["id"]), "call-btn"), "Answer"))
        box.append(major)
        page = Adw.NavigationPage(title="Incoming call", tag="incoming", child=box, can_pop=False)
        page.call_id = call["id"]
        self.nav.push(page)
        self.present()

    # ------------------------------------------------------------ in call
    def show_call_page(self):
        if not self.nav.find_page("incall"):
            self.nav.pop_to_tag("main")
            self.call_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16,
                                    margin_bottom=24, margin_start=20, margin_end=20)
            tv = Adw.ToolbarView()
            hb = Adw.HeaderBar(show_title=False)
            tv.add_top_bar(hb)
            tv.set_content(Gtk.ScrolledWindow(child=self.call_box, vexpand=True,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER))
            self.nav.push(Adw.NavigationPage(title="Call", tag="incall", child=tv))
        self._render_call()
        if not self.timer:
            self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _tick(self):
        if not self.nav.find_page("incall"):
            self.timer = 0
            return False
        if hasattr(self, "status_lbl") and self.calls:
            cur = self._current()
            if cur:
                self.status_lbl.set_label(self._status(cur))
        return True

    def _stop_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def _current(self):
        live = [c for c in self.calls if c["state"] not in ("incoming",)]
        active = [c for c in live if c["state"] in ("active", "dialing", "ringing", "remote_held")]
        return (active or live or [None])[0]

    def _render_call(self):
        box = self.call_box
        clear(box)
        cur = self._current()
        if cur is None:
            return
        live = [c for c in self.calls if c["state"] != "incoming"]
        conf = cur.get("conference")
        members = [c for c in live if conf and c.get("conference") == conf]

        if len(live) > 1:  # call switcher
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lb.add_css_class("boxed-list")
            for c in live:
                r = Adw.ActionRow(title=GLib.markup_escape_text(c["name"]),
                                  subtitle=("Group call · " if c.get("conference") else "") + self._status(c))
                if c["id"] != cur["id"] and c["state"] == "held" and not (conf and c.get("conference") == conf):
                    r.add_suffix(icon_button("media-playback-start-symbolic", "Swap to this call",
                                             lambda cid=c["id"]: self.rpc("hold", call_id=cid, on=False)))
                if c.get("conference"):
                    r.add_suffix(icon_button("list-remove-symbolic", "Talk privately",
                                             lambda cid=c["id"]: self.rpc("split", call_id=cid)))
                r.add_suffix(icon_button("call-stop-symbolic", "Hang up this call",
                                         lambda cid=c["id"]: self._hangup_one(cid)))
                lb.append(r)
            box.append(lb)

        title = "Group call" if members else cur["name"]
        if not members:
            box.append(Adw.Avatar(size=96 if len(live) == 1 else 56, text=cur["name"], show_initials=True, halign=Gtk.Align.CENTER,
                                  margin_top=8))
        name = Gtk.Label(label=title, wrap=True, justify=Gtk.Justification.CENTER, css_classes=["caller"])
        box.append(name)
        if members:
            box.append(Gtk.Label(label=", ".join(m["name"] for m in members), wrap=True, css_classes=["dim-label"],
                                 justify=Gtk.Justification.CENTER))
        elif cur["display"] != cur["name"]:
            box.append(Gtk.Label(label=cur["display"], css_classes=["dim-label"]))
        self.status_lbl = Gtk.Label(label=self._status(cur), css_classes=["call-status"])
        box.append(self.status_lbl)

        if cur["video"]:
            va = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.FILL, vexpand=False)
            va.add_css_class("video-area")
            va.append(Gtk.Image(icon_name="camera-video-symbolic", pixel_size=32, margin_top=40))
            va.append(Gtk.Label(label="Video on", margin_top=6))
            va.append(Gtk.Label(label="(the loopback backend carries no media)", css_classes=["caption"],
                                margin_bottom=30))
            box.append(va)
        else:
            box.append(Gtk.Box(vexpand=True, height_request=12))

        if self.dtmf_open:
            kp = Gtk.Grid(column_spacing=12, row_spacing=6, halign=Gtk.Align.CENTER)
            for i, (d, _) in enumerate(KEYS):
                b = Gtk.Button(label=d)
                b.add_css_class("round")
                b.connect("clicked", lambda _b, d=d: self.rpc("dtmf", call_id=cur["id"], digits=d))
                kp.attach(b, i % 3, i // 3, 1, 1)
            box.append(kp)

        grid = Gtk.Grid(column_spacing=22, row_spacing=12, halign=Gtk.Align.CENTER, margin_top=8,
                        column_homogeneous=True)

        def toggle(icon, label, active, cb, sensitive=True):
            t = Gtk.ToggleButton(icon_name=icon, active=active, tooltip_text=label, sensitive=sensitive,
                                 halign=Gtk.Align.CENTER)
            t.add_css_class("round")
            t.connect("toggled", lambda b: cb(b.get_active()))
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            v.append(t)
            v.append(Gtk.Label(label=label, css_classes=["ctl-label"]))
            return v

        connected = cur["state"] in ("active", "held", "remote_held")
        held = cur["held"] or cur["state"] == "held"
        controls = [
            toggle("microphone-sensitivity-muted-symbolic", "Mute", cur["muted"],
                   lambda on: self.rpc("mute", on=on)),
            toggle("input-dialpad-symbolic", "Keypad", self.dtmf_open, self._toggle_dtmf),
            self._route_button(),
            toggle("camera-video-symbolic", "Video", cur["video"],
                   lambda on: self.rpc("video", call_id=cur["id"], on=on), connected),
            toggle("media-playback-pause-symbolic", "Hold", held,
                   lambda on: self.rpc("hold", call_id=cur["id"], on=on), connected),
        ]
        if len(live) > 1 and len(members) < len(live):
            merge = toggle("call-start-symbolic", "Merge", False, lambda _on: self.rpc("merge"), connected)
            controls.append(merge)
        else:
            controls.append(toggle("list-add-symbolic", "Add call", False, lambda _on: self._add_call(), connected))
        for i, w in enumerate(controls):
            grid.attach(w, i % 3, i // 3, 1, 1)
        box.append(grid)

        end = icon_button("call-stop-symbolic", "End call", lambda: self._hangup_one(cur["id"]), "end-btn")
        end.set_halign(Gtk.Align.CENTER)
        end.set_margin_top(18)
        box.append(end)

    def _hangup_one(self, cid):
        self.rpc("hangup", call_id=cid)

    def _toggle_dtmf(self, on):
        self.dtmf_open = on
        self._render_call()

    def _add_call(self):
        self.select_tab("keypad")
        self.toast("Dial the next person. Your current call will be held; tap Merge to make it a group call.")

    def _route_button(self):
        """Speaker / earpiece / Bluetooth: a menu of PipeWire sinks."""
        pop = Gtk.Popover()
        vb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        pop.set_child(vb)
        icons = {"bluetooth": "bluetooth-active-symbolic", "speaker": "audio-speakers-symbolic",
                 "headset": "audio-headphones-symbolic", "earpiece": "phone-symbolic"}

        def fill(*_):
            clear(vb)
            routes = self.rpc("routes") or []
            if not routes:
                vb.append(Gtk.Label(label="No audio outputs found", margin_top=6, margin_bottom=6))
            for r in routes:
                b = Gtk.Button()
                hb = Gtk.Box(spacing=8)
                hb.append(Gtk.Image(icon_name=icons.get(r["kind"], "audio-speakers-symbolic")))
                hb.append(Gtk.Label(label=r["label"], ellipsize=3, max_width_chars=26, xalign=0, hexpand=True))
                if r.get("default"):
                    hb.append(Gtk.Image(icon_name="object-select-symbolic"))
                b.set_child(hb)
                b.add_css_class("flat")
                b.connect("clicked", lambda _b, rid=r["id"]: (pop.popdown(), self.rpc("route", id=rid)))
                vb.append(b)
            sp = Gtk.Button(label="Speaker off" if self.speaker else "Speaker on")
            sp.add_css_class("flat")
            sp.connect("clicked", lambda *_: (pop.popdown(), self.rpc("speaker", on=not self.speaker)))
            vb.append(sp)
        pop.connect("show", fill)
        mb = Gtk.MenuButton(icon_name="audio-speakers-symbolic", popover=pop, tooltip_text="Audio output",
                            halign=Gtk.Align.CENTER)
        mb.add_css_class("round")
        if self.speaker:
            mb.add_css_class("suggested-action")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        v.append(mb)
        v.append(Gtk.Label(label="Audio", css_classes=["ctl-label"]))
        return v

    # ============================================================ settings
    def open_settings(self):
        s = self.rpc("settings") or {}
        page = Adw.PreferencesPage()

        def combo(title, key, subtitle=""):
            model = Gtk.StringList.new([lbl for _, lbl in ACTION_LABELS])
            row = Adw.ComboRow(title=title, subtitle=subtitle, model=model)
            keys = [k for k, _ in ACTION_LABELS]
            row.set_selected(keys.index(s.get(key, "ring")) if s.get(key) in keys else 0)
            row.connect("notify::selected", lambda r, _p: self.rpc("set", key=key, value=keys[r.get_selected()]))
            return row

        def switch(title, key, subtitle=""):
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=bool(s.get(key)))
            row.connect("notify::active", lambda r, _p: self.rpc("set", key=key, value=r.get_active()))
            return row

        dnd = Adw.PreferencesGroup(title="Do not disturb")
        dnd.add(switch("Do not disturb", "dnd", "Favorites and allowed numbers still ring"))
        dnd.add(combo("Other callers", "dnd_action"))
        dnd.add(switch("Repeated calls break through", "dnd_repeat_callers", "Second call within 3 minutes rings"))
        groups = Adw.EntryRow(title="Groups allowed during DND", text=", ".join(s.get("dnd_allowed_groups", [])),
                              show_apply_button=True)
        groups.connect("apply", lambda r: self.rpc("set", key="dnd_allowed_groups",
                                                   value=[g.strip() for g in r.get_text().split(",") if g.strip()]))
        dnd.add(groups)
        page.add(dnd)

        scr = Adw.PreferencesGroup(title="Call screening")
        scr.add(combo("Unknown callers", "unknown_action", "Numbers not in your contacts"))
        scr.add(combo("Withheld numbers", "withheld_action"))
        scr.add(combo("Likely spam", "spam_action", "Premium-rate, reported or spoofed numbers"))
        scr.add(switch("Detect neighbour spoofing", "neighbor_spoof_filter",
                       "Unknown numbers that mimic your own prefix"))
        page.add(scr)

        for kind, title in (("block", "Blocked"), ("allow", "Always allowed"), ("spam", "Reported spam")):
            grp = Adw.PreferencesGroup(title=title, description="Exact numbers, or patterns like +1900* or sip:*@spam.example"
                                       if kind == "block" else "")
            for e in self.rpc("lists", kind=kind) or []:
                row = Adw.ActionRow(title=GLib.markup_escape_text(pretty(e["pattern"], self.region)),
                                    subtitle=e["action"] or "")
                row.add_suffix(icon_button("user-trash-symbolic", "Remove",
                                           lambda k=kind, p=e["pattern"]: (self.rpc("list_remove", kind=k, pattern=p),
                                                                           self.nav.pop(), self.open_settings())))
                grp.add(row)
            add = Adw.EntryRow(title=f"Add to {title.lower()}", show_apply_button=True)
            add.connect("apply", lambda r, k=kind: (self._list_add(k, r.get_text().strip()), self.nav.pop(),
                                                    self.open_settings()) if r.get_text().strip() else None)
            grp.add(add)
            page.add(grp)

        priv = Adw.PreferencesGroup(title="Privacy")
        priv.add(switch("Offer to call copied numbers", "clipboard_detect",
                        "Reads the clipboard only while Phone is focused"))
        page.add(priv)

        acct = Adw.PreferencesGroup(title="Account")
        st = self.rpc("state") or {}
        for b in st.get("backends", []):
            reg = (st.get("registration") or {}).get(b["id"], {})
            acct.add(Adw.ActionRow(title=b["name"], subtitle=GLib.markup_escape_text(
                ("Connected · " if reg.get("ok") else "Offline · ") + (reg.get("detail") or ""))))
        own = Adw.EntryRow(title="My number", text=s.get("own_number", ""), show_apply_button=True)
        own.connect("apply", lambda r: self.rpc("set", key="own_number",
                                                value=numbers.normalize(r.get_text(), self.region) or r.get_text()))
        acct.add(own)
        region = Adw.EntryRow(title="Region (for local numbers)", text=s.get("region", "US"), show_apply_button=True)
        region.connect("apply", lambda r: self.rpc("set", key="region", value=r.get_text().strip().upper()[:2]))
        acct.add(region)
        page.add(acct)

        peers = [p for p in (self.rpc("directory") or []) if p.get("profile") != st.get("profile")]
        if peers or "loopback" in [b["id"] for b in st.get("backends", [])]:
            lg = Adw.PreferencesGroup(title="Loopback test peers",
                                      description="Local phoned instances; 'loop:echo' answers automatically")
            for p in [{"profile": "echo", "name": "Echo test", "number": ""}] + peers:
                addr = p.get("number") or f"loop:{p['profile']}"
                row = Adw.ActionRow(title=GLib.markup_escape_text(p.get("name") or p["profile"]),
                                    subtitle=GLib.markup_escape_text(pretty(addr, self.region)), activatable=True)
                row.connect("activated", lambda *_a, a=f"loop:{p['profile']}": self.dial(a))
                row.add_suffix(Gtk.Image(icon_name="call-start-symbolic"))
                lg.add(row)
            page.add(lg)

        hist = Adw.PreferencesGroup()
        clr = Adw.ButtonRow(title="Clear call history")
        clr.add_css_class("destructive-action")
        clr.connect("activated", lambda *_: self.rpc("clear_history"))
        hist.add(clr)
        page.add(hist)
        self._push("Settings", "settings", page)

    # ============================================================ vCard files
    def import_vcard(self):
        f = Gtk.FileFilter(name="vCard")
        f.add_suffix("vcf")
        f.add_suffix("vcard")
        f.add_mime_type("text/vcard")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg = Gtk.FileDialog(title="Import contacts", filters=store)

        def done(d, res):
            try:
                file = d.open_finish(res)
            except GLib.Error:
                return
            r = self.rpc("import_vcard", path=file.get_path())
            if r:
                self.toast(f"Imported {r['added']} new, updated {r['updated']}")
        dlg.open(self, None, done)

    def export_vcard(self, ids=None):
        dlg = Gtk.FileDialog(title="Export contacts", initial_name="contacts.vcf")

        def done(d, res):
            try:
                file = d.save_finish(res)
            except GLib.Error:
                return
            r = self.rpc("export_vcard", path=file.get_path(), ids=ids)
            if r:
                self.toast(f"Exported {r['count']} contacts")
        dlg.save(self, None, done)

    # ============================================================ refresh
    def refresh_settings(self):
        self.settings = self.rpc("settings") or {}
        self.region = self.settings.get("region", "US")
        self.dnd_btn.handler_block(self.dnd_handler)
        self.dnd_btn.set_active(bool(self.settings.get("dnd")))
        self.dnd_btn.handler_unblock(self.dnd_handler)
        self.dnd_btn.set_tooltip_text("Do not disturb: " + ("on" if self.settings.get("dnd") else "off"))

    def refresh_all(self):
        self.refresh_settings()
        self.refresh_groups()
        self.refresh_favorites()
        self.refresh_contacts()
        self.refresh_recents()
        self.refresh_calls()

    def on_event(self, ev):
        t = ev.get("type")
        if t in ("call", "incoming", "ended", "conference", "audio"):
            self.refresh_calls()
        if t == "ended":
            st = ev["call"].get("status")
            if st in ("busy", "failed", "rejected", "voicemail", "no_answer") and ev["call"]["direction"] == "out":
                self.toast(f"{ev['call']['name']}: {STATUS_TEXT.get(st, st)}")
        if t in ("history", "ended"):
            self.refresh_recents()
        if t == "contacts":
            self.refresh_groups()
            self.refresh_contacts()
            self.refresh_favorites()
        if t in ("settings", "dnd"):
            self.refresh_settings()
        if t == "show":
            if ev.get("page") in ("favorites", "recents", "contacts", "keypad"):
                self.select_tab(ev["page"])
            elif ev.get("page") == "incall":
                self.show_call_page()
            elif ev.get("page") == "incoming":
                self.refresh_calls()
            if ev.get("number"):
                self.entry.set_text(ev["number"])
            self.present()
        if t == "error":
            self.toast(ev.get("detail", "error"))


class PhoneApp(Adw.Application):
    def __init__(self, profile="default"):
        app_id = APP_ID if profile in ("", "default") else f"{APP_ID}.{''.join(ch for ch in profile if ch.isalnum())}"
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.profile = profile
        self.win: PhoneWindow | None = None
        self.add_main_option("profile", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Instance", "NAME")
        self.add_main_option("incoming", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Show incoming call", "ID")
        self.add_main_option("page", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Open a tab", "NAME")
        self.add_main_option("screenshot", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Render the window to a PNG and exit (for docs/tests)", "PATH")

    def do_startup(self):
        Adw.Application.do_startup(self)
        prov = Gtk.CssProvider()
        prov.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.hold()  # stay resident so incoming calls appear instantly
        GLib.timeout_add_seconds(1, lambda: self.release() or False)

    def _ensure_window(self):
        if self.win:
            return self.win
        client = Client(self.profile)
        for _ in range(10):  # phoned may still be starting
            if client.available():
                break
            time.sleep(0.1)
        if not client.available():
            # development convenience: start phoned from the source tree
            subprocess.Popen([sys.executable, "-W", "ignore", "-m", "omarchy_phone.daemon", "--profile", self.profile,
                              "--ui-cmd", f"{sys.executable} -W ignore -m omarchy_phone.ui"],
                             cwd=os.path.dirname(HERE), start_new_session=True)
            for _ in range(50):
                if client.available():
                    break
                time.sleep(0.1)
        self.win = PhoneWindow(self, client)
        client.subscribe(lambda ev: GLib.idle_add(lambda: self.win.on_event(ev) and False))
        return self.win

    def do_command_line(self, cmdline):
        opts = cmdline.get_options_dict().end().unpack()
        args = cmdline.get_arguments()[1:]
        win = self._ensure_window()
        if opts.get("page"):
            win.select_tab(opts["page"])
        for a in args:
            if a.startswith("tel:") or numbers.first_number(a, win.region):
                n = numbers.first_number(a[4:] if a.startswith("tel:") else a, win.region)
                win.select_tab("keypad")
                win.entry.set_text(pretty(n, win.region) if n else a)
        if opts.get("incoming"):
            win.refresh_calls()
        win.present()
        if opts.get("screenshot"):
            GLib.timeout_add(900, self._screenshot, opts["screenshot"])
        return 0

    def _screenshot(self, path):
        w = self.win
        content = w.get_content()
        if os.environ.get("OMARCHY_PHONE_DEBUG"):
            print("screenshot:", w.get_mapped(), content.get_mapped(), content.get_width(), file=sys.stderr)
        width, height = content.get_width(), content.get_height()
        snap = Gtk.Snapshot()
        # paint the window background first: the content itself is transparent
        rgba = Gdk.RGBA()
        rgba.parse("#fafafb" if not Adw.StyleManager.get_default().get_dark() else "#222226")
        rect = Graphene.Rect().init(0, 0, width, height)
        snap.append_color(rgba, rect)
        content.get_parent().snapshot_child(content, snap)
        node = snap.to_node()
        if node is not None:
            tex = w.get_native().get_renderer().render_texture(node, rect)
            tex.save_to_png(path)
        else:
            print("screenshot: nothing rendered", file=sys.stderr)
        self.quit()
        return False


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    profile = os.environ.get("OMARCHY_PHONE_PROFILE", "default")
    for i, a in enumerate(argv):
        if a == "--profile" and i + 1 < len(argv):
            profile = argv[i + 1]
        elif a.startswith("--profile="):
            profile = a.split("=", 1)[1]
    return PhoneApp(profile).run(argv)


if __name__ == "__main__":
    sys.exit(main())
