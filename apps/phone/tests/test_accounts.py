"""SIP account CRUD, validation, baresip line building and keyring isolation.

Uses the in-memory keyring stand-in (OMARCHY_PHONE_KEYRING=memory) so this never touches a real
Secret Service; everything else stays in a temp SQLite file, same as the other unit tests.
"""
import json
import os
import tempfile
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"
os.environ["OMARCHY_PHONE_KEYRING"] = "memory"
os.environ["OMARCHY_PHONE_NO_NOTIFY"] = "1"     # PhoneService() below must never touch the real session bus
os.environ["OMARCHY_PHONE_AUDIO_DRYRUN"] = "1"  # ...or the real default audio sink
os.environ.setdefault("OMARCHY_PHONE_NO_UI_LAUNCH", "1")

from omarchy_phone import keyring  # noqa: E402
from omarchy_phone.daemon import PhoneService  # noqa: E402
from omarchy_phone.sip_account import SipAccount, split_username, to_baresip_line, validate  # noqa: E402


class Validate(unittest.TestCase):
    def test_good_account(self):
        acc = SipAccount(display_name="Jane", username="jane", domain="pbx.example.org", transport="udp")
        self.assertEqual(validate(acc, require_password=True, password="hunter2"), [])

    def test_missing_fields(self):
        acc = SipAccount()
        errors = validate(acc, require_password=True, password="")
        self.assertTrue(any("Username" in e for e in errors))
        self.assertTrue(any("Domain" in e for e in errors))
        self.assertTrue(any("Password" in e for e in errors))

    def test_username_must_not_contain_at_or_spaces(self):
        acc = SipAccount(username="jane@pbx.example.org", domain="pbx.example.org")
        errors = validate(acc)
        self.assertTrue(any("Username" in e for e in errors), errors)
        acc2 = SipAccount(username="jane doe", domain="pbx.example.org")
        self.assertTrue(any("Username" in e for e in validate(acc2)))

    def test_bad_domain(self):
        for domain in ("not a host", 'evil";rm', "host;transport=tcp;extra"):
            acc = SipAccount(username="jane", domain=domain)
            self.assertTrue(validate(acc), domain)

    def test_domain_with_port_and_ipv6_ok(self):
        for domain in ("pbx.example.org:5061", "127.0.0.1", "127.0.0.1:5060", "[::1]:5060"):
            acc = SipAccount(username="jane", domain=domain)
            self.assertEqual(validate(acc), [], domain)

    def test_bad_transport(self):
        acc = SipAccount(username="jane", domain="pbx.example.org", transport="quic")
        self.assertTrue(any("Transport" in e for e in validate(acc)))

    def test_password_rejects_quotes_and_angle_brackets(self):
        acc = SipAccount(username="jane", domain="pbx.example.org")
        for bad in ('has"quote', "has<angle>", "line\nbreak"):
            self.assertTrue(validate(acc, password=bad), bad)

    def test_bad_proxy(self):
        acc = SipAccount(username="jane", domain="pbx.example.org", proxy="not a host")
        self.assertTrue(any("proxy" in e.lower() for e in validate(acc)))

    def test_good_proxy_with_scheme_and_port(self):
        acc = SipAccount(username="jane", domain="pbx.example.org", proxy="sip:proxy.example.org:5060")
        self.assertEqual(validate(acc), [])

    def test_split_username(self):
        self.assertEqual(split_username("jane@pbx.example.org"), ("jane", "pbx.example.org"))
        self.assertEqual(split_username("sip:jane@pbx.example.org"), ("jane", "pbx.example.org"))
        self.assertEqual(split_username("sips:jane@pbx.example.org:5061"), ("jane", "pbx.example.org:5061"))
        self.assertEqual(split_username("jane"), ("jane", ""))


class AccountLine(unittest.TestCase):
    def test_basic_udp(self):
        acc = SipAccount(username="jane", domain="pbx.example.org")
        line = to_baresip_line(acc, "hunter2")
        self.assertEqual(line, '<sip:jane@pbx.example.org>;auth_pass="hunter2";regint=300')

    def test_display_name_transport_and_proxy(self):
        acc = SipAccount(display_name="Jane Doe", username="jane", domain="pbx.example.org",
                         proxy="proxy.example.org", transport="tcp")
        line = to_baresip_line(acc, "s3cret", regint=120)
        self.assertEqual(line, '"Jane Doe" <sip:jane@pbx.example.org;transport=tcp>;auth_pass="s3cret";'
                              'outbound="sip:proxy.example.org;transport=tcp";regint=120')

    def test_tls_transport(self):
        acc = SipAccount(username="jane", domain="pbx.example.org", transport="tls")
        line = to_baresip_line(acc, "x")
        self.assertIn("sip:jane@pbx.example.org;transport=tls", line)

    def test_proxy_with_explicit_scheme_and_transport_is_not_doubled(self):
        acc = SipAccount(username="jane", domain="pbx.example.org", proxy="sips:proxy.example.org;transport=tls",
                         transport="tls")
        line = to_baresip_line(acc, "x")
        self.assertEqual(line.count("transport="), 2)   # once on the AOR, once on the proxy (already given)

    def test_password_quoting_escapes_backslash_and_quote(self):
        acc = SipAccount(username="jane", domain="pbx.example.org")
        line = to_baresip_line(acc, 'a"b\\c')
        self.assertIn('auth_pass="a\\"b\\\\c"', line)

    def test_no_password_omits_auth_pass(self):
        acc = SipAccount(username="jane", domain="pbx.example.org")
        line = to_baresip_line(acc, "")
        self.assertNotIn("auth_pass", line)


class KeyringMemory(unittest.TestCase):
    def test_round_trip_and_clear(self):
        keyring.set_password("test-profile-1", "s3cret")
        self.assertEqual(keyring.get_password("test-profile-1"), "s3cret")
        keyring.clear_password("test-profile-1")
        self.assertIsNone(keyring.get_password("test-profile-1"))

    def test_unset_profile_returns_none(self):
        self.assertIsNone(keyring.get_password("never-set-profile"))


class SipAccountCRUD(unittest.TestCase):
    """Through PhoneService (as the D-Bus daemon methods would be called), including the keyring."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        old_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.tmp.name
        self.addCleanup(lambda: os.environ.update(XDG_DATA_HOME=old_xdg) if old_xdg is not None
                        else os.environ.pop("XDG_DATA_HOME", None))
        self.svc = PhoneService(profile="acct-test")
        self.addCleanup(self.svc.shutdown)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(keyring.clear_password, "acct-test")

    def test_no_account_by_default(self):
        self.assertIsNone(self.svc.m_sip_account())
        self.assertIsNone(keyring.get_password("acct-test"))

    def test_save_requires_password_for_a_new_account(self):
        with self.assertRaises(ValueError):
            self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"})

    def test_save_requires_valid_fields(self):
        with self.assertRaises(ValueError):
            self.svc.m_save_sip_account({"username": "", "domain": ""}, password="x")

    def test_save_and_read_back_without_password(self):
        saved = self.svc.m_save_sip_account(
            {"display_name": "Jane", "username": "jane", "domain": "pbx.example.org", "transport": "tcp"},
            password="hunter2")
        self.assertEqual(saved["username"], "jane")
        self.assertTrue(saved["has_password"])
        self.assertNotIn("password", saved)
        got = self.svc.m_sip_account()
        self.assertEqual(got["domain"], "pbx.example.org")
        self.assertNotIn("password", got)
        self.assertEqual(keyring.get_password("acct-test"), "hunter2")

    def test_edit_with_blank_password_keeps_the_old_one(self):
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"}, password="hunter2")
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org", "proxy": "proxy.example.org"})
        self.assertEqual(keyring.get_password("acct-test"), "hunter2")
        self.assertEqual(self.svc.m_sip_account()["proxy"], "proxy.example.org")

    def test_edit_with_new_password_replaces_it(self):
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"}, password="hunter2")
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"}, password="newpass")
        self.assertEqual(keyring.get_password("acct-test"), "newpass")

    def test_delete_clears_keyring_and_settings(self):
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"}, password="hunter2")
        self.svc.m_delete_sip_account()
        self.assertIsNone(self.svc.m_sip_account())
        self.assertIsNone(keyring.get_password("acct-test"))

    def test_username_with_at_is_split_into_domain(self):
        self.svc.m_save_sip_account({"username": "jane@pbx.example.org"}, password="hunter2")
        acc = self.svc.m_sip_account()
        self.assertEqual((acc["username"], acc["domain"]), ("jane", "pbx.example.org"))

    def test_password_never_reaches_settings_or_state_json(self):
        self.svc.m_save_sip_account({"username": "jane", "domain": "pbx.example.org"}, password="hunter2-secret")
        blob = json.dumps(self.svc.m_settings()) + json.dumps(self.svc.m_state())
        self.assertNotIn("hunter2-secret", blob)

    def test_generic_set_refuses_sip_account(self):
        with self.assertRaises(ValueError):
            self.svc.m_set("sip_account", {"username": "sneaky"})


if __name__ == "__main__":
    unittest.main()
