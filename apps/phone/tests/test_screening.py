"""Call screening rules: precedence, DND, block/allow lists, unknown/withheld/spam policies."""
import os
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"

from omarchy_phone import screening as S  # noqa: E402
from omarchy_phone.store import DEFAULT_SETTINGS  # noqa: E402

FRIEND = "+12125550101"
STRANGER = "+13125550142"


def ctx(**kw):
    settings = dict(DEFAULT_SETTINGS, own_number="+12125550100")
    settings.update(kw.pop("settings", {}))
    return S.Context(settings=settings, **kw)


class Screening(unittest.TestCase):
    def test_contacts_and_unknown_ring_by_default(self):
        self.assertEqual(S.screen(FRIEND, ctx(is_contact=True)).action, S.RING)
        self.assertEqual(S.screen(STRANGER, ctx()).action, S.RING)

    def test_unknown_policy(self):
        for action in (S.SILENT, S.VOICEMAIL, S.REJECT):
            d = S.screen(STRANGER, ctx(settings={"unknown_action": action}))
            self.assertEqual((d.action, d.rule), (action, "unknown"))
        # contacts are never "unknown"
        d = S.screen(FRIEND, ctx(is_contact=True, settings={"unknown_action": S.REJECT}))
        self.assertEqual(d.action, S.RING)

    def test_block_list_patterns(self):
        c = ctx(block=[("+13125550142", S.REJECT), ("+1800*", S.VOICEMAIL), ("+4477009001??", S.SILENT)])
        self.assertEqual(S.screen(STRANGER, c).action, S.REJECT)
        self.assertEqual(S.screen("+18005550199", c).action, S.VOICEMAIL)
        self.assertEqual(S.screen("+447700900123", c).action, S.SILENT)
        self.assertEqual(S.screen("+44770090012", c).action, S.RING)      # too short for the glob
        self.assertEqual(S.screen("+13125550143", c).action, S.RING)

    def test_block_applies_to_contacts_too(self):
        c = ctx(is_contact=True, block=[(FRIEND, S.REJECT)])
        self.assertEqual(S.screen(FRIEND, c).action, S.REJECT)

    def test_allow_list_beats_everything(self):
        c = ctx(allow=["+1312555*"], block=[("+1312*", S.REJECT)],
                settings={"dnd": True, "unknown_action": S.REJECT})
        d = S.screen(STRANGER, c)
        self.assertEqual((d.action, d.rule), (S.RING, "allow:+1312555*"))

    def test_favorite_beats_block_and_dnd(self):
        c = ctx(is_contact=True, is_favorite=True, block=[("+1212*", S.REJECT)], settings={"dnd": True})
        self.assertEqual(S.screen(FRIEND, c).rule, "favorite")

    def test_withheld(self):
        for addr in ("", "anonymous", "Restricted", "sip:anonymous@example.org"):
            self.assertEqual(S.screen(addr, ctx()).action, S.VOICEMAIL, addr)
        self.assertEqual(S.screen("anonymous", ctx(settings={"withheld_action": S.REJECT})).action, S.REJECT)

    def test_dnd(self):
        on = {"dnd": True}
        self.assertEqual(S.screen(FRIEND, ctx(is_contact=True, settings=on)).action, S.SILENT)
        self.assertEqual(S.screen(STRANGER, ctx(settings=dict(on, dnd_action=S.VOICEMAIL))).action, S.VOICEMAIL)
        # repeated caller breaks through, unless disabled
        self.assertEqual(S.screen(STRANGER, ctx(recent_calls=1, settings=on)).rule, "dnd:repeat")
        self.assertEqual(S.screen(STRANGER, ctx(recent_calls=1, settings=dict(on, dnd_repeat_callers=False))).action,
                         S.SILENT)
        # allowed groups pass
        c = ctx(is_contact=True, contact_groups=["Family"], allowed_groups=["Family"], settings=on)
        self.assertEqual(S.screen(FRIEND, c).action, S.RING)

    def test_spam(self):
        self.assertEqual(S.screen("+19005550123", ctx()).rule, "premium:+1900")
        self.assertEqual(S.screen("+13125550199", ctx(spam=["+13125550199"])).action, S.VOICEMAIL)
        self.assertEqual(S.screen("+13125550199", ctx(spam=["+13125550199"],
                                                      settings={"spam_action": S.REJECT})).action, S.REJECT)
        # a contact who happens to have a premium number is not spam
        self.assertEqual(S.screen("+19005550123", ctx(is_contact=True)).action, S.RING)

    def test_neighbor_spoofing(self):
        self.assertEqual(S.screen("+12125550177", ctx()).rule, "spoof")          # same +1 212 555
        self.assertEqual(S.screen("+12125550177", ctx(is_contact=True)).action, S.RING)
        self.assertEqual(S.screen("+12125550177", ctx(settings={"neighbor_spoof_filter": False})).action, S.RING)
        self.assertEqual(S.screen("+12125550100", ctx()).action, S.RING)         # our own number

    def test_emergency(self):
        self.assertEqual(S.screen("911", ctx(block=[("*", S.REJECT)], settings={"dnd": True})).action, S.RING)

    def test_sip_uri_patterns(self):
        c = ctx(block=[("sip:*@spam.example", S.REJECT)])
        self.assertEqual(S.screen("sip:bot@spam.example", c).action, S.REJECT)
        self.assertEqual(S.screen("sip:ana@example.org", c).action, S.RING)


if __name__ == "__main__":
    unittest.main()
