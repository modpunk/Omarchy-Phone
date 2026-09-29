"""Number normalization and detection (built-in fallback; libphonenumber is disabled in tests).

All numbers are fictional: NANP 555-01xx and Ofcom drama ranges (+44 20 7946 0xxx, +44 7700 900xxx).
"""
import os
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"

from omarchy_phone import numbers as N  # noqa: E402


class Normalize(unittest.TestCase):
    def test_us_formats(self):
        for raw in ["(212) 555-0123", "212-555-0123", "212.555.0123", "2125550123",
                    "1 212 555 0123", "+1 212-555-0123", "+1 (212) 555-0123", "tel:+12125550123",
                    "011 1 212 555 0123", "212-555-0123 ext. 45"]:
            self.assertEqual(N.normalize(raw, "US"), "+12125550123", raw)

    def test_uk(self):
        self.assertEqual(N.normalize("020 7946 0123", "GB"), "+442079460123")
        self.assertEqual(N.normalize("+44 7700 900123", "US"), "+447700900123")
        self.assertEqual(N.normalize("0044 7700 900123", "DE"), "+447700900123")

    def test_rejects(self):
        for raw in ["", "hello", "555-0123", "123", "+1 555 012", "1-800-FLOWERS", "+1+2125550123",
                    "(112) 555-0123", "2125550123abc"]:
            self.assertIsNone(N.normalize(raw, "US"), raw)

    def test_addresses(self):
        self.assertTrue(N.is_uri("sip:alice@example.org"))
        self.assertTrue(N.is_uri("@alice:example.org"))
        self.assertFalse(N.is_uri("tel:+12125550123"))
        self.assertEqual(N.normalize_address("sip:alice@example.org"), "sip:alice@example.org")
        self.assertEqual(N.normalize_address("212 555 0123"), "+12125550123")

    def test_format(self):
        self.assertEqual(N.format_number("+12125550123", "US"), "(212) 555-0123")
        self.assertEqual(N.format_number("+12125550123", "GB"), "+1 212-555-0123")
        self.assertEqual(N.format_number("+442079460123", "US"), "+44 20 7946 0123")
        self.assertEqual(N.format_number("+442079460123", "GB"), "020 7946 0123")
        self.assertEqual(N.format_as_you_type("21255501", "US"), "(212) 555-01")
        self.assertEqual(N.format_as_you_type("5550123", "US"), "555-0123")
        self.assertEqual(N.format_as_you_type("*67#", "US"), "*67#")

    def test_same_number(self):
        self.assertTrue(N.same_number("+12125550123", "2125550123"))
        self.assertFalse(N.same_number("+12125550123", "+12125550124"))
        self.assertFalse(N.same_number("123", "123 "))


class Detect(unittest.TestCase):
    def e164s(self, text, region="US"):
        return [m.e164 for m in N.find_numbers(text, region)]

    def test_finds_numbers_in_prose(self):
        text = ("Call me at (212) 555-0123 or on my cell 646.555.0199. "
                "London office: +44 20 7946 0123, mobile +44 7700 900456.")
        self.assertEqual(self.e164s(text),
                         ["+12125550123", "+16465550199", "+442079460123", "+447700900456"])

    def test_spans_are_exact(self):
        text = "ring (212) 555-0123 now"
        m = N.find_numbers(text)[0]
        self.assertEqual(text[m.start:m.end], "(212) 555-0123")
        self.assertEqual(m.uri, "tel:+12125550123")

    def test_extension_and_tel_uri(self):
        self.assertEqual(self.e164s("Front desk 212-555-0123 x204"), ["+12125550123"])
        self.assertEqual(self.e164s("<a href=x>tel:+12125550123</a>"), ["+12125550123"])

    def test_no_false_positives(self):
        for text in [
            "Meeting on 2026-09-29 at 10:30-11:45",
            "Due 09/29/2026, see you 29.09.2026",
            "Server at 192.168.100.200 port 8080",
            "Total: $1234567.89 or €2125550123",
            "Order #2125550123 shipped",
            "Your order number: 212 555 0123 is ready",
            "tracking 1Z999AA10123456784",
            "Card 4111 1111 1111 1111 expires",
            "ID 20260929123045",
            "version 1.2.3.4 build 55501234",
            "pi is 3.14159265358979",
            "pages 1234-5678",
            "https://example.org/u/2125550123",
            "use code 12345678 to sign in",
        ]:
            self.assertEqual(self.e164s(text), [], text)

    def test_region_affects_national_numbers(self):
        self.assertEqual(self.e164s("Ring 020 7946 0123 today", "GB"), ["+442079460123"])
        self.assertEqual(self.e164s("Ring 020 7946 0123 today", "US"), [])

    def test_first_number_for_paste(self):
        self.assertEqual(N.first_number("  +1 (212) 555-0123\n"), "+12125550123")
        self.assertEqual(N.first_number("Hi! It's Ana, my number is 212 555 0199 :)"), "+12125550199")
        self.assertEqual(N.first_number("sip:ana@example.org"), "sip:ana@example.org")
        self.assertIsNone(N.first_number("nothing to see here"))

    def test_linkify_escapes(self):
        out = N.linkify("<b> 212-555-0123 & more")
        self.assertEqual(out, '&lt;b&gt; <a href="tel:+12125550123">212-555-0123</a> &amp; more')


if __name__ == "__main__":
    unittest.main()
