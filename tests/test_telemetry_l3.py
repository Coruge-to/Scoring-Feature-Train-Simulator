"""Phase L3 tests: the telemetry data contract (AVAIL), the generation-aware telemetry gate, the HUD that waits for real telemetry, and the per-item
visibility. Standard library + (for layer D) the real Overlay offscreen.

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_telemetry_l3.py" -v

Layers: (A) the contract (AVAIL format, vocabulary, HUD item mapping); (B) the gate, pure (normal mode, strict mode, generations, stale / ahead /
held, diagnostics only on change); (C) the HUD controller against fake Overlay / timer / window API; (D) the real Overlay (offscreen, only when UDP
54321 is free): the existing Current line still works unchanged, an AVAIL line from a Legacy-like sender draws only what it provides, a new scenario
instance leaves no old value behind; (E) static guards (what Phase L3 may touch).
No BVE, no BveEX, no Caller is started; nothing outside a temp directory is written.
"""
import ast
import importlib.util
import os
import re
import socket
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import telemetry_contract as tc  # noqa: E402
import telemetry_gate as tg  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402  (fakes of the E4 suite: block builder, fake source / overlay / timer / window API)

HAS_QT = importlib.util.find_spec("PyQt6") is not None


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# a full line of the CURRENT sender, in the format Class1.cs has always written (no AVAIL)
CURRENT_FULL = ("SCENARIO_ID:{sid},SPEED:45.5,TIME:36000000,LOCATION:1234.5,GRADIENT:10,NEXTLOC:2000,NEXTTIME:36100000,ISPASS:0,ISTIMING:1,"
                "MARGINB:5,MARGINF:5,REV:前:1,POW:P3:3,BRK:N:0:8,HTYPE:2,ALLTXT:切_N_前:N_P1_P2_P3:N_B1_B2_B3_B4_B5_B6_B7_EB:,SIGLIMIT:1000,"
                "TRAINLEN:80,MAPLIMITS:,FWDSIGLIMIT:1000,FWDSIGLOC:-1,DOOR:0,DOORDIR:1,TERM:0,MAPHEAD:1000,MAPTAIL:1000,CLEARDIST:0,"
                "CALCG:0.00000,BTYPE:Ecb,JUMP:0,CAB:8:0,BCP:0.0,PRATES:0_0.1_0.2_0.3_0.4_0.5_0.6_0.7_1:440.0,BPP:0.0:490.0,STATNAME:駅A,DOORTIME:4630")
# the tokens a Legacy sender can provide (see Docs\Handshake-PhaseL3-LegacyTelemetry.md)
LEGACY_TOKENS = ("time", "speed", "loc", "grad", "station", "door", "siglimit", "siglimit_ahead", "maplimit", "brake_type", "brake_cab", "prates", "calcg",
                 "meta")
LEGACY_LINE = ("SCENARIO_ID:{sid},AVAIL:1:" + "+".join(sorted(LEGACY_TOKENS)) + ",SPEED:30.5,TIME:36000000,LOCATION:1000.5,GRADIENT:-12.5,NEXTLOC:2500,"
               "NEXTTIME:36200000,ISPASS:0,ISTIMING:0,MARGINB:5,MARGINF:5,SIGLIMIT:90,FWDSIGLIMIT:1000,FWDSIGLOC:-1,DOOR:0,DOORDIR:1,TERM:0,"
               "MAPHEAD:70,MAPTAIL:70,CALCG:0.00100,BTYPE:Smee,CAB:5:0,PRATES:0_0.2_0.4_0.6_0.8_1:490.0,STATNAME:駅B")


def current_line(sid):
    return CURRENT_FULL.format(sid=sid)


def legacy_line(sid):
    return LEGACY_LINE.format(sid=sid)


def core_line(sid, avail=None, extra=""):
    avail_part = ",AVAIL:" + avail if avail is not None else ""
    return "SCENARIO_ID:%d%s,SPEED:10.0,TIME:1000,LOCATION:5.0%s" % (sid, avail_part, extra)


# ---------------------------------------------------------------------------------------------------------------------------------------
class A_Contract(unittest.TestCase):
    def test_format_and_parse_roundtrip(self):
        text = tc.format_avail(["speed", "time"])
        self.assertEqual(text, "AVAIL:1:speed+time")                       # sorted: deterministic
        line = tc.parse_telemetry(core_line(7, "1:speed+time"))
        self.assertTrue(line.valid)
        self.assertEqual((line.scenario_id, line.avail_status, line.tokens), (7, tc.AVAIL_OK, frozenset({"speed", "time"})))

    def test_no_avail_means_everything_is_available(self):
        line = tc.parse_telemetry(current_line(5))
        self.assertTrue(line.valid)
        self.assertEqual(line.avail_status, tc.AVAIL_ABSENT)
        a = line.availability
        self.assertFalse(a.explicit)
        for item in tc.HUD_ITEM_REQUIRES:
            self.assertTrue(a.item(item), item)
        for token in tc.KNOWN_TOKENS:
            self.assertTrue(a.has(token), token)

    def test_unknown_tokens_are_ignored_and_counted(self):
        line = tc.parse_telemetry(core_line(1, "1:speed+futuretoken+time+another_one"))
        self.assertTrue(line.valid)
        self.assertEqual(line.tokens, frozenset({"speed", "time"}))
        self.assertEqual(line.unknown_tokens, 2)

    def test_bad_token_text_is_ignored_not_an_error(self):
        line = tc.parse_telemetry(core_line(1, "1:speed+Bad-Token+time+9x"))
        self.assertTrue(line.valid)
        self.assertEqual((line.tokens, line.bad_tokens), (frozenset({"speed", "time"}), 2))

    def test_unsupported_version_is_not_interpreted(self):
        for version in ("2", "0", "99"):
            line = tc.parse_telemetry(core_line(1, version + ":speed+time"))
            self.assertFalse(line.valid, version)
            self.assertEqual(line.reason, tc.AVAIL_UNSUPPORTED)

    def test_malformed_avail_is_not_trusted(self):
        for body in ("", "x:speed", "1", "abc"):
            line = tc.parse_telemetry(core_line(1, body))
            self.assertFalse(line.valid, body)
            self.assertEqual(line.reason, tc.AVAIL_MALFORMED)
        too_many = "1:" + "+".join("t%d" % i for i in range(tc.MAX_TOKENS + 1))
        self.assertEqual(tc.parse_telemetry(core_line(1, too_many)).reason, tc.AVAIL_MALFORMED)

    def test_empty_token_list_is_valid_and_means_nothing_optional(self):
        line = tc.parse_telemetry(core_line(1, "1:"))
        self.assertTrue(line.valid)
        self.assertEqual(line.tokens, frozenset())
        for item in tc.HUD_ITEM_REQUIRES:
            self.assertFalse(line.availability.item(item), item)

    def test_required_keys(self):
        good = core_line(3)
        self.assertTrue(tc.parse_telemetry(good).valid)
        for key in tc.REQUIRED_KEYS:
            broken = ",".join(p for p in good.split(",") if not p.startswith(key + ":"))
            line = tc.parse_telemetry(broken)
            self.assertFalse(line.valid, key)
            self.assertTrue(line.reason.startswith("missing-"), line.reason)
        for bad in ("SCENARIO_ID:x,SPEED:1,TIME:1,LOCATION:1", "SCENARIO_ID:1,SPEED:nan,TIME:1,LOCATION:1", "SCENARIO_ID:1,SPEED:1,TIME:1.5,LOCATION:1",
                    "SCENARIO_ID:1,SPEED:1,TIME:1,LOCATION:inf", "SCENARIO_ID:1,SPEED:,TIME:1,LOCATION:1"):
            line = tc.parse_telemetry(bad)
            self.assertFalse(line.valid, bad)
            self.assertEqual(line.reason, "malformed-required")

    def test_parse_never_raises(self):
        for text in ("", ",,,", "AVAIL:", "AVAIL:::", "\x00\xff", "SCENARIO_ID:", "A" * 100000, None, 5):
            line = tc.parse_telemetry(text)
            self.assertFalse(line.valid)

    def test_vocabulary_covers_every_key_the_current_sender_writes(self):
        src = read_text(os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "Class1.cs"))
        data = src[src.index('string data = $"') :]
        data = data[: data.index("\n")]
        keys = set(re.findall(r"(?:^|,|\")([A-Z_]+):\{", data[data.index('"') :]))
        keys |= {"SCENARIO_ID"}
        covered = {k for ks in tc.TOKEN_KEYS.values() for k in ks} | {"SCENARIO_ID"}
        self.assertEqual(keys - covered, set(), "keys of the Current line that no token covers")
        # the non-line datagrams are covered too
        self.assertTrue({"STALIST", "META", "JUMP_COMPLETE"} <= covered)

    def test_every_token_is_well_formed_and_known_to_the_hud_map(self):
        for t in tc.KNOWN_TOKENS:
            self.assertRegex(t, r"^[a-z][a-z0-9_]{0,31}$")
        for item, needs in tc.HUD_ITEM_REQUIRES.items():
            self.assertTrue(set(needs) <= tc.KNOWN_TOKENS, item)

    def test_hud_items_are_exactly_the_overlay_switches(self):
        tree = ast.parse(read_text(os.path.join(ROOT, "main.py")))
        overlay = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        init = next(n for n in overlay.body if getattr(n, "name", "") == "__init__")
        switches = None
        for node in ast.walk(init):
            if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "self.disp_settings":
                switches = {k.value for k in node.value.keys}
        self.assertEqual(switches, set(tc.HUD_ITEM_REQUIRES))

    def test_legacy_token_set_matches_the_audit_decision(self):
        a = tc.Availability(LEGACY_TOKENS)
        for item in ("time", "time_left", "speed", "limit", "dist", "grad"):
            self.assertTrue(a.item(item), item)
        self.assertFalse(a.item("handle"))                          # REV / POW / BRK / ALLTXT texts do not exist on Legacy
        for token in ("handle", "bcp", "bpp", "maplimit_ahead", "jump", "trainlen", "doortime"):
            self.assertFalse(a.has(token), token)

    def test_telemetry_state_defaults_are_fresh_objects(self):
        a, b = tc.telemetry_state_defaults(), tc.telemetry_state_defaults()
        self.assertEqual(a, b)
        a["bve_map_limits"].append((1.0, 2.0))
        self.assertEqual(b["bve_map_limits"], [])


# ---------------------------------------------------------------------------------------------------------------------------------------
class Events(object):
    def __init__(self):
        self.items = []

    def __call__(self, event, **fields):
        self.items.append((event, fields))

    def names(self):
        return [e for e, _ in self.items]


class B_Gate(unittest.TestCase):
    def strict(self):
        ev = Events()
        return tg.TelemetryGate(strict=True, log=ev), ev

    # -- normal mode ---------------------------------------------------------------------------------------------------------------------
    def test_normal_mode_accepts_everything_and_only_follows_avail(self):
        g = tg.TelemetryGate(strict=False)
        self.assertTrue(g.ready)
        for text in ("garbage", "", current_line(1), legacy_line(2), "SPEED:1"):
            self.assertTrue(g.accept(text))
        self.assertTrue(g.ready)
        self.assertEqual(g.stale + g.invalid + g.ahead_lines, 0)
        self.assertFalse(g.consume_epoch_reset())                    # normal mode never resets anything

    def test_normal_mode_follows_the_avail_of_the_latest_line(self):
        g = tg.TelemetryGate(strict=False)
        g.accept(current_line(1))
        self.assertFalse(g.availability.explicit)
        g.accept(legacy_line(2))
        self.assertEqual(g.availability, tc.Availability(LEGACY_TOKENS))
        self.assertFalse(g.availability.item("handle"))
        g.accept(current_line(3))                                     # a sender without AVAIL again: everything
        self.assertTrue(g.availability.item("handle"))

    def test_normal_mode_ignores_a_bad_avail_part(self):
        g = tg.TelemetryGate(strict=False)
        g.accept(legacy_line(1))
        g.accept(core_line(1, "9:speed"))                              # unsupported version: availability is not changed by it
        self.assertEqual(g.availability, tc.Availability(LEGACY_TOKENS))

    # -- strict mode: start --------------------------------------------------------------------------------------------------------------
    def test_not_ready_before_the_first_telemetry(self):
        g, ev = self.strict()
        self.assertFalse(g.ready)
        self.assertEqual(g.wait_reason, "no-telemetry-for-generation")
        self.assertIsNone(g.on_generation(1))
        self.assertFalse(g.ready)

    def test_ready_after_the_first_valid_line(self):
        g, ev = self.strict()
        g.on_generation(1)
        self.assertTrue(g.accept(current_line(100)))
        self.assertTrue(g.ready)
        self.assertIsNone(g.wait_reason)
        self.assertTrue(g.consume_epoch_reset())                       # the first scenario instance starts from the defaults
        self.assertFalse(g.consume_epoch_reset())                      # once

    def test_invalid_lines_never_make_it_ready(self):
        g, ev = self.strict()
        g.on_generation(1)
        for text in ("", "STATUS", "SCENARIO_ID:1", core_line(1, "5:x"), core_line(1, "bad"), "SPEED:1,TIME:1"):
            self.assertFalse(g.accept(text), text)
        self.assertFalse(g.ready)
        self.assertEqual(g.invalid, 6)

    def test_ready_before_the_first_generation_is_reported_is_still_possible(self):
        # telemetry can arrive before the first state reading changes the generation from 0 (the Caller publishes generation >= 1 only later)
        g, ev = self.strict()
        self.assertTrue(g.accept(current_line(5)))
        self.assertTrue(g.ready)
        g.on_generation(1)                                             # the generation then arrives: the data is retired (it cannot be told to belong)
        self.assertFalse(g.ready)

    # -- strict mode: generations --------------------------------------------------------------------------------------------------------
    def test_a_generation_change_retires_the_data_until_new_telemetry(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        self.assertTrue(g.ready)
        self.assertIsNone(g.on_generation(2))
        self.assertFalse(g.ready)
        self.assertEqual(g.availability, tc.ALL_AVAILABLE)             # nothing of the old data is carried over
        self.assertFalse(g.accept(current_line(10)))                   # a late packet of the old scenario instance
        self.assertFalse(g.ready)
        self.assertEqual(g.stale, 1)
        self.assertTrue(g.accept(current_line(11)))
        self.assertTrue(g.ready)
        self.assertTrue(g.consume_epoch_reset())

    def test_old_generation_packets_are_ignored_even_after_new_ones_arrived(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        g.on_generation(2)
        g.accept(current_line(11))
        for _ in range(5):
            self.assertFalse(g.accept(current_line(10)))
        self.assertTrue(g.accept(current_line(11)))
        self.assertEqual(g.stale, 5)
        self.assertTrue(g.ready)

    def test_ordering_is_by_first_appearance_not_by_value(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(900))
        g.on_generation(2)
        self.assertTrue(g.accept(current_line(5)))                     # a smaller number is a NEW instance, not an old one
        g.on_generation(3)
        self.assertTrue(g.accept(current_line(7)))
        self.assertFalse(g.accept(current_line(5)))
        self.assertFalse(g.accept(current_line(900)))

    def test_the_sender_moving_ahead_of_the_caller_hides_and_holds(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        self.assertTrue(g.ready)
        self.assertFalse(g.accept(current_line(11)))                   # the sender started the next scenario before the generation changed
        self.assertFalse(g.ready)
        self.assertEqual(g.wait_reason, "sender-ahead")
        self.assertFalse(g.accept(current_line(10)))                   # and a late packet of the old one is stale
        self.assertFalse(g.ready)
        held = g.on_generation(2)
        self.assertEqual(held, current_line(11))                       # the newest datagram of the new scenario is handed over to be applied
        self.assertTrue(g.ready)
        self.assertTrue(g.consume_epoch_reset())
        self.assertTrue(g.accept(current_line(11)))

    def test_only_the_newest_ahead_datagram_is_held(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        for sid, text in ((11, "a"), (11, "b")):
            g.accept(current_line(sid) + ",X:" + text)
        self.assertTrue(g.has_held)
        self.assertTrue(g.on_generation(2).endswith("X:b"))
        self.assertFalse(g.has_held)

    def test_without_a_held_datagram_the_generation_change_returns_nothing(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        self.assertIsNone(g.on_generation(2))

    def test_the_same_generation_again_changes_nothing(self):
        g, ev = self.strict()
        g.on_generation(4)
        g.accept(current_line(10))
        self.assertIsNone(g.on_generation(4))
        self.assertTrue(g.ready)
        self.assertEqual(ev.names().count("telemetry-generation"), 1)

    def test_telemetry_that_stops_stays_valid_for_the_generation(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        self.assertTrue(g.ready)                                          # no clock and no threshold exist in the gate: a pause is not a loss

    def test_first_epoch_reset_only_when_the_instance_changes(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        g.consume_epoch_reset()
        for _ in range(10):
            g.accept(current_line(10))
        self.assertFalse(g.consume_epoch_reset())
        g.on_generation(2)
        g.accept(current_line(11))
        self.assertTrue(g.consume_epoch_reset())

    def test_remembered_epochs_are_bounded(self):
        g, ev = self.strict()
        for gen in range(1, 300):
            g.on_generation(gen)
            self.assertTrue(g.accept(current_line(gen + 1000)))
        self.assertLessEqual(len(g._seen), tg.MAX_REMEMBERED_EPOCHS)
        self.assertLessEqual(len(g._retired), tg.MAX_REMEMBERED_EPOCHS)

    # -- availability --------------------------------------------------------------------------------------------------------------------
    def test_strict_mode_availability_follows_the_bound_line(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(legacy_line(10))
        self.assertEqual(g.availability, tc.Availability(LEGACY_TOKENS))
        self.assertFalse(g.availability.item("handle"))
        self.assertTrue(g.availability.item("speed"))

    def test_availability_can_be_updated_inside_a_scenario(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(core_line(10, "1:speed+time+loc+grad"))
        self.assertTrue(g.availability.item("grad"))
        g.accept(core_line(10, "1:speed+time+loc"))                    # a vehicle change or a failed read: the next line says so
        self.assertFalse(g.availability.item("grad"))
        self.assertEqual(g.avail_changes, 1)

    def test_availability_of_a_new_scenario_replaces_the_old_one(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(legacy_line(10))
        g.on_generation(2)
        g.accept(current_line(11))                                      # a reload with a sender that does not announce: everything again
        self.assertEqual(g.availability, tc.ALL_AVAILABLE)

    def test_unknown_tokens_are_safe(self):
        g, ev = self.strict()
        g.on_generation(1)
        self.assertTrue(g.accept(core_line(10, "1:speed+time+loc+grad+station+siglimit+maplimit+quantum_hud")))
        self.assertTrue(g.availability.item("speed"))
        self.assertEqual(g.unknown_tokens, 1)

    # -- diagnostics only on change ------------------------------------------------------------------------------------------------------
    def test_no_log_for_repeated_packets(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(legacy_line(10))
        before = len(ev.items)
        for _ in range(5000):
            g.accept(legacy_line(10))
        self.assertEqual(len(ev.items), before)
        self.assertEqual(g.accepted, 5001)

    def test_a_drop_reason_is_logged_once_per_generation_even_when_stale_and_good_datagrams_alternate(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(current_line(10))
        g.on_generation(2)
        for _ in range(1000):
            g.accept(current_line(10))
        self.assertEqual(ev.names().count("telemetry-drop"), 1)
        g.accept(current_line(11))
        for _ in range(1000):                          # alternation: good, stale, good, stale ...
            g.accept(current_line(10))
            g.accept(current_line(11))
        self.assertEqual(ev.names().count("telemetry-drop"), 1)
        g.on_generation(3)
        for _ in range(1000):
            g.accept(current_line(11))
        self.assertEqual(ev.names().count("telemetry-drop"), 2)         # a new generation may log its own episode
        self.assertEqual(g.stale, 3000)

    def test_invalid_episode_logged_once_per_reason(self):
        g, ev = self.strict()
        g.on_generation(1)
        for _ in range(100):
            g.accept("garbage")
        g.accept("SCENARIO_ID:x,SPEED:1,TIME:1,LOCATION:1")
        drops = [f["reason"] for e, f in ev.items if e == "telemetry-drop"]
        self.assertEqual(drops, ["missing-scenario-id", "malformed-required"])

    def test_log_fields_are_fixed_words_and_numbers(self):
        g, ev = self.strict()
        g.on_generation(1)
        g.accept(legacy_line(10))
        for event, fields in ev.items:
            for k, v in fields.items():
                self.assertRegex(str(v), r"^[A-Za-z0-9_\-+]+$", (event, k, v))   # a list of fixed words is joined by +

    def test_a_failing_logger_does_not_break_the_gate(self):
        def bad(event, **fields):
            raise RuntimeError("boom")
        g = tg.TelemetryGate(strict=True, log=bad)
        g.on_generation(1)
        self.assertTrue(g.accept(current_line(10)))
        self.assertTrue(g.ready)

    def test_accept_never_raises(self):
        g, ev = self.strict()
        for text in (None, 5, b"x", "\x00", "A" * 200000, "SCENARIO_ID:" + "9" * 5000 + ",SPEED:1,TIME:1,LOCATION:1"):
            try:
                g.accept(text)
            except Exception as e:        # noqa: BLE001
                self.fail("accept raised %r for %r" % (e, str(text)[:20]))


# ---------------------------------------------------------------------------------------------------------------------------------------
class OverlayWithTelemetry(e4.FakeOverlay):
    """The fake Overlay of the E4 suite + the one method the controller calls when a held datagram has to be applied."""

    def __init__(self):
        super().__init__()
        self.applied = []

    def apply_telemetry_text(self, text):
        self.applied.append(text)


class C_Controller(unittest.TestCase):
    def setUp(self):
        e4.FakeOverlay.created = 0
        self.args = e4.args_for()
        self.log = e4.Log()
        self.source = e4.FakeSource(e4.make_block(self.args.bve_pid, self.args.instance))
        self.reader = ms.StateReader(self.args, self.source, self.log)
        self.overlay = OverlayWithTelemetry()
        self.timer = e4.FakeTimer()
        self.api = e4.FakeWindowApi()
        self.clock = e4.Clock()
        self.steps = []
        self.count = 0
        self.gate = tg.TelemetryGate(strict=True)
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock, telemetry=self.gate)
        self.gate.log = self.hud.emit_event

    def publish(self, session=False, driving=False, generation=0, closed=False):
        self.count += 1
        self.source.data = e4.make_block(self.args.bve_pid, self.args.instance, session, driving, closed, generation, self.count)

    def pump(self, ticks=1):
        for _ in range(ticks):
            self.clock.t += 0.02
            self.hud.tick()

    def feed(self, text):
        return self.gate.accept(text)

    def test_session_and_driving_on_alone_do_not_show_the_hud(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(200)
        self.assertEqual(self.hud.mode, ms.MODE_ACTIVE)
        self.assertEqual((self.overlay.visible, self.overlay.shows, len(self.steps)), (False, 0, 0))
        self.assertEqual(self.api.searches, 0)                          # not even the BVE window is looked for while there is nothing to show
        self.assertEqual(self.log.events("hud-show"), [])
        self.assertEqual(self.log.events("hud-hide"), [])               # nothing was shown, so nothing is "hidden" in the log either

    def test_the_hud_appears_with_the_first_telemetry_of_the_generation(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(5)
        self.feed(legacy_line(10))
        self.pump(3)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.shows, 1)
        self.assertGreaterEqual(len(self.steps), 1)
        self.assertEqual(len(self.log.events("hud-show")), 1)
        self.assertEqual(len(self.log.events("telemetry-first")), 1)

    def test_telemetry_before_session_on_is_remembered_for_the_generation(self):
        self.hud.start()
        self.publish(False, False, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(5)
        self.assertFalse(self.overlay.visible)                          # Session OFF: hidden, whatever arrives
        self.publish(True, True, 1)
        self.pump(3)
        self.assertTrue(self.overlay.visible)

    def test_a_new_generation_hides_the_hud_until_new_telemetry(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(3)
        self.assertTrue(self.overlay.visible)
        self.publish(True, True, 2)                                      # the scenario was reloaded and the Caller already says ON again
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        steps = len(self.steps)
        self.assertFalse(self.feed(legacy_line(10)))                     # the old scenario instance
        self.pump(5)
        self.assertFalse(self.overlay.visible)
        self.assertEqual(len(self.steps), steps)                        # and nothing was updated meanwhile
        self.assertTrue(self.feed(legacy_line(11)))
        self.pump(2)
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.shows, 2)
        self.assertEqual(e4.FakeOverlay.created, 1)                      # still the one Overlay

    def test_the_hold_applies_the_new_scenario_without_another_datagram(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(2)
        self.feed(legacy_line(11))                                       # the sender is ahead (a pause may follow: no more datagrams)
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.publish(True, True, 2)
        self.pump(3)
        self.assertEqual(self.overlay.applied, [legacy_line(11)])
        self.assertTrue(self.overlay.visible)

    def test_session_off_hides_and_the_same_generation_resumes(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(3)
        self.publish(False, False, 1)
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.publish(True, True, 1)
        self.pump(3)
        self.assertTrue(self.overlay.visible)                            # same generation, same scenario instance: its data is still current
        self.assertEqual(self.overlay.shows, 2)

    def test_driving_off_then_on(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(3)
        self.publish(True, False, 1)
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.publish(True, True, 1)
        self.pump(3)
        self.assertTrue(self.overlay.visible)
        self.assertEqual((self.overlay.shows, self.overlay.hides), (2, 1))

    def test_telemetry_that_stops_does_not_hide_the_hud(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(2)
        self.pump(2000)                                                  # a long pause: no datagram, no threshold
        self.assertTrue(self.overlay.visible)
        self.assertEqual(self.overlay.hides, 0)

    def test_sender_ahead_without_a_generation_change_hides_the_hud(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(2)
        self.assertTrue(self.overlay.visible)
        self.feed(legacy_line(11))
        self.pump(2)
        self.assertFalse(self.overlay.visible)                           # the old data is no longer current; it is not shown frozen
        self.assertEqual(self.gate.wait_reason, "sender-ahead")

    def test_one_overlay_and_no_timer_of_its_own_across_a_long_sequence(self):
        self.hud.start()
        sid = 100
        for gen in range(1, 40):
            self.publish(True, True, gen)
            self.pump(2)
            sid += 1
            self.feed(legacy_line(sid))
            self.pump(3)
            self.publish(True, False, gen)
            self.pump(2)
            self.publish(False, False, gen)
            self.pump(2)
        self.assertEqual(e4.FakeOverlay.created, 1)
        self.assertEqual(self.timer.starts, 0)                           # the controller never starts a timer; it only changes the interval
        self.assertLessEqual(len(self.log.events("hud-show")), 39)

    def test_diagnostics_are_state_changes_only(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        for _ in range(3000):
            self.feed(legacy_line(10))
            self.pump(1)
        telemetry_lines = [line for line in self.log.lines if " event=telemetry-" in line]
        self.assertLessEqual(len(telemetry_lines), 3)
        for line in self.log.lines:
            self.assertNotIn("36000000", line)                           # no telemetry value is ever logged

    def test_summary_carries_the_telemetry_counters(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.feed("junk")
        self.pump(2)
        self.hud.shutdown()
        summary = self.log.events("hud-summary")[0]
        self.assertNotIn("tel_accepted", summary)                                # hud-summary is longer than the Caller transcribes: the counters have a line of their own
        counters = self.log.events("telemetry-summary")[0]
        self.assertIn("tel_accepted=1", counters)
        self.assertIn("tel_invalid=1", counters)
        self.assertLess(len(counters), 160)
    def test_telemetry_events_fit_the_callers_transcription_limit(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.feed(core_line(10, "1:time+speed"))
        self.pump(3)
        self.gate.on_generation(2)
        self.feed(legacy_line(10))
        self.hud.shutdown()
        for line in self.log.lines:
            if " event=telemetry-" in line or " event=hud-items" in line:
                self.assertLessEqual(len(line), 160, line)                        # the Caller keeps 160 characters of an application line

    def test_hud_items_are_reported_once_per_change(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(5)
        events = self.log.events("hud-items")
        self.assertEqual(len(events), 1)
        self.assertIn("unavailable=handle", events[0])
        for _ in range(500):
            self.feed(legacy_line(10))
            self.pump(1)
        self.assertEqual(len(self.log.events("hud-items")), 1)
        self.feed(core_line(10, "1:time+speed+loc"))                      # the sender announces less: the change is reported
        self.pump(2)
        events = self.log.events("hud-items")
        self.assertEqual(len(events), 2)
        self.assertIn("unavailable=dist+grad+handle+limit+time_left", events[1])

    def test_a_sender_without_avail_reports_nothing_unavailable(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(current_line(10))
        self.pump(3)
        events = self.log.events("hud-items")
        self.assertEqual(len(events), 1)
        self.assertIn("unavailable=none", events[0])

    def test_state_lost_failsafe_still_wins(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(2)
        self.feed(legacy_line(10))
        self.pump(2)
        self.assertTrue(self.overlay.visible)
        self.source.data = b"\x00" * 64
        self.pump(3)
        self.assertFalse(self.overlay.visible)
        self.assertIsNotNone(self.hud.failsafe)

    def test_a_controller_without_a_telemetry_gate_behaves_as_in_e4(self):
        hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: None, timer=self.timer,
                                      clock=self.clock)
        hud.start()
        self.publish(True, True, 1)
        for _ in range(3):
            self.clock.t += 0.02
            hud.tick()
        self.assertTrue(self.overlay.visible)


# ---------------------------------------------------------------------------------------------------------------------------------------
def port_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 54321))
        return True
    except OSError:
        return False
    finally:
        s.close()


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class D_RealOverlay(unittest.TestCase):
    """The real Overlay (offscreen). The HUD text calls are recorded, so 'a row is not drawn' is a fact about draw_hud, not about pixels."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not port_free():
            raise unittest.SkipTest("UDP 54321 is in use (a running TS Scoring is never touched): INCONCLUSIVE")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["l3"])
        import main
        import hud_ui
        cls.main, cls.hud_ui = main, hud_ui

    def setUp(self):
        self._wdl = self.main.write_desktop_log
        self.main.write_desktop_log = lambda *a, **k: None                  # the Overlay logs a door time to the Desktop; a test must not
        self.overlay = self.main.Overlay()
        self.overlay.timer.stop()
        self.drawn = []
        self._orig = self.hud_ui.draw_text_with_stroke

        def recorder(painter, text, *a, **k):
            self.drawn.append(text)
        self.hud_ui.draw_text_with_stroke = recorder

    def tearDown(self):
        self.main.write_desktop_log = self._wdl
        self.hud_ui.draw_text_with_stroke = self._orig
        self.overlay.udp_socket.close()
        self.overlay.close()
        self.overlay.deleteLater()

    def render(self):
        self.drawn.clear()
        self.overlay.grab()
        return list(self.drawn)

    def feed(self, text):
        if self.overlay.telemetry_gate.accept(text):
            self.overlay.apply_telemetry_text(text)

    def send_udp(self, text):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(text.encode("utf-8"), ("127.0.0.1", 54321))
        s.close()

    def pump_until(self, predicate, seconds=3.0):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    # -- Current: unchanged -------------------------------------------------------------------------------------------------------------
    def test_the_current_line_without_avail_updates_everything_as_before(self):
        o = self.overlay
        self.send_udp(current_line(5))
        self.assertTrue(self.pump_until(lambda: o.current_scenario_id == 5), "the datagram was not read from the real UDP socket")
        self.assertEqual((o.bve_speed, o.bve_location, o.bve_time_ms, o.bve_gradient), (45.5, 1234.5, 36000000, 10.0))
        self.assertEqual((o.bve_rev_text, o.bve_pow_text, o.bve_brk_text, o.bve_brk_max), ("前", "P3", "N", 8))
        self.assertEqual((o.bve_next_loc, o.bve_next_time, o.bve_btype, o.cab_brk_count), (2000.0, 36100000, "Ecb", 8))
        self.assertEqual((o.bcPressure, o.bpPressure, o.bve_bp_initial), (0.0, 0.0, 490.0))
        self.assertEqual(o.bve_current_station_name, "駅A")
        self.assertEqual(o.bve_door_close_time_ms, 4630)
        self.assertFalse(o.telemetry_gate.availability.explicit)

    def test_every_hud_item_is_drawn_for_a_current_line(self):
        self.feed(current_line(5))
        texts = self.render()
        joined = " ".join(texts)
        for expected in ("10:00:00", "45.5 km/h", "+10.0 ‰", "前", "P3"):
            self.assertIn(expected, joined, expected)
        for item in tc.HUD_ITEM_REQUIRES:
            self.assertEqual(self.hud_ui.hud_item_state(self.overlay, item), "shown")

    def test_a_current_line_with_an_avail_that_lists_everything_is_the_same_as_without(self):
        all_tokens = "+".join(sorted(tc.KNOWN_TOKENS))
        self.feed(current_line(5))
        without = self.render()
        o2 = self.main.Overlay()
        o2.timer.stop()
        try:
            o2.telemetry_gate.accept(current_line(5).replace("SCENARIO_ID:5,", "SCENARIO_ID:5,AVAIL:1:%s," % all_tokens))
            o2.apply_telemetry_text(current_line(5))
            self.drawn.clear()
            o2.grab()
            with_avail = list(self.drawn)
        finally:
            o2.udp_socket.close()
            o2.close()
        self.assertEqual(without, with_avail)

    # -- Legacy-like: AVAIL -------------------------------------------------------------------------------------------------------------
    def test_a_legacy_line_draws_only_what_it_provides(self):
        self.feed(legacy_line(7))
        texts = " ".join(self.render())
        self.assertIn("10:00:00", texts)
        self.assertIn("30.5 km/h", texts)
        self.assertIn("-12.5 ‰", texts)
        self.assertNotIn("切", texts)                                     # the handle row (REV / POW / BRK texts) is not drawn at all
        self.assertNotIn("EB", texts)
        self.assertEqual(self.hud_ui.hud_item_state(self.overlay, "handle"), "unavailable")
        for item in ("time", "time_left", "speed", "limit", "dist", "grad"):
            self.assertEqual(self.hud_ui.hud_item_state(self.overlay, item), "shown", item)

    def test_the_handle_row_is_the_only_difference_between_a_current_and_a_legacy_screen(self):
        self.feed(legacy_line(7))
        legacy_texts = self.render()
        o2 = self.main.Overlay()
        o2.timer.stop()
        try:
            o2.telemetry_gate.accept(legacy_line(7))
            o2.apply_telemetry_text(legacy_line(7))
            o2.telemetry_gate.availability = tc.ALL_AVAILABLE                # the same data, but with the handle row allowed
            self.drawn.clear()
            o2.grab()
            full_texts = list(self.drawn)
        finally:
            o2.udp_socket.close()
            o2.close()
        self.assertGreater(len(full_texts), len(legacy_texts))                # the allowed one draws the (default) handle texts
        for t in legacy_texts:
            self.assertIn(t, full_texts)

    def test_user_hidden_and_unavailable_are_told_apart(self):
        self.feed(legacy_line(7))
        o = self.overlay
        o.disp_settings["speed"] = False
        self.assertEqual(self.hud_ui.hud_item_state(o, "speed"), "user-hidden")
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")
        o.disp_settings["handle"] = False
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")      # what cannot exist is reported before what the user switched off
        self.assertEqual(self.hud_ui.hud_item_state(o, "grad"), "shown")
        texts = " ".join(self.render())
        self.assertNotIn("30.5 km/h", texts)
        self.assertIn("-12.5 ‰", texts)
        # the user's switches are not touched by availability
        self.assertTrue(o.disp_settings["handle"] is False and o.disp_settings["grad"] is True)

    def test_unknown_item_names_are_not_governed(self):
        self.assertTrue(self.hud_ui.hud_item_available(self.overlay, "no_such_item"))

    def test_availability_updates_with_the_next_line(self):
        o = self.overlay
        self.feed(legacy_line(7))
        self.assertIn("-12.5 ‰", " ".join(self.render()))
        self.feed(legacy_line(7).replace("grad+", ""))
        self.assertEqual(self.hud_ui.hud_item_state(o, "grad"), "unavailable")
        self.assertNotIn("‰", " ".join(self.render()))
        self.feed(legacy_line(7))
        self.assertEqual(self.hud_ui.hud_item_state(o, "grad"), "shown")

    def test_debug_pressure_lines_are_left_out_when_unavailable(self):
        o = self.overlay
        o.show_graph = True
        self.feed(legacy_line(7))
        # the F2 diagnostics are drawn with painter.drawText, not draw_text_with_stroke: build the text list the way draw_hud does
        self.assertFalse(self.hud_ui.hud_data_available(o, "bcp"))
        self.assertFalse(self.hud_ui.hud_data_available(o, "bpp"))
        self.assertTrue(self.hud_ui.hud_data_available(o, "calcg"))
        src = read_text(os.path.join(ROOT, "hud_ui.py"))
        self.assertIn('hud_data_available(self, "bcp")', src)
        self.assertIn('hud_data_available(self, "bpp")', src)
        self.assertIn('hud_data_available(self, "calcg")', src)

    # -- strict: epochs and defaults ----------------------------------------------------------------------------------------------------
    def test_a_new_scenario_instance_leaves_no_old_value_behind(self):
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        self.feed(current_line(10))
        o.bve_map_limits = [(100.0, 60.0)]                                # something only a previous scenario had
        self.assertEqual(o.bve_gradient, 10.0)
        o.telemetry_gate.on_generation(2)
        self.feed(legacy_line(11).replace("GRADIENT:-12.5,", ""))         # the new scenario provides no gradient at all
        self.assertEqual(o.bve_gradient, 0.0)                              # reset to the default, not the old 10.0
        self.assertEqual(o.bve_map_limits, [])
        self.assertEqual(o.bve_rev_text, "切")                            # and the handle values of the old line are gone
        self.assertEqual(o.bve_speed, 30.5)

    def test_values_of_the_same_instance_are_not_reset(self):
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        self.feed(current_line(10))
        o.bve_map_limits = [(100.0, 60.0)]
        self.feed(current_line(10))
        self.assertEqual(o.bve_map_limits, [])                            # (this line carries MAPLIMITS: empty) -> applied normally
        o.bve_gradient = 77.0
        self.feed(core_line(10, "1:speed+time+loc"))
        self.assertEqual(o.bve_gradient, 77.0)                             # same instance: no reset, only the keys of the line are applied

    def test_the_defaults_table_equals_a_fresh_overlay(self):
        fresh = self.overlay
        for name, value in tc.telemetry_state_defaults().items():
            self.assertTrue(hasattr(fresh, name), name)
            self.assertEqual(getattr(fresh, name), value, name)

    def test_reset_restores_exactly_the_defaults(self):
        o = self.overlay
        self.feed(current_line(5))
        o.reset_telemetry_state()
        for name, value in tc.telemetry_state_defaults().items():
            self.assertEqual(getattr(o, name), value, name)

    def test_the_gate_is_non_strict_by_default_in_the_overlay(self):
        self.assertFalse(self.overlay.telemetry_gate.strict)
        self.assertTrue(self.overlay.telemetry_gate.ready)

    def test_garbage_does_not_break_the_intake(self):
        o = self.overlay
        for text in ("", "junk", "SCENARIO_ID:", "AVAIL:1:x"):
            self.send_udp(text)
        self.send_udp(current_line(9))
        self.assertTrue(self.pump_until(lambda: o.current_scenario_id == 9))


# ---------------------------------------------------------------------------------------------------------------------------------------
class E_StaticGuards(unittest.TestCase):
    def test_contract_and_gate_modules_are_pure(self):
        for name in ("telemetry_contract.py", "telemetry_gate.py"):
            tree = ast.parse(read_text(os.path.join(ROOT, name)))
            imports = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    imports.update(a.name.split(".")[0] for a in n.names)
                elif isinstance(n, ast.ImportFrom) and n.module:
                    imports.add(n.module.split(".")[0])
            self.assertEqual(imports - {"math", "re", "collections", "telemetry_contract"}, set(), name)

    def test_the_gate_has_no_clock_and_no_threshold(self):
        code = re.sub(r'"""[\s\S]*?"""', "", read_text(os.path.join(ROOT, "telemetry_gate.py")))
        code = re.sub(r"#.*", "", code)
        for token in ("time.", "monotonic", "sleep", "timeout", "threading", "QTimer", "datetime"):
            self.assertNotIn(token, code, token)

    def test_overlay_changes_are_only_the_l3_allowance(self):
        import overlay_guard
        new = read_text(os.path.join(ROOT, "main.py"))
        old = e4._git("show", "bc4c1160bf6755776d27525a4928a742c460825e:main.py")
        if old is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        # against the E4 commit the L3 additions are the only differences (the E4 commit has none of the L3 members yet)
        self.assertEqual(overlay_guard.problems(old, new), [])

    def test_hud_ui_changes_are_only_the_item_conditions_and_the_pressure_lines(self):
        old = e4._git("show", "bc4c1160bf6755776d27525a4928a742c460825e:hud_ui.py")
        if old is None:
            self.skipTest("git not available (INCONCLUSIVE)")
        new = read_text(os.path.join(ROOT, "hud_ui.py"))
        otree, ntree = ast.parse(old), ast.parse(new)
        ofn = {n.name: n for n in otree.body if isinstance(n, ast.FunctionDef)}
        nfn = {n.name: n for n in ntree.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(nfn) - set(ofn), {"hud_item_available", "hud_data_available", "hud_item_state", "hud_item_visible"})
        self.assertEqual(set(ofn) - set(nfn), set())

        class Revert(ast.NodeTransformer):
            def visit_Call(self, node):
                self.generic_visit(node)
                if isinstance(node.func, ast.Name) and node.func.id == "hud_item_visible":
                    return ast.parse('self.disp_settings["%s"]' % node.args[1].value, mode="eval").body
                return node
        visible_calls = sum(1 for n in ast.walk(nfn["draw_hud"]) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "hud_item_visible")
        reverted = Revert().visit(nfn["draw_hud"])
        ob = {ast.dump(s) for s in ofn["draw_hud"].body}
        nb = {ast.dump(s) for s in reverted.body}
        removed = [s for s in ofn["draw_hud"].body if ast.dump(s) not in nb]
        added = [s for s in reverted.body if ast.dump(s) not in ob]
        # the only removed statement is the dbg_texts.extend([...]) that held the pressure lines; the added ones are its replacement
        self.assertEqual(len(removed), 1)
        self.assertIn("dbg_texts.extend", ast.unparse(removed[0]))
        self.assertIn("BCP", ast.unparse(removed[0]))
        for s in added:
            text = ast.unparse(s)
            self.assertTrue(any(w in text for w in ("dbg_texts", "pressure_parts")), text)
        self.assertEqual(visible_calls, 7)

    def test_normal_mode_main_path_is_unchanged(self):
        new = read_text(os.path.join(ROOT, "main.py"))
        self.assertIn("overlay = Overlay()\n    overlay.show()\n    return app.exec()", new.replace("\r\n", "\n"))

    def test_the_hud_modules_still_have_no_forbidden_operation(self):
        code = re.sub(r'"""[\s\S]*?"""', "", read_text(os.path.join(ROOT, "managed_hud.py")))
        code = re.sub(r"#.*", "", code)
        for token in ("subprocess", "os._exit", "sys.exit", "keyboard", "is_scoring_mode", "begin_official_jump", "write_desktop_log"):
            self.assertNotIn(token, code, token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
