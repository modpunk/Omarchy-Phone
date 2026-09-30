"""Phone number normalization, formatting and detection in free text.

Uses libphonenumber (python-phonenumbers) when it is installed, and a small built-in
fallback otherwise. Set OMARCHY_PHONE_NO_LIBPHONENUMBER=1 to force the fallback.

Numbers are stored as E.164 ("+15550123456"). Non-numeric addresses (SIP URIs,
Matrix IDs) are passed through unchanged by `normalize_address`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

try:  # pragma: no cover - depends on the system
    if os.environ.get("OMARCHY_PHONE_NO_LIBPHONENUMBER"):
        raise ImportError
    import phonenumbers as _pn
except ImportError:
    _pn = None

HAVE_LIBPHONENUMBER = _pn is not None

# region -> (country calling code, national trunk prefix)
REGIONS: dict[str, tuple[str, str]] = {
    "US": ("1", "1"), "CA": ("1", "1"), "GB": ("44", "0"), "IE": ("353", "0"),
    "DE": ("49", "0"), "AT": ("43", "0"), "CH": ("41", "0"), "FR": ("33", "0"),
    "BE": ("32", "0"), "NL": ("31", "0"), "LU": ("352", ""), "ES": ("34", ""),
    "PT": ("351", ""), "IT": ("39", ""), "DK": ("45", ""), "NO": ("47", ""),
    "SE": ("46", "0"), "FI": ("358", "0"), "PL": ("48", ""), "CZ": ("420", ""),
    "GR": ("30", ""), "AU": ("61", "0"), "NZ": ("64", "0"), "JP": ("81", "0"),
    "KR": ("82", "0"), "CN": ("86", "0"), "IN": ("91", "0"), "BR": ("55", "0"),
    "MX": ("52", ""), "AR": ("54", "0"), "ZA": ("27", "0"), "IL": ("972", "0"),
    "TR": ("90", "0"), "UA": ("380", "0"), "SG": ("65", ""), "HK": ("852", ""),
    "PH": ("63", "0"), "NG": ("234", "0"), "EG": ("20", "0"), "RU": ("7", "8"),
}
_CALLING_CODES = sorted({cc for cc, _ in REGIONS.values()}, key=len, reverse=True)
# international dialling prefixes by region ("00" everywhere else)
_IDD = {"US": "011", "CA": "011", "AU": "0011", "JP": "010"}

# Separators people put inside numbers.
_SEP = re.compile(r"[\s().\-/ ‐-―]")
_EXT = re.compile(r"\s*(?:ext\.?|extension|x|#)\s*\d{1,6}\s*$", re.I)
_URI = re.compile(r"^(?:sips?:|tel:|matrix:|xmpp:)|^@[^:\s]+:[^\s]+$|^[^@\s]+@[^@\s]+\.[^@\s]+$", re.I)


def is_uri(address: str) -> bool:
    """True for SIP/XMPP/Matrix-style addresses that are not plain phone numbers."""
    a = address.strip()
    if a.lower().startswith("tel:"):
        return False
    return bool(_URI.match(a))


def digits_only(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _split_cc(digits: str) -> tuple[str, str] | None:
    for cc in _CALLING_CODES:
        if digits.startswith(cc):
            return cc, digits[len(cc):]
    return None


def _valid_nanp(national: str) -> bool:
    return len(national) == 10 and national[0] in "23456789" and national[3] in "23456789"


def _valid_e164(e164: str) -> bool:
    d = e164[1:]
    if not d.isdigit() or not 8 <= len(d) <= 15:
        return False
    split = _split_cc(d)
    if split is None:
        return 8 <= len(d) <= 15  # unknown country code: accept on length only
    cc, national = split
    if cc == "1":
        return _valid_nanp(national)
    return 6 <= len(national) <= 13


def normalize(raw: str, region: str = "US") -> str | None:
    """Return the E.164 form of `raw`, or None if it is not a plausible phone number."""
    if raw is None:
        return None
    s = raw.strip()
    if s.lower().startswith("tel:"):
        s = s[4:].split(";")[0]
    s = _EXT.sub("", s)
    if not s or re.search(r"[^\d\s().\-/+ ‐-―]", s):
        return None
    if s.count("+") > 1 or ("+" in s and not s.lstrip("(").startswith("+")):
        return None
    region = region.upper()
    if _pn is not None:  # pragma: no cover - depends on the system
        try:
            n = _pn.parse(s, region)
        except _pn.NumberParseException:
            return None
        if not _pn.is_possible_number(n):
            return None
        return _pn.format_number(n, _pn.PhoneNumberFormat.E164)
    plus = s.lstrip("(").startswith("+")
    d = digits_only(s)
    if not d:
        return None
    if plus:
        e = "+" + d
        return e if _valid_e164(e) else None
    idd = _IDD.get(region, "00")
    for prefix in {idd, "00"}:
        if d.startswith(prefix) and len(d) > len(prefix) + 7:
            e = "+" + d[len(prefix):]
            return e if _valid_e164(e) else None
    cc, trunk = REGIONS.get(region, ("1", "1"))
    if cc == "1":
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        return "+1" + d if _valid_nanp(d) else None
    if trunk and d.startswith(trunk):
        d = d[len(trunk):]
    e = "+" + cc + d
    return e if _valid_e164(e) else None


def normalize_address(raw: str, region: str = "US") -> str | None:
    """E.164 for numbers, the URI itself for SIP/Matrix/XMPP addresses."""
    if raw and is_uri(raw):
        return raw.strip()
    return normalize(raw, region)


def format_number(e164: str, region: str = "US") -> str:
    """Human-readable form: national format for the home region, international otherwise."""
    if not e164 or not e164.startswith("+"):
        return e164 or ""
    if _pn is not None:  # pragma: no cover
        try:
            n = _pn.parse(e164, None)
            home = _pn.region_code_for_number(n) == region.upper()
            fmt = _pn.PhoneNumberFormat.NATIONAL if home else _pn.PhoneNumberFormat.INTERNATIONAL
            return _pn.format_number(n, fmt)
        except _pn.NumberParseException:
            return e164
    split = _split_cc(e164[1:])
    if split is None:
        return e164
    cc, nat = split
    home_cc, trunk = REGIONS.get(region.upper(), ("1", "1"))
    if cc == "1" and len(nat) == 10:
        body = f"({nat[:3]}) {nat[3:6]}-{nat[6:]}"
        return body if home_cc == "1" else f"+1 {nat[:3]}-{nat[3:6]}-{nat[6:]}"
    groups = _group(nat)
    if cc == home_cc:
        return (trunk + groups) if trunk else groups
    return f"+{cc} {groups}"


def _group(nat: str) -> str:
    if len(nat) <= 4:
        return nat
    if len(nat) == 10:
        return f"{nat[:2]} {nat[2:6]} {nat[6:]}" if nat[0] in "123" else f"{nat[:4]} {nat[4:7]} {nat[7:]}"
    head = len(nat) % 4 or 4
    parts = [nat[:head]] + [nat[i:i + 4] for i in range(head, len(nat), 4)]
    return " ".join(parts)


def format_as_you_type(raw: str, region: str = "US") -> str:
    """Light formatting for the keypad field; never drops characters the user typed."""
    d = digits_only(raw)
    plus = raw.startswith("+")
    if _pn is not None:  # pragma: no cover
        f = _pn.AsYouTypeFormatter(region.upper())
        out = ""
        for ch in ("+" if plus else "") + d:
            out = f.input_digit(ch)
        return out
    if plus or any(c in raw for c in "*#,;"):
        return raw
    if REGIONS.get(region.upper(), ("1",))[0] == "1":
        if len(d) == 11 and d[0] == "1":
            return f"1 ({d[1:4]}) {d[4:7]}-{d[7:]}"
        if 7 < len(d) <= 10:
            return f"({d[:3]}) {d[3:6]}-{d[6:]}"
        if 4 < len(d) <= 7:
            return f"{d[:3]}-{d[3:]}"
    return raw


def same_number(a: str, b: str) -> bool:
    """Loose equality used for caller-ID matching (numbers may arrive without a country code)."""
    if not a or not b:
        return False
    if a == b:
        return True
    da, db = digits_only(a), digits_only(b)
    if len(da) < 7 or len(db) < 7:
        return False
    tail = min(9, len(da), len(db))
    return da[-tail:] == db[-tail:]


# ---------------------------------------------------------------- detection


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    raw: str
    e164: str

    @property
    def uri(self) -> str:
        return "tel:" + self.e164


_CANDIDATE = re.compile(
    r"(?<![\w+$€£¥#@./=-])"                     # not glued to a word, price, id or URL
    r"(?:tel:)?(?:\+|\(\+?)?\d[\d \t().\-/ ‐-―]{5,22}\d"
    r"(?:\s*(?:ext\.?|x)\s*\d{1,6})?"
    r"(?![\w$€%]|[.,]\d)"
)
_DATE = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")
_IP = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_RANGE = re.compile(r"^\d{1,4}\s*-\s*\d{1,4}$")
_ID_CONTEXT = re.compile(
    r"(?:order|invoice|tracking|ref(?:erence)?|account|acct|card|iban|isbn|serial|id|po|ticket|case|"
    r"confirmation|code|pin|otp)\s*(?:no\.?|number|nr\.?|#)?\s*[:#]?\s*$",
    re.I,
)


def find_numbers(text: str, region: str = "US") -> list[Match]:
    """Detect phone numbers in `text`. Conservative: prefers missing a number over
    turning a date, time, price, IP address or order ID into a tap-to-call link."""
    if not text:
        return []
    if _pn is not None:  # pragma: no cover
        out = []
        for m in _pn.PhoneNumberMatcher(text, region.upper(), leniency=_pn.Leniency.VALID):
            out.append(Match(m.start, m.end, m.raw_string,
                             _pn.format_number(m.number, _pn.PhoneNumberFormat.E164)))
        return out
    found: list[Match] = []
    for m in _CANDIDATE.finditer(text):
        raw = m.group(0).rstrip(" \t-./(")
        start = m.start()
        # an opening paren belongs to the number only if it closes inside it
        if raw.startswith("(") and ")" not in raw:
            raw, start = raw[1:], start + 1
        core = raw[4:] if raw.lower().startswith("tel:") else raw
        core_nx = _EXT.sub("", core)
        d = digits_only(core_nx)
        if not 8 <= len(d) <= 15:
            continue
        compact = _SEP.sub("", core_nx)
        if _DATE.match(core_nx.strip()) or _IP.match(core_nx.strip()) or _RANGE.match(core_nx.strip()):
            continue
        if re.search(r"\d\.\d{1,2}$", core_nx) and "." in core_nx and core_nx.count(".") == 1:
            continue  # decimal like 12345.50
        if _ID_CONTEXT.search(text[max(0, start - 24):start]):
            continue
        separators = len(core_nx) - len(compact)
        has_plus = compact.startswith("+")
        if not has_plus and separators == 0 and len(d) not in (10, 11):
            continue  # a bare run of digits is more likely an ID than a phone number
        if core_nx.count("(") != core_nx.count(")"):
            continue
        e164 = normalize(core_nx, region)
        if e164 is None:
            continue
        found.append(Match(start, start + len(raw), raw, e164))
    return found


def first_number(text: str, region: str = "US") -> str | None:
    """E.164 of the first number in `text` (used by Paste), or the text itself if it
    is a whole SIP/Matrix address."""
    if not text:
        return None
    t = text.strip()
    whole = normalize_address(t, region)
    if whole:
        return whole
    ms = find_numbers(t, region)
    return ms[0].e164 if ms else None


def linkify(text: str, region: str = "US") -> str:
    """Pango markup with detected numbers turned into tel: links (for Gtk.Label)."""
    from xml.sax.saxutils import escape

    out, pos = [], 0
    for m in find_numbers(text, region):
        out.append(escape(text[pos:m.start]))
        out.append(f'<a href="{m.uri}">{escape(m.raw)}</a>')
        pos = m.end
    out.append(escape(text[pos:]))
    return "".join(out)
