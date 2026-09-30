"""AudioRouter: PipeWire sink classification/parsing, route switching, and the audio policy
CallManager drives on incoming/answered/ended calls.

Never touches a real PipeWire: `classify`/`parse_routes` are pure functions tested against
canned pw-dump-shaped fixtures, and AudioRouter's own subprocess calls are swapped out for a
recording fake. OMARCHY_PHONE_AUDIO_DRYRUN=1 additionally keeps AudioRouter from ever invoking
`wpctl set-default` for real, same belt-and-suspenders as test_accounts.py.
"""
import json
import os
import subprocess
import tempfile
import unittest

os.environ["OMARCHY_PHONE_NO_LIBPHONENUMBER"] = "1"
os.environ["OMARCHY_PHONE_QUIET"] = "1"
os.environ["OMARCHY_PHONE_AUDIO_DRYRUN"] = "1"
os.environ["OMARCHY_PHONE_NO_NOTIFY"] = "1"
os.environ.setdefault("OMARCHY_PHONE_NO_UI_LAUNCH", "1")

import omarchy_phone.audio as audio_mod  # noqa: E402
from omarchy_phone.audio import AudioRouter, classify, parse_routes  # noqa: E402
from omarchy_phone.backends.loopback import LoopbackBackend  # noqa: E402
from omarchy_phone.calls import CallManager  # noqa: E402
from omarchy_phone.daemon import PhoneService  # noqa: E402
from omarchy_phone.store import Store  # noqa: E402


def node(id, name, desc="", api=None):
    props = {"node.name": name, "node.description": desc, "media.class": "Audio/Sink"}
    if api:
        props["device.api"] = api
    return {"type": "PipeWire:Interface:Node", "id": id, "info": {"props": props}}


def meta(default_name, as_json=False):
    value = json.dumps({"name": default_name}) if as_json else {"name": default_name}
    return {"type": "PipeWire:Interface:Metadata", "metadata": [{"key": "default.audio.sink", "value": value}]}


def dump_json(*objs):
    return json.dumps(list(objs))


class Classify(unittest.TestCase):
    def test_bluetooth_by_device_api(self):
        self.assertEqual(classify({"info": {"props": {"device.api": "bluez5", "node.name": "x"}}}), "bluetooth")

    def test_bluetooth_by_name_prefix(self):
        self.assertEqual(classify({"info": {"props": {"node.name": "bluez_output.AA_BB.a2dp-sink"}}}), "bluetooth")

    def test_earpiece_by_name(self):
        self.assertEqual(classify({"info": {"props": {"node.name": "earpiece-sink"}}}), "earpiece")

    def test_earpiece_by_handset_description(self):
        self.assertEqual(
            classify({"info": {"props": {"node.name": "x", "node.description": "Built-in Handset"}}}), "earpiece")

    def test_headset_by_description(self):
        self.assertEqual(
            classify({"info": {"props": {"node.name": "x", "node.description": "USB Headset"}}}), "headset")

    def test_headset_by_headphones_name(self):
        self.assertEqual(classify({"info": {"props": {"node.name": "analog-headphones"}}}), "headset")

    def test_headset_falls_back_to_nick_when_no_description(self):
        self.assertEqual(classify({"info": {"props": {"node.name": "x", "node.nick": "Headset Mic"}}}), "headset")

    def test_unrecognized_sink_falls_back_to_speaker(self):
        self.assertEqual(classify({"info": {"props": {"node.name": "alsa_output.builtin-speaker"}}}), "speaker")

    def test_missing_props_falls_back_to_speaker(self):
        self.assertEqual(classify({"info": {}}), "speaker")


class ParseRoutes(unittest.TestCase):
    def test_default_flagged_and_kinds_assigned(self):
        dump = [meta("alsa_output.speaker"),
                node(1, "alsa_output.speaker", "Built-in Audio"),
                node(2, "bluez_output.AA_BB", api="bluez5")]
        routes, default = parse_routes(dump)
        self.assertEqual(default, "alsa_output.speaker")
        by_id = {r["id"]: r for r in routes}
        self.assertTrue(by_id[1]["default"])
        self.assertFalse(by_id[2]["default"])
        self.assertEqual(by_id[2]["kind"], "bluetooth")
        self.assertEqual(by_id[1]["label"], "Built-in Audio")

    def test_default_value_as_json_string(self):
        dump = [meta("alsa_output.speaker", as_json=True), node(1, "alsa_output.speaker")]
        routes, default = parse_routes(dump)
        self.assertEqual(default, "alsa_output.speaker")
        self.assertTrue(routes[0]["default"])

    def test_no_metadata_means_no_default(self):
        routes, default = parse_routes([node(1, "alsa_output.speaker")])
        self.assertIsNone(default)
        self.assertFalse(routes[0]["default"])

    def test_non_sink_nodes_are_ignored(self):
        source = {"type": "PipeWire:Interface:Node", "id": 9,
                  "info": {"props": {"media.class": "Audio/Source", "node.name": "mic"}}}
        routes, _ = parse_routes([source])
        self.assertEqual(routes, [])

    def test_label_prefers_description_over_name(self):
        routes, _ = parse_routes([node(1, "alsa_output.x", "Built-in Speaker")])
        self.assertEqual(routes[0]["label"], "Built-in Speaker")

    def test_label_falls_back_to_name_when_no_description(self):
        routes, _ = parse_routes([node(1, "alsa_output.x")])
        self.assertEqual(routes[0]["label"], "alsa_output.x")


class FakeRun:
    """Stands in for subprocess.run inside omarchy_phone.audio: records every command, and answers
    `pw-dump` with canned JSON so AudioRouter.routes() never shells out for real."""

    def __init__(self, dump):
        self.dump = dump
        self.commands: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        if cmd[0] == "pw-dump":
            return type("Completed", (), {"stdout": self.dump})()
        return type("Completed", (), {"stdout": ""})()


class RouterSwitching(unittest.TestCase):
    """set_route/route_kind/restore against a fake pw-dump of speaker + earpiece + bluetooth sinks."""

    def setUp(self):
        self.fake = FakeRun(dump_json(meta("alsa_output.speaker"),
                                     node(1, "alsa_output.speaker", "Built-in Speaker"),
                                     node(2, "alsa_output.earpiece", "Earpiece"),
                                     node(3, "bluez_output.hs", api="bluez5")))
        self._orig_run = audio_mod.subprocess.run
        audio_mod.subprocess.run = self.fake
        self.addCleanup(setattr, audio_mod.subprocess, "run", self._orig_run)

    def wpctl_calls(self):
        return [c for c in self.fake.commands if c[0] == "wpctl"]

    def test_routes_reflects_pw_dump_and_default(self):
        router = AudioRouter(dry_run=True)
        routes = router.routes()
        self.assertEqual([(r["id"], r["kind"]) for r in routes],
                         [(1, "speaker"), (2, "earpiece"), (3, "bluetooth")])
        self.assertTrue(next(r for r in routes if r["id"] == 1)["default"])

    def test_dry_run_switches_state_without_shelling_to_wpctl(self):
        router = AudioRouter(dry_run=True)
        target = router.set_route(2)
        self.assertEqual(target["kind"], "earpiece")
        self.assertEqual(router.current["id"], 2)
        self.assertEqual(router.saved, "1")           # remembers the previously-default route's id
        self.assertEqual(self.wpctl_calls(), [])

    def test_live_set_route_invokes_wpctl_set_default(self):
        router = AudioRouter(dry_run=False)
        router.set_route(3)
        self.assertIn(["wpctl", "set-default", "3"], self.fake.commands)

    def test_route_kind_selects_matching_sink(self):
        router = AudioRouter(dry_run=True)
        target = router.route_kind("bluetooth")
        self.assertEqual(target["id"], 3)
        self.assertEqual(router.current["kind"], "bluetooth")

    def test_route_kind_returns_none_when_no_such_kind_present(self):
        router = AudioRouter(dry_run=True)
        self.assertIsNone(router.route_kind("headset"))

    def test_set_route_unknown_id_raises(self):
        router = AudioRouter(dry_run=True)
        with self.assertRaises(ValueError):
            router.set_route(999)

    def test_set_route_only_remembers_the_original_default_once(self):
        router = AudioRouter(dry_run=True)
        router.set_route(2)                            # earpiece; saves "1"
        router.set_route(3)                             # bluetooth; "1" must still be what gets restored
        self.assertEqual(router.saved, "1")

    def test_restore_returns_to_saved_default_and_clears_state(self):
        router = AudioRouter(dry_run=False)
        router.set_route(2)
        router.restore()
        self.assertIn(["wpctl", "set-default", "1"], self.fake.commands)
        self.assertIsNone(router.saved)
        self.assertIsNone(router.current)

    def test_restore_without_a_prior_switch_is_a_no_op(self):
        router = AudioRouter(dry_run=False)
        router.restore()
        self.assertEqual(self.wpctl_calls(), [])

    def test_dry_run_restore_never_shells_to_wpctl(self):
        router = AudioRouter(dry_run=True)
        router.set_route(2)
        router.restore()
        self.assertEqual(self.wpctl_calls(), [])


class RouterErrorPaths(unittest.TestCase):
    """routes() must degrade to an empty list rather than raise when pw-dump is unusable."""

    def tearDown(self):
        audio_mod.subprocess.run = self._orig

    def setUp(self):
        self._orig = audio_mod.subprocess.run

    def test_missing_pw_dump_binary_yields_no_routes(self):
        def raise_missing(cmd, **kwargs):
            raise FileNotFoundError("no such file: pw-dump")
        audio_mod.subprocess.run = raise_missing
        self.assertEqual(AudioRouter(dry_run=True).routes(), [])

    def test_pw_dump_timeout_yields_no_routes(self):
        def raise_timeout(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=3)
        audio_mod.subprocess.run = raise_timeout
        self.assertEqual(AudioRouter(dry_run=True).routes(), [])

    def test_malformed_json_yields_no_routes(self):
        audio_mod.subprocess.run = lambda cmd, **kwargs: type("Completed", (), {"stdout": "not json"})()
        self.assertEqual(AudioRouter(dry_run=True).routes(), [])

    def test_empty_output_yields_no_routes(self):
        audio_mod.subprocess.run = lambda cmd, **kwargs: type("Completed", (), {"stdout": ""})()
        self.assertEqual(AudioRouter(dry_run=True).routes(), [])


class DryRunDefaultFromEnvironment(unittest.TestCase):
    def test_env_var_is_the_default_when_not_passed_explicitly(self):
        self.assertTrue(AudioRouter().dry_run)   # OMARCHY_PHONE_AUDIO_DRYRUN=1 set at module load

    def test_explicit_argument_overrides_the_environment(self):
        self.assertFalse(AudioRouter(dry_run=False).dry_run)


class FakeAudio:
    """Records the audio-policy decisions CallManager makes, without touching PipeWire."""

    def __init__(self):
        self.ring_calls: list[bool] = []
        self.restored = False
        self.route_kind_calls: list[str] = []
        self.set_route_calls: list[int] = []
        self.by_kind = {"speaker": {"id": 1, "kind": "speaker"}, "earpiece": {"id": 2, "kind": "earpiece"}}
        self.by_id = {1: {"id": 1, "kind": "speaker"}, 2: {"id": 2, "kind": "earpiece"}}

    def ring(self, on):
        self.ring_calls.append(on)

    def route_kind(self, kind):
        self.route_kind_calls.append(kind)
        return self.by_kind.get(kind)

    def set_route(self, route_id):
        self.set_route_calls.append(route_id)
        return self.by_id.get(route_id, {"id": route_id, "kind": "earpiece"})

    def restore(self):
        self.restored = True


class CallAudioPolicy(unittest.TestCase):
    """CallManager's use of AudioRouter across the call lifecycle: ring on incoming, silence on
    answer, restore on hangup, and route switching via set_speaker/set_route. simulate_incoming
    and hangup on the loopback backend both emit synchronously, so no GLib spin is needed here."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "p.db"))
        self.store.set("own_number", "+12125550100")
        self.audio = FakeAudio()
        self.events = []
        self.backend = LoopbackBackend({"profile": "audio-test", "number": "+12125550100",
                                        "dir": os.path.join(self.tmp.name, "reg")})
        self.mgr = CallManager(self.store, [self.backend], audio=self.audio, emit=self.events.append)
        self.addCleanup(self.mgr.stop)
        self.addCleanup(self.store.close)
        self.addCleanup(self.tmp.cleanup)

    def test_incoming_call_rings(self):
        self.mgr.simulate_incoming("+13125550177")
        self.assertEqual(self.audio.ring_calls, [True])

    def test_answering_silences_the_ringtone(self):
        cid = self.mgr.simulate_incoming("+13125550177")
        self.mgr.answer(cid)
        self.assertEqual(self.audio.ring_calls, [True, False])

    def test_silenced_incoming_call_never_rings(self):
        self.store.set("unknown_action", "silent")
        self.mgr.simulate_incoming("+13125550177")
        self.assertEqual(self.audio.ring_calls, [])

    def test_second_incoming_call_while_busy_does_not_ring_again(self):
        first = self.mgr.simulate_incoming("+13125550177")
        self.mgr.answer(first)
        self.mgr.simulate_incoming("+13125550188")
        self.assertEqual(self.audio.ring_calls, [True, False])   # no second True

    def test_declined_unanswered_call_stops_ringing_and_restores(self):
        cid = self.mgr.simulate_incoming("+13125550177")
        self.mgr.decline(cid)
        self.assertEqual(self.audio.ring_calls, [True, False])
        self.assertTrue(self.audio.restored)

    def test_hangup_after_answer_restores_but_does_not_ring_again(self):
        cid = self.mgr.simulate_incoming("+13125550177")
        self.mgr.answer(cid)
        self.mgr.hangup(cid)
        self.assertEqual(self.audio.ring_calls, [True, False])   # hangup adds no extra ring() call
        self.assertTrue(self.audio.restored)

    def test_restore_only_fires_once_the_last_call_ends(self):
        first = self.mgr.simulate_incoming("+13125550177")
        self.mgr.answer(first)
        second = self.mgr.simulate_incoming("+13125550188")
        self.mgr.decline(second)
        self.assertFalse(self.audio.restored)            # first call is still live
        self.mgr.hangup(first)
        self.assertTrue(self.audio.restored)

    def test_set_speaker_true_routes_to_speaker_and_updates_flag(self):
        route = self.mgr.set_speaker(True)
        self.assertEqual(self.audio.route_kind_calls, ["speaker"])
        self.assertEqual(route["kind"], "speaker")
        self.assertTrue(self.mgr.speaker)
        self.assertEqual(self.events[-1], {"type": "audio", "speaker": True, "route": route})

    def test_set_speaker_false_routes_to_earpiece_and_updates_flag(self):
        self.mgr.set_speaker(True)
        route = self.mgr.set_speaker(False)
        self.assertEqual(self.audio.route_kind_calls, ["speaker", "earpiece"])
        self.assertEqual(route["kind"], "earpiece")
        self.assertFalse(self.mgr.speaker)

    def test_set_route_by_id_updates_speaker_flag_from_the_resulting_kind(self):
        route = self.mgr.set_route(1)   # speaker
        self.assertEqual(self.audio.set_route_calls, [1])
        self.assertEqual(route["kind"], "speaker")
        self.assertTrue(self.mgr.speaker)
        route2 = self.mgr.set_route(2)  # earpiece
        self.assertFalse(self.mgr.speaker)
        self.assertEqual(self.events[-1], {"type": "audio", "speaker": False, "route": route2})


class DaemonAudioWiring(unittest.TestCase):
    """m_routes/m_route on PhoneService delegate to the real AudioRouter, with pw-dump faked out
    so this never touches actual PipeWire hardware."""

    def setUp(self):
        self.fake = FakeRun(dump_json(meta("alsa_output.speaker"),
                                     node(1, "alsa_output.speaker", "Built-in Speaker"),
                                     node(2, "alsa_output.earpiece", "Earpiece")))
        self._orig_run = audio_mod.subprocess.run
        audio_mod.subprocess.run = self.fake
        self.addCleanup(setattr, audio_mod.subprocess, "run", self._orig_run)
        self.tmp = tempfile.TemporaryDirectory()
        old_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.tmp.name
        self.addCleanup(lambda: os.environ.update(XDG_DATA_HOME=old_xdg) if old_xdg is not None
                        else os.environ.pop("XDG_DATA_HOME", None))
        self.svc = PhoneService(profile="audio-daemon-test")
        self.addCleanup(self.svc.shutdown)
        self.addCleanup(self.tmp.cleanup)

    def test_m_routes_lists_pipewire_sinks(self):
        routes = self.svc.m_routes()
        self.assertEqual([r["kind"] for r in routes], ["speaker", "earpiece"])

    def test_m_route_switches_and_is_reflected_in_m_routes(self):
        result = self.svc.m_route(2)
        self.assertEqual(result["kind"], "earpiece")
        self.assertEqual(self.svc.audio.current["id"], 2)
        by_id = {r["id"]: r for r in self.svc.m_routes()}
        self.assertTrue(by_id[2]["default"])
        self.assertFalse(by_id[1]["default"])   # no longer the one wpctl would report as default


class SilentModeAndRing(unittest.TestCase):
    """The ring/silent switch file and the ringtone loop's quiet/silent no-op paths. Real subprocess
    Popen is never exercised here: OMARCHY_PHONE_QUIET=1 (set at module load, same as every other
    test in this suite) makes AudioRouter.ring(True) a no-op before it would ever spawn `pw-play`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp.name
        self.addCleanup(self._restore_xdg)
        self.addCleanup(self.tmp.cleanup)

    def _restore_xdg(self):
        if self._orig_xdg is not None:
            os.environ["XDG_RUNTIME_DIR"] = self._orig_xdg
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)

    def _write_silent(self, value):
        d = os.path.join(self.tmp.name, "omarchy-phone")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "silent"), "w") as f:
            f.write(value)

    def test_silent_mode_on(self):
        self._write_silent("on")
        self.assertTrue(AudioRouter.silent_mode())

    def test_silent_mode_off(self):
        self._write_silent("off")
        self.assertFalse(AudioRouter.silent_mode())

    def test_silent_mode_defaults_false_when_the_switch_file_is_missing(self):
        self.assertFalse(AudioRouter.silent_mode())

    def test_ring_true_is_a_noop_under_the_quiet_env_var(self):
        router = AudioRouter(dry_run=True)
        router.ring(True)
        self.assertIsNone(router._ring)

    def test_ring_true_is_skipped_when_silent_mode_is_on(self):
        self._write_silent("on")
        router = AudioRouter(dry_run=True)
        router.ring(True)
        self.assertIsNone(router._ring)

    def test_ring_false_with_nothing_ringing_is_a_noop(self):
        router = AudioRouter(dry_run=True)
        router.ring(False)   # must not raise even though _ring is already None
        self.assertIsNone(router._ring)


if __name__ == "__main__":
    unittest.main()
