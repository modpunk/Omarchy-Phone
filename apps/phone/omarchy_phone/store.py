"""SQLite storage: contacts, groups, favorites, call log, screening lists and settings."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

from . import numbers, vcard
from .vcard import Contact

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY, uid TEXT UNIQUE NOT NULL, name TEXT, given TEXT, family TEXT,
  org TEXT, note TEXT, emails TEXT DEFAULT '[]', favorite INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS numbers (
  contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE, pos INTEGER,
  label TEXT, value TEXT, tail TEXT
);
CREATE INDEX IF NOT EXISTS numbers_value ON numbers(value);
CREATE INDEX IF NOT EXISTS numbers_tail ON numbers(tail);
CREATE TABLE IF NOT EXISTS groups (
  contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE, name TEXT,
  UNIQUE(contact_id, name)
);
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, call_id TEXT, remote TEXT, name TEXT, direction TEXT,
  started REAL, answered REAL, ended REAL, status TEXT, reason TEXT, video INTEGER DEFAULT 0,
  backend TEXT, conference TEXT
);
CREATE INDEX IF NOT EXISTS calls_remote ON calls(remote, started);
CREATE TABLE IF NOT EXISTS lists (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, pattern TEXT NOT NULL, action TEXT, note TEXT,
  created REAL, UNIQUE(kind, pattern)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {
    "region": "US",
    "own_number": "",
    "dnd": False,
    "dnd_action": "silent",          # silent | voicemail | reject
    "dnd_repeat_callers": True,
    "dnd_allowed_groups": [],
    "unknown_action": "ring",        # ring | silent | voicemail | reject
    "withheld_action": "voicemail",
    "spam_action": "voicemail",
    "neighbor_spoof_filter": True,
    "clipboard_detect": False,
    "backend": "loopback",
}


def _tail(value: str) -> str:
    d = numbers.digits_only(value)
    return d[-9:] if len(d) >= 7 else ""


def default_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "omarchy-phone", "phone.db")


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ------------------------------------------------------------ settings
    def settings(self) -> dict:
        s = dict(DEFAULT_SETTINGS)
        for row in self.db.execute("SELECT key, value FROM settings"):
            s[row["key"]] = json.loads(row["value"])
        return s

    def get(self, key: str):
        return self.settings().get(key)

    def set(self, key: str, value):
        if key not in DEFAULT_SETTINGS:
            raise KeyError(key)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    # ------------------------------------------------------------ contacts
    def _load(self, row) -> Contact:
        cid = row["id"]
        nums = [(r["label"], r["value"]) for r in
                self.db.execute("SELECT label, value FROM numbers WHERE contact_id=? ORDER BY pos", (cid,))]
        groups = [r["name"] for r in
                  self.db.execute("SELECT name FROM groups WHERE contact_id=? ORDER BY rowid", (cid,))]
        return Contact(name=row["name"] or "", given=row["given"] or "", family=row["family"] or "",
                       org=row["org"] or "", note=row["note"] or "", numbers=nums,
                       emails=json.loads(row["emails"] or "[]"), groups=groups,
                       favorite=bool(row["favorite"]), uid=row["uid"], id=cid)

    def contact(self, cid: int) -> Contact | None:
        row = self.db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
        return self._load(row) if row else None

    def contacts(self, query: str = "", group: str | None = None) -> list[Contact]:
        sql, args = "SELECT DISTINCT c.* FROM contacts c LEFT JOIN numbers n ON n.contact_id=c.id", []
        where = []
        if group:
            sql += " JOIN groups g ON g.contact_id=c.id"
            where.append("g.name=?")
            args.append(group)
        if query:
            q = f"%{query.lower()}%"
            cond = "(lower(c.name) LIKE ? OR lower(c.given||' '||c.family) LIKE ? OR lower(c.org) LIKE ?"
            args += [q, q, q]
            d = numbers.digits_only(query)
            if len(d) >= 3:
                cond += " OR n.value LIKE ?"
                args.append(f"%{d}%")
            where.append(cond + ")")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY lower(coalesce(nullif(c.name,''), c.given||' '||c.family, c.org))"
        return [self._load(r) for r in self.db.execute(sql, args)]

    def favorites(self) -> list[Contact]:
        return [c for c in self.contacts() if c.favorite]

    def groups(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT name FROM groups ORDER BY lower(name)")]

    def save_contact(self, c: Contact) -> int:
        c.uid = c.uid or str(uuid.uuid4())
        with self.db:
            if c.id is None:
                cur = self.db.execute(
                    "INSERT INTO contacts (uid, name, given, family, org, note, emails, favorite)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (c.uid, c.name, c.given, c.family, c.org, c.note, json.dumps(c.emails), int(c.favorite)))
                c.id = cur.lastrowid
            else:
                self.db.execute(
                    "UPDATE contacts SET uid=?, name=?, given=?, family=?, org=?, note=?, emails=?, favorite=?"
                    " WHERE id=?",
                    (c.uid, c.name, c.given, c.family, c.org, c.note, json.dumps(c.emails), int(c.favorite), c.id))
                self.db.execute("DELETE FROM numbers WHERE contact_id=?", (c.id,))
                self.db.execute("DELETE FROM groups WHERE contact_id=?", (c.id,))
            for pos, (label, value) in enumerate(c.numbers):
                self.db.execute("INSERT INTO numbers VALUES (?,?,?,?,?)", (c.id, pos, label, value, _tail(value)))
            for g in c.groups:
                self.db.execute("INSERT OR IGNORE INTO groups VALUES (?,?)", (c.id, g))
        return c.id

    def delete_contact(self, cid: int):
        with self.db:
            self.db.execute("DELETE FROM contacts WHERE id=?", (cid,))

    def set_favorite(self, cid: int, on: bool):
        with self.db:
            self.db.execute("UPDATE contacts SET favorite=? WHERE id=?", (int(on), cid))

    def set_groups(self, cid: int, groups: list[str]):
        with self.db:
            self.db.execute("DELETE FROM groups WHERE contact_id=?", (cid,))
            for g in groups:
                self.db.execute("INSERT OR IGNORE INTO groups VALUES (?,?)", (cid, g))

    def contact_for_number(self, address: str) -> Contact | None:
        if not address:
            return None
        row = self.db.execute("SELECT contact_id FROM numbers WHERE value=? LIMIT 1", (address,)).fetchone()
        if row is None and _tail(address):
            for r in self.db.execute("SELECT contact_id, value FROM numbers WHERE tail=?", (_tail(address),)):
                if numbers.same_number(r["value"], address):
                    row = r
                    break
        return self.contact(row["contact_id"]) if row else None

    def import_vcard(self, text: str, region: str | None = None) -> tuple[int, int]:
        """Import cards, merging by UID or by (name + a shared number). Returns (added, updated)."""
        region = region or self.get("region")
        added = updated = 0
        for c in vcard.parse(text, region):
            existing = None
            row = self.db.execute("SELECT id FROM contacts WHERE uid=?", (c.uid,)).fetchone()
            if row:
                existing = self.contact(row["id"])
            else:
                for _, n in c.numbers:
                    m = self.contact_for_number(n)
                    if m and m.display_name() == c.display_name():
                        existing = m
                        break
            if existing:
                c.id, c.uid = existing.id, existing.uid
                c.favorite = c.favorite or existing.favorite
                c.groups = existing.groups + [g for g in c.groups if g not in existing.groups]
                c.numbers = existing.numbers + [n for n in c.numbers if n[1] not in {v for _, v in existing.numbers}]
                updated += 1
            else:
                added += 1
            self.save_contact(c)
        return added, updated

    def export_vcard(self, ids: list[int] | None = None, version: str = "3.0") -> str:
        cs = self.contacts() if ids is None else [c for c in (self.contact(i) for i in ids) if c]
        return vcard.export(cs, version)

    # ------------------------------------------------------------ call log
    def log_call(self, **kw) -> int:
        cols = ("call_id", "remote", "name", "direction", "started", "answered", "ended", "status",
                "reason", "video", "backend", "conference")
        vals = [kw.get(k) for k in cols]
        with self.db:
            cur = self.db.execute(f"INSERT INTO calls ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        return cur.lastrowid

    def update_call(self, call_id: str, **kw):
        if not kw:
            return
        sets = ", ".join(f"{k}=?" for k in kw)
        with self.db:
            self.db.execute(f"UPDATE calls SET {sets} WHERE call_id=?", (*kw.values(), call_id))

    def history(self, limit: int = 200, missed_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM calls"
        if missed_only:
            sql += " WHERE status IN ('missed','voicemail','rejected','blocked')"
        rows = self.db.execute(sql + " ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["duration"] = int((r["ended"] or 0) - r["answered"]) if r["answered"] and r["ended"] else 0
            out.append(d)
        return out

    def recent_calls_from(self, remote: str, since: float) -> int:
        return self.db.execute("SELECT count(*) FROM calls WHERE remote=? AND direction='in' AND started>=?",
                               (remote, since)).fetchone()[0]

    def clear_history(self):
        with self.db:
            self.db.execute("DELETE FROM calls")

    # ------------------------------------------------------------ screening lists
    def list_entries(self, kind: str | None = None) -> list[dict]:
        if kind:
            rows = self.db.execute("SELECT * FROM lists WHERE kind=? ORDER BY created", (kind,))
        else:
            rows = self.db.execute("SELECT * FROM lists ORDER BY kind, created")
        return [dict(r) for r in rows]

    def add_list_entry(self, kind: str, pattern: str, action: str | None = None, note: str = ""):
        if kind not in ("allow", "block", "spam"):
            raise ValueError(kind)
        with self.db:
            # a number is either allowed or blocked, never both
            other = {"allow": ("block", "spam"), "block": ("allow",), "spam": ("allow",)}[kind]
            self.db.execute(f"DELETE FROM lists WHERE pattern=? AND kind IN ({','.join('?' * len(other))})",
                            (pattern, *other))
            self.db.execute("INSERT OR REPLACE INTO lists (kind, pattern, action, note, created) VALUES (?,?,?,?,?)",
                            (kind, pattern, action, note, time.time()))

    def remove_list_entry(self, kind: str, pattern: str):
        with self.db:
            self.db.execute("DELETE FROM lists WHERE kind=? AND pattern=?", (kind, pattern))
