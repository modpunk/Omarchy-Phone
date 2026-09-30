"""vCard 2.1 / 3.0 / 4.0 import and 3.0 / 4.0 export (RFC 2426, RFC 6350).

Only the properties the phone app uses are interpreted (FN, N, TEL, EMAIL, ORG, NOTE,
CATEGORIES, UID, X-OMARCHY-FAVORITE); everything else is ignored on import. PHOTO data
is skipped so a large address book stays cheap to import on a 2-core device.
"""
from __future__ import annotations

import quopri
import re
import uuid
from dataclasses import dataclass, field

from . import numbers

FAVORITE_PROP = "X-OMARCHY-FAVORITE"
_TEL_TYPES = ("cell", "mobile", "home", "work", "main", "fax", "pager", "iphone", "voice", "other")


@dataclass
class Contact:
    name: str = ""
    given: str = ""
    family: str = ""
    org: str = ""
    note: str = ""
    numbers: list[tuple[str, str]] = field(default_factory=list)   # (label, E.164 or URI)
    emails: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    favorite: bool = False
    uid: str = ""
    id: int | None = None

    def display_name(self) -> str:
        if self.name:
            return self.name
        full = " ".join(p for p in (self.given, self.family) if p)
        return full or self.org or (self.numbers[0][1] if self.numbers else "Unnamed")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.display_name(), "given": self.given, "family": self.family,
            "org": self.org, "note": self.note, "numbers": [list(n) for n in self.numbers],
            "emails": self.emails, "groups": self.groups, "favorite": self.favorite, "uid": self.uid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Contact":
        return cls(
            name=d.get("name", ""), given=d.get("given", ""), family=d.get("family", ""),
            org=d.get("org", ""), note=d.get("note", ""),
            numbers=[tuple(n) for n in d.get("numbers", [])], emails=list(d.get("emails", [])),
            groups=list(d.get("groups", [])), favorite=bool(d.get("favorite")), uid=d.get("uid", ""),
            id=d.get("id"),
        )


# ------------------------------------------------------------------ parsing


def _unfold(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper().split(":", 1)[0]:
            lines[-1] = lines[-1][:-1] + line  # vCard 2.1 soft line break
        else:
            lines.append(line)
    return [ln for ln in lines if ln.strip()]


def _unescape(v: str) -> str:
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _split(v: str, sep: str) -> list[str]:
    parts, cur, esc = [], [], False
    for ch in v:
        if esc:
            cur.append("\\" + ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [_unescape(p) for p in parts]


def _parse_line(line: str) -> tuple[str, dict[str, list[str]], str]:
    # name[;params]:value -- colons inside quoted param values are allowed
    in_q, idx = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            idx = i
            break
    if idx < 0:
        return "", {}, ""
    head, value = line[:idx], line[idx + 1:]
    parts = head.split(";")
    name = parts[0].split(".")[-1].upper()   # drop "item1." property groups
    params: dict[str, list[str]] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params.setdefault(k.upper(), []).extend(x.strip('"').lower() for x in v.split(","))
        else:  # vCard 2.1 bare type, e.g. TEL;CELL:
            params.setdefault("TYPE", []).append(p.lower())
    enc = [e.upper() for e in params.get("ENCODING", [])]
    if "QUOTED-PRINTABLE" in enc:
        charset = (params.get("CHARSET") or ["utf-8"])[0]
        value = quopri.decodestring(value.encode("latin-1", "replace")).decode(charset, "replace")
    return name, params, value


def _tel_label(types: list[str]) -> str:
    for t in types:
        if t in _TEL_TYPES and t not in ("voice", "pref"):
            return {"mobile": "cell", "iphone": "cell"}.get(t, t)
    return "other" if not types or types == ["pref"] else "voice" if "voice" in types else types[0]


def parse(text: str, region: str = "US") -> list[Contact]:
    """Parse every vCard in `text`. Malformed cards are skipped, not fatal."""
    contacts: list[Contact] = []
    cur: Contact | None = None
    for line in _unfold(text):
        name, params, value = _parse_line(line)
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            cur = Contact()
            continue
        if cur is None:
            continue
        if name == "END" and value.strip().upper() == "VCARD":
            if cur.display_name() != "Unnamed" or cur.numbers:
                cur.uid = cur.uid or str(uuid.uuid4())
                contacts.append(cur)
            cur = None
        elif name == "FN":
            cur.name = _unescape(value).strip()
        elif name == "N":
            parts = _split(value, ";") + ["", ""]
            cur.family, cur.given = parts[0].strip(), parts[1].strip()
        elif name == "ORG":
            cur.org = _split(value, ";")[0].strip()
        elif name == "NOTE":
            cur.note = _unescape(value)
        elif name == "EMAIL":
            cur.emails.append(_unescape(value).strip())
        elif name == "UID":
            cur.uid = value.strip()
        elif name == "CATEGORIES":
            for g in _split(value, ","):
                g = g.strip()
                if g and g not in cur.groups:
                    cur.groups.append(g)
        elif name == FAVORITE_PROP:
            cur.favorite = value.strip().lower() in ("1", "true", "yes")
        elif name == "TEL":
            raw = _unescape(value).strip()
            addr = numbers.normalize_address(raw, region) or raw
            if addr and all(addr != n for _, n in cur.numbers):
                cur.numbers.append((_tel_label(params.get("TYPE", [])), addr))
        elif name == "IMPP":  # sip:/xmpp:/matrix: addresses are callable too
            raw = value.strip()
            if numbers.is_uri(raw):
                cur.numbers.append(("impp", raw))
    return contacts


# ------------------------------------------------------------------ export


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _fold(line: str) -> str:
    out, cur = [], b""
    for ch in line:
        b = ch.encode()
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode())
            cur = b""
        cur += b
    out.append(cur.decode())
    return "\r\n ".join(out)


def export(contacts: list[Contact], version: str = "3.0") -> str:
    lines: list[str] = []
    for c in contacts:
        card = ["BEGIN:VCARD", f"VERSION:{version}", f"FN:{_escape(c.display_name())}",
                f"N:{_escape(c.family)};{_escape(c.given)};;;"]
        if c.uid:
            card.append(f"UID:{c.uid}")
        if c.org:
            card.append(f"ORG:{_escape(c.org)}")
        for label, value in c.numbers:
            if label == "impp":
                card.append(f"IMPP:{value}")
                continue
            t = label.upper() if version == "3.0" else label.lower()
            if version == "4.0" and value.startswith("+"):
                card.append(f'TEL;VALUE=uri;TYPE={t}:tel:{value}')
            else:
                card.append(f"TEL;TYPE={t}:{value}")
        for e in c.emails:
            card.append(f"EMAIL:{e}")
        if c.groups:
            card.append("CATEGORIES:" + ",".join(_escape(g) for g in c.groups))
        if c.note:
            card.append(f"NOTE:{_escape(c.note)}")
        if c.favorite:
            card.append(f"{FAVORITE_PROP}:1")
        card.append("END:VCARD")
        lines.extend(_fold(ln) for ln in card)
    return "\r\n".join(lines) + ("\r\n" if lines else "")
