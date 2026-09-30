"""Contact import/export (vCard 2.1, 3.0, 4.0) and the SQLite contact store."""
import os
import tempfile
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"

from omarchy_phone import vcard  # noqa: E402
from omarchy_phone.store import Store  # noqa: E402

V21 = (
    "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Doe;Jane;;;\r\nFN:Jane Doe\r\n"
    "TEL;CELL;PREF:(212) 555-0101\r\nTEL;WORK:212.555.0102\r\n"
    "NOTE;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:Caf=C3=A9 at 5=\r\npm\r\n"
    "PHOTO;ENCODING=BASE64;TYPE=JPEG:/9j/4AAQSkZJRgABAQ\r\n AAAQABAAD\r\n\r\n"
    "END:VCARD\r\n"
)

V30 = """BEGIN:VCARD
VERSION:3.0
FN:Ana Lima
N:Lima;Ana;;;
ORG:Example Co\\, Ltd;R&D
item1.TEL;type=CELL;type=VOICE;type=pref:+44 7700 900123
TEL;TYPE=HOME:020 7946 0123
EMAIL;TYPE=INTERNET:ana@example.org
CATEGORIES:Family,Climbing
NOTE:Line one\\nLine two\\, with comma
X-OMARCHY-FAVORITE:1
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Office Bridge
IMPP:sip:bridge@example.org
END:VCARD
"""

V40 = """BEGIN:VCARD
VERSION:4.0
UID:urn:uuid:4fbe8971-0bc3-424c-9c26-36c3e1eff6b1
FN:Bo Chen
TEL;VALUE=uri;TYPE="voice,cell";PREF=1:tel:+1-646-555-0199
TEL;VALUE=uri;TYPE=work:tel:+1-646-555-0199
CATEGORIES:Work
END:VCARD
BEGIN:VCARD
VERSION:4.0
END:VCARD
"""


class Import(unittest.TestCase):
    def test_v21(self):
        [c] = vcard.parse(V21)
        self.assertEqual(c.display_name(), "Jane Doe")
        self.assertEqual((c.given, c.family), ("Jane", "Doe"))
        self.assertEqual(c.numbers, [("cell", "+12125550101"), ("work", "+12125550102")])
        self.assertEqual(c.note, "Café at 5pm")

    def test_v30(self):
        ana, bridge = vcard.parse(V30, region="GB")
        self.assertEqual(ana.org, "Example Co, Ltd")
        self.assertEqual(ana.numbers, [("cell", "+447700900123"), ("home", "+442079460123")])
        self.assertEqual(ana.groups, ["Family", "Climbing"])
        self.assertTrue(ana.favorite)
        self.assertEqual(ana.note, "Line one\nLine two, with comma")
        self.assertEqual(ana.emails, ["ana@example.org"])
        self.assertEqual(bridge.numbers, [("impp", "sip:bridge@example.org")])

    def test_v40_dedupes_and_skips_empty(self):
        cards = vcard.parse(V40)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].uid, "urn:uuid:4fbe8971-0bc3-424c-9c26-36c3e1eff6b1")
        self.assertEqual(cards[0].numbers, [("cell", "+16465550199")])

    def test_garbage_is_not_fatal(self):
        self.assertEqual(vcard.parse("not a vcard\nFN:x\n"), [])
        self.assertEqual(len(vcard.parse("BEGIN:VCARD\nFN:Only Name\nEND:VCARD\n")), 1)

    def test_round_trip(self):
        original = vcard.parse(V30, region="GB")
        for version in ("3.0", "4.0"):
            again = vcard.parse(vcard.export(original, version), region="GB")
            self.assertEqual([c.to_dict() for c in again], [c.to_dict() for c in original], version)

    def test_export_folds_long_lines(self):
        c = vcard.Contact(name="N", note="x" * 300)
        out = vcard.export([c])
        self.assertTrue(all(len(line.encode()) <= 75 for line in out.split("\r\n")))
        self.assertEqual(vcard.parse(out)[0].note, "x" * 300)


class StoreContacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "phone.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_import_merges_by_uid_and_number(self):
        self.assertEqual(self.store.import_vcard(V30, region="GB"), (2, 0))
        self.assertEqual(self.store.import_vcard(V30, region="GB"), (0, 2))   # re-import updates
        self.store.import_vcard(V21)
        self.assertEqual(len(self.store.contacts()), 3)
        self.assertEqual([c.display_name() for c in self.store.favorites()], ["Ana Lima"])
        self.assertEqual(sorted(self.store.groups()), ["Climbing", "Family"])
        self.assertEqual([c.display_name() for c in self.store.contacts(group="Family")], ["Ana Lima"])

    def test_lookup_by_number(self):
        self.store.import_vcard(V21)
        self.assertEqual(self.store.contact_for_number("+12125550102").display_name(), "Jane Doe")
        self.assertEqual(self.store.contact_for_number("2125550101").display_name(), "Jane Doe")
        self.assertIsNone(self.store.contact_for_number("+12125550199"))

    def test_search_and_export(self):
        self.store.import_vcard(V21 + V30, region="GB")
        self.assertEqual([c.display_name() for c in self.store.contacts(query="ana")], ["Ana Lima"])
        self.assertEqual([c.display_name() for c in self.store.contacts(query="0101")], ["Jane Doe"])
        exported = vcard.parse(self.store.export_vcard())
        self.assertEqual(sorted(c.display_name() for c in exported), ["Ana Lima", "Jane Doe", "Office Bridge"])

    def test_edit_favorite_groups_delete(self):
        self.store.import_vcard(V21)
        c = self.store.contacts()[0]
        self.store.set_favorite(c.id, True)
        self.store.set_groups(c.id, ["Work"])
        c = self.store.contact(c.id)
        self.assertTrue(c.favorite)
        self.assertEqual(c.groups, ["Work"])
        self.store.delete_contact(c.id)
        self.assertEqual(self.store.contacts(), [])


if __name__ == "__main__":
    unittest.main()
