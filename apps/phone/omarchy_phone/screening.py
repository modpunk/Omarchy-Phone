"""Call screening: decide what happens to an incoming call before the phone rings.

`screen()` is a pure function of the caller and a `Context` snapshot, so it is easy to test
and cheap to run. First matching rule wins; see docs/phone/DESIGN.md section 5.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from . import numbers

RING, SILENT, VOICEMAIL, REJECT = "ring", "silent", "voicemail", "reject"
ACTIONS = (RING, SILENT, VOICEMAIL, REJECT)

# Premium-rate / commonly abused prefixes (E.164). Users can add their own via the spam list.
PREMIUM_PREFIXES = ("+1900", "+1976", "+44909", "+44908", "+449", "+4990", "+33899", "+3489")
EMERGENCY = ("112", "911", "999", "000", "110", "119")
REPEAT_WINDOW = 180  # seconds: a second call inside this window breaks through DND


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    rule: str = ""

    def to_dict(self):
        return {"action": self.action, "reason": self.reason, "rule": self.rule}


@dataclass
class Context:
    settings: dict = field(default_factory=dict)
    allow: list[str] = field(default_factory=list)            # patterns
    block: list[tuple[str, str]] = field(default_factory=list)  # (pattern, action)
    spam: list[str] = field(default_factory=list)             # user-reported spam patterns
    is_contact: bool = False
    is_favorite: bool = False
    contact_groups: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)   # groups that pass DND
    recent_calls: int = 0                                     # calls from this caller in REPEAT_WINDOW


def matches(pattern: str, address: str) -> bool:
    """Exact E.164/URI, a prefix ending in '*', or a glob ('?' = one digit)."""
    if not pattern or not address:
        return False
    p = pattern.strip()
    if any(ch in p for ch in "*?["):
        return fnmatch.fnmatchcase(address, p)
    if p == address:
        return True
    return p.startswith("+") and address.startswith("+") and numbers.same_number(p, address) and len(
        numbers.digits_only(p)) == len(numbers.digits_only(address))


def _is_withheld(address: str) -> bool:
    a = (address or "").strip().lower()
    return a in ("", "anonymous", "unknown", "restricted", "private", "withheld") or a.startswith(
        "sip:anonymous@")


def _neighbor_spoof(address: str, own: str) -> bool:
    """Same country and first six national digits as our own number: classic neighbour spoofing."""
    if not own or not address.startswith("+") or not own.startswith("+") or address == own:
        return False
    da, do = numbers.digits_only(address), numbers.digits_only(own)
    return len(da) == len(do) and da[:7] == do[:7]


def screen(address: str, ctx: Context) -> Decision:
    s = ctx.settings
    addr = (address or "").strip()

    if numbers.digits_only(addr) in EMERGENCY and not addr.startswith("+"):
        return Decision(RING, "Emergency services", "emergency")
    for p in ctx.allow:
        if matches(p, addr):
            return Decision(RING, "Allowed", f"allow:{p}")
    if ctx.is_favorite:
        return Decision(RING, "Favorite", "favorite")

    for p, action in ctx.block:
        if matches(p, addr):
            return Decision(action if action in ACTIONS else REJECT, f"Blocked ({p})", f"block:{p}")

    if _is_withheld(addr):
        return Decision(s.get("withheld_action", VOICEMAIL), "Number withheld", "withheld")

    if s.get("dnd"):
        if set(ctx.contact_groups) & set(ctx.allowed_groups):
            return Decision(RING, "Allowed group", "dnd:group")
        if s.get("dnd_repeat_callers", True) and ctx.recent_calls >= 1:
            return Decision(RING, "Repeated call", "dnd:repeat")
        return Decision(s.get("dnd_action", SILENT), "Do not disturb", "dnd")

    if not ctx.is_contact:
        for p in ctx.spam:
            if matches(p, addr):
                return Decision(s.get("spam_action", VOICEMAIL), "Reported spam", f"spam:{p}")
        for p in PREMIUM_PREFIXES:
            if addr.startswith(p):
                return Decision(s.get("spam_action", VOICEMAIL), "Premium-rate number", f"premium:{p}")
        if s.get("neighbor_spoof_filter", True) and _neighbor_spoof(addr, s.get("own_number", "")):
            return Decision(s.get("spam_action", VOICEMAIL), "Likely spoofed", "spoof")
        unknown = s.get("unknown_action", RING)
        return Decision(unknown, "Unknown caller" if unknown != RING else "", "unknown")

    return Decision(RING, "", "contact")
