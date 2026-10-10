"""Phase LI1 tests: the handle group and the brake pressures that the AtsEX Legacy sender now writes, read by the UNCHANGED Current reader and drawn by the
UNCHANGED HUD; and the proof that this does not reach the score.

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_legacy_input_li1.py" -v

Layers: (A) the generic display contract (reference.py states it; literal anchors from the phase brief); (B) the real Overlay (offscreen, only when UDP
54321 is free): every supported handle combination parses and draws, a group that is not announced is not drawn, a new scenario instance leaves no handle
or pressure behind; (C) scoring isolation: the same drive with and without the handle / pressure data ends with the same score state, scoring mode is never on;
(D) static guards: no Legacy branch in the Python, managed mode never switches scoring on.
No BVE, no AtsEX, no Caller is started; nothing outside a temp directory is written.
"""
import ast
import importlib.util
import os
import re
import socket
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import legacy_input_reference as ref  # noqa: E402
import telemetry_contract as tc  # noqa: E402
import telemetry_gate as tg  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None

LEGACY_TOKENS = ("time", "speed", "loc", "grad", "station", "door", "siglimit", "siglimit_ahead", "maplimit", "brake_type", "brake_cab", "prates", "calcg",
                 "meta")
ECB, SMEE, CL = ref.ECB, ref.SMEE, ref.CL
BTYPE = {ECB: "Ecb", SMEE: "Smee", CL: "Cl"}


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def handle_pairs(out):
    """The wire parts of a reference 'ok' result, in the order of the Current line."""
    return "REV:%s,POW:%s,BRK:%s,HTYPE:%s,ALLTXT:%s" % tuple(out[1:])


def legacy_line(sid, handle=None, bcp=None, bpp=None, time_ms=36000000, speed=30.5, btype="Ecb", announce=True):
    """A telemetry line of the Legacy sender: the 14 tokens of Phase L3, plus handle / bcp / bpp when given (and announced)."""
    tokens = list(LEGACY_TOKENS)
    tail = []
    if handle is not None:
        if announce:
            tokens.append("handle")
        tail.append(handle_pairs(handle))
    if bcp is not None:
        if announce:
            tokens.append("bcp")
        tail.append("BCP:%s" % bcp)
    if bpp is not None:
        if announce:
            tokens.append("bpp")
        tail.append("BPP:%s" % bpp)
    head = ("SCENARIO_ID:%d,AVAIL:1:%s,SPEED:%s,TIME:%d,LOCATION:1000.5,GRADIENT:-12.5,NEXTLOC:2500,NEXTTIME:36200000,ISPASS:0,ISTIMING:0,MARGINB:5,MARGINF:5,"
            "SIGLIMIT:90,FWDSIGLIMIT:1000,FWDSIGLOC:-1,DOOR:0,DOORDIR:1,TERM:0,MAPHEAD:70,MAPTAIL:70,CALCG:0.00100,BTYPE:%s,CAB:5:0,"
            "PRATES:0_0.2_0.4_0.6_0.8_1:490.0,STATNAME:S"
            % (sid, "+".join(sorted(tokens)), speed, time_ms, btype))
    return head + ("," + ",".join(tail) if tail else "")


def handle_for(htype, brake, rev=1, pow_=0, brk=0, pow_n=4, brk_n=5, eb_n=6):
    out = ref.expected_handle(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, False)
    assert out[0] == "ok", out
    return out


# the five supported combinations as seen on the real machine
ONE_ECB = (ref.ONE_LEVER, ECB, 4, 5, 6)
ONE_SMEE = (ref.ONE_LEVER, SMEE, 4, 9, 10)
TWO_ECB = (ref.TWO_LEVER, ECB, 6, 8, 9)
TWO_SMEE = (ref.TWO_LEVER, SMEE, 4, 9, 10)
TWO_CL = (ref.TWO_LEVER, CL, 5, 2, 3)


def make(layout, rev=1, pow_=0, brk=0):
    htype, brake, pow_n, brk_n, eb_n = layout
    return handle_for(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n)


# ---------------------------------------------------------------------------------------------------------------------------------------
class A_DisplayContract(unittest.TestCase):
    def test_reverser_texts(self):
        self.assertEqual([ref.expected_handle(2, ECB, r, 0, 0, 4, 7, 8, False)[1] for r in (-1, 0, 1)], ["後:-1", "切:0", "前:1"])

    def test_one_lever_ecb_literal(self):
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 0, 4, 5, 6, False),
                         ["ok", "前:1", "N:0", "N:0:6", "1", "後_切_前:N_P1_P2_P3_P4:N_B1_B2_B3_B4_B5_EB:"])

    def test_one_lever_positions(self):
        self.assertEqual(ref.expected_handle(1, ECB, 1, 3, 0, 4, 5, 6, False)[2], "P3:3")           # power position -> P<n>
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 0, 4, 5, 6, False)[2], "N:0")            # neutral -> N
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 3, 4, 5, 6, False)[3], "B3:3:6")         # service brake -> B<n>
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 5, 4, 5, 6, False)[3], "B5:5:6")         # last service notch
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 6, 4, 5, 6, False)[3], "EB:6:6")         # the emergency notch of the host -> EB
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 7, 4, 5, 6, False), ["drop", "brk-range"])   # beyond it is not a position (LI2 final)

    def test_one_lever_smee_is_the_same_shape(self):
        out = ref.expected_handle(1, SMEE, 0, 0, 10, 4, 9, 10, False)
        self.assertEqual(out[3:5], ["EB:10:10", "1"])
        self.assertEqual(out[5], "後_切_前:N_P1_P2_P3_P4:N_B1_B2_B3_B4_B5_B6_B7_B8_B9_EB:")

    def test_two_lever_ecb_and_smee(self):
        out = ref.expected_handle(2, SMEE, -1, 4, 10, 4, 9, 10, False)
        self.assertEqual(out, ["ok", "後:-1", "P4:4", "EB:10:10", "2", "後_切_前:P0_P1_P2_P3_P4:B0_B1_B2_B3_B4_B5_B6_B7_B8_B9_EB:"])
        self.assertEqual(ref.expected_handle(2, ECB, 0, 0, 0, 6, 8, 9, False)[2:4], ["P0:0", "B0:0:9"])

    def test_two_lever_cl(self):
        texts = [ref.expected_handle(2, CL, 1, 0, b, 5, 2, 3, False)[3] for b in (0, 1, 2, 3)]
        self.assertEqual(texts, ["運転:0:3", "重なり:1:3", "常用:2:3", "非常:3:3"])
        self.assertEqual(ref.expected_handle(2, CL, 1, 0, 4, 5, 2, 3, False), ["drop", "brk-range"])      # beyond the emergency notch (LI2 final)
        self.assertEqual(ref.expected_handle(2, CL, 1, 5, 0, 5, 2, 3, False)[2], "P5:5")
        self.assertEqual(ref.expected_handle(2, CL, 1, 0, 0, 5, 2, 3, False)[5], "後_切_前:P0_P1_P2_P3_P4_P5:運転_重なり_常用_非常:")

    def test_one_lever_cl_is_built_since_li2(self):
        # LI1 left the one-lever Cl cab unavailable; LI2 (tests\test_legacy_input_li2.py has the full table) builds it
        self.assertEqual(ref.expected_handle(1, CL, 1, 0, 0, 5, 2, 3, False),
                         ["ok", "前:1", "運転:0", "運転:0:3", "1", "後_切_前:運転_P1_P2_P3_P4_P5:運転_重なり_常用_非常:"])      # LI2 final: the RUN word at rest (it was the off word)

    def test_holding_speed_brake_cases_are_built_since_the_li2_final(self):
        # LI1 refused every holding speed brake; the LI2 final builds all of them (only an unreadable flag is refused)
        self.assertEqual(ref.expected_handle(1, ECB, 1, 0, 1, 4, 7, 8, True)[3], "抑速:1:8")
        self.assertEqual(ref.expected_handle(2, CL, 1, 0, 1, 5, 2, 3, True)[3], "抑速:1:3")
        self.assertEqual(ref.expected_handle(2, ECB, 1, 0, 0, 4, 7, 8, None), ["drop", "hold-missing"])

    def test_emergency_boundary_is_the_host_value(self):
        self.assertEqual(ref.expected_handle(2, ECB, 1, 0, 0, 4, 7, 9, False), ["drop", "eb-layout"])    # not brake notches + 1: nothing is derived

    def test_every_ok_case_is_one_wire_part_per_key(self):
        cases = ref.all_cases()
        self.assertGreater(len(cases), 800)
        ok = [c for c in cases if c["out"][0] == "ok"]
        for c in ok:
            rev, pow_, brk, htype, alltxt = c["out"][1:]
            for text in (rev, pow_, brk, htype, alltxt):
                self.assertNotIn(",", text, c)
                self.assertNotIn("\n", text, c)
            self.assertEqual(len(rev.split(":")), 2, c)
            self.assertEqual(len(pow_.split(":")), 2, c)
            self.assertEqual(len(brk.split(":")), 3, c)
            self.assertEqual(len(alltxt.split(":")), 4, c)           # rev : power : brake : holding speed texts (empty unless the cab has independent holding speed notches)
            self.assertRegex(alltxt.split(":")[3], r"^(H[0-9]+(_H[0-9]+)*)?$", c)
        reasons = {c["out"][1] for c in cases if c["out"][0] == "drop"}
        self.assertEqual(reasons, {"type-unknown", "brake-unknown", "rev-missing", "pow-missing", "brk-missing", "layout-missing",
                                   "hold-missing", "layout-range", "cl-layout", "eb-layout", "rev-range",
                                   "holdn-missing", "hold-range", "pow-range", "brk-range", "pow-brk-both"})

    def test_the_wire_vocabulary_is_the_current_one(self):
        self.assertEqual(tc.TOKEN_KEYS["handle"], ("REV", "POW", "BRK", "HTYPE", "ALLTXT"))
        self.assertEqual(tc.TOKEN_KEYS["bcp"], ("BCP",))
        self.assertEqual(tc.TOKEN_KEYS["bpp"], ("BPP",))
        self.assertIn("handle", tc.HUD_ITEM_REQUIRES["handle"])


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
class RealOverlayCase(unittest.TestCase):
    """The real Overlay (offscreen). The HUD text calls are recorded, so 'a row is not drawn' is a fact about draw_hud, not about pixels."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if not port_free():
            raise unittest.SkipTest("UDP 54321 is in use (a running TS Scoring is never touched): INCONCLUSIVE")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["li1"])
        import main
        import hud_ui
        cls.main, cls.hud_ui = main, hud_ui

    def new_overlay(self):
        o = self.main.Overlay()
        o.timer.stop()
        self._overlays.append(o)
        return o

    def setUp(self):
        self._overlays = []
        self._wdl = self.main.write_desktop_log
        self.main.write_desktop_log = lambda *a, **k: None
        self.overlay = self.new_overlay()
        self.drawn = []
        self._orig = self.hud_ui.draw_text_with_stroke

        def recorder(painter, text, *a, **k):
            self.drawn.append(text)
        self.hud_ui.draw_text_with_stroke = recorder

    def tearDown(self):
        self.main.write_desktop_log = self._wdl
        self.hud_ui.draw_text_with_stroke = self._orig
        for o in self._overlays:
            try:
                o.udp_socket.close()
                o.close()
                o.deleteLater()
            except Exception:
                pass

    def render(self, overlay=None):
        self.drawn.clear()
        (overlay or self.overlay).grab()
        return list(self.drawn)

    def feed(self, text, overlay=None):
        o = overlay or self.overlay
        if o.telemetry_gate.accept(text):
            o.apply_telemetry_text(text)


class B_RealOverlayReadsTheLegacyGroups(RealOverlayCase):
    def test_two_lever_smee_in_eb_is_read_and_drawn(self):
        o = self.overlay
        self.feed(legacy_line(21, make(TWO_SMEE, rev=-1, pow_=0, brk=10), "440.0", "0.0", btype="Smee"))
        self.assertEqual((o.bve_rev_text, o.bve_rev_pos, o.bve_pow_text, o.bve_pow_notch), ("後", -1, "P0", 0))
        self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max, o.is_single_handle), ("EB", 10, 10, False))
        self.assertEqual(o.all_brk_texts, ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "EB"])
        self.assertEqual((o.bcPressure, o.bpPressure), (440.0, 0.0))
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown")
        texts = self.render()
        for expected in ("後", "P0", "EB"):
            self.assertIn(expected, texts)

    def test_two_lever_ecb(self):
        o = self.overlay
        self.feed(legacy_line(22, make(TWO_ECB, rev=1, pow_=3, brk=0)))
        self.assertEqual((o.bve_rev_text, o.bve_pow_text, o.bve_brk_text, o.is_single_handle), ("前", "P3", "B0", False))
        texts = self.render()
        for expected in ("前", "P3", "B0"):
            self.assertIn(expected, texts)

    def test_two_lever_cl_words(self):
        o = self.overlay
        for brk, word in ((0, "運転"), (1, "重なり"), (2, "常用"), (3, "非常")):
            self.feed(legacy_line(23, make(TWO_CL, rev=1, pow_=2, brk=brk), btype="Cl"))
            self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max), (word, brk, 3))
            self.assertIn(word, self.render())
        self.assertEqual(o.all_brk_texts, ["運転", "重なり", "常用", "非常"])

    def test_one_lever_ecb_draws_one_handle_text(self):
        o = self.overlay
        self.feed(legacy_line(24, make(ONE_ECB, rev=1, pow_=3, brk=0)))
        self.assertTrue(o.is_single_handle)
        self.assertEqual(o.all_brk_texts, ["N", "B1", "B2", "B3", "B4", "B5", "EB"])
        texts = self.render()
        self.assertIn("前", texts)
        self.assertIn("P3", texts)                       # the handle shows the power text while a power position is held
        self.feed(legacy_line(24, make(ONE_ECB, rev=1, pow_=0, brk=4)))
        texts = self.render()
        self.assertIn("B4", texts)                       # ... and the brake text while the brake is applied
        self.feed(legacy_line(24, make(ONE_ECB, rev=1, pow_=0, brk=6)))
        self.assertIn("EB", self.render())
        self.feed(legacy_line(24, make(ONE_ECB, rev=1, pow_=0, brk=0)))
        self.assertIn("N", self.render())                # neutral -> N

    def test_one_lever_smee(self):
        o = self.overlay
        self.feed(legacy_line(25, make(ONE_SMEE, rev=0, pow_=0, brk=9), btype="Smee"))
        self.assertTrue(o.is_single_handle)
        self.assertEqual((o.bve_brk_text, o.bve_brk_max), ("B9", 10))
        self.assertIn("B9", self.render())

    def test_pressure_is_read_in_kpa_unchanged(self):
        o = self.overlay
        self.feed(legacy_line(26, None, "123.4", "490.0"))
        self.assertEqual((o.bcPressure, o.bpPressure), (123.4, 490.0))
        self.assertEqual(o.bve_bp_initial, 490.0)                   # bp_initial is NOT sent: the reader's own default stays
        self.assertTrue(self.hud_ui.hud_data_available(o, "bcp") and self.hud_ui.hud_data_available(o, "bpp"))

    def test_pressure_tokens_are_independent(self):
        o = self.overlay
        self.feed(legacy_line(27, None, "50.0", None))
        self.assertTrue(self.hud_ui.hud_data_available(o, "bcp"))
        self.assertFalse(self.hud_ui.hud_data_available(o, "bpp"))
        self.assertEqual(o.bcPressure, 50.0)
        self.assertEqual(o.bpPressure, 0.0)                         # never sent: the default, and the item is told unavailable

    def test_a_group_that_is_not_announced_is_not_drawn(self):
        o = self.overlay
        self.feed(legacy_line(28))                                   # a one-lever Cl, an unreadable cab ...: no handle group at all
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")
        joined = " ".join(self.render())
        self.assertNotIn("切", joined)
        self.assertNotIn("EB", joined)
        self.assertFalse(self.hud_ui.hud_data_available(o, "bcp"))
        self.assertFalse(self.hud_ui.hud_data_available(o, "bpp"))

    def test_availability_follows_the_next_line(self):
        o = self.overlay
        self.feed(legacy_line(29, make(TWO_ECB, rev=1, pow_=3, brk=0), "10.0", "490.0"))
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown")
        self.assertIn("P3", self.render())
        self.feed(legacy_line(29, None, None, None))                 # the same scenario, the group could not be built in this Tick
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")
        self.assertNotIn("P3", self.render())                        # the old text is not shown
        self.assertFalse(self.hud_ui.hud_data_available(o, "bcp"))

    def test_an_unsupported_avail_version_is_not_interpreted(self):
        line = legacy_line(30, make(TWO_ECB)).replace("AVAIL:1:", "AVAIL:2:")
        self.assertFalse(tc.parse_telemetry(line).valid)

    def test_a_new_scenario_instance_leaves_no_handle_or_pressure_behind(self):
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        self.feed(legacy_line(31, make(TWO_SMEE, rev=1, pow_=4, brk=10), "440.0", "0.0", btype="Smee"))
        self.assertEqual((o.bve_pow_text, o.bcPressure, o.bpPressure), ("P4", 440.0, 0.0))
        o.telemetry_gate.on_generation(2)
        self.feed(legacy_line(32))                                   # the new scenario: no handle, no pressure
        self.assertEqual((o.bve_rev_text, o.bve_pow_text, o.bve_brk_text, o.bve_brk_notch), ("切", "N", "N", 0))
        self.assertEqual((o.bcPressure, o.bpPressure, o.bve_bp_initial), (0.0, 0.0, 490.0))
        self.assertFalse(o.is_single_handle)
        self.assertEqual(o.all_brk_texts, [])
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")

    def test_a_new_scenario_with_a_different_vehicle_replaces_the_layout(self):
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        self.feed(legacy_line(41, make(TWO_SMEE, rev=1, pow_=0, brk=0), btype="Smee"))
        self.assertEqual(len(o.all_brk_texts), 11)
        o.telemetry_gate.on_generation(2)
        self.feed(legacy_line(42, make(ONE_ECB, rev=1, pow_=0, brk=0)))
        self.assertTrue(o.is_single_handle)
        self.assertEqual(o.all_brk_texts, ["N", "B1", "B2", "B3", "B4", "B5", "EB"])

    def test_the_hud_is_hidden_before_the_first_line_of_a_generation(self):
        gate = tg.TelemetryGate(strict=True)
        self.assertFalse(gate.ready)
        gate.on_generation(1)
        self.assertFalse(gate.ready)
        self.assertTrue(gate.accept(legacy_line(51, make(TWO_ECB))))
        self.assertTrue(gate.ready)
        gate.on_generation(2)
        self.assertFalse(gate.ready)                                  # a new generation: not shown until its own first line


# ---------------------------------------------------------------------------------------------------------------------------------------
class C_ScoringIsolation(RealOverlayCase):
    """The managed application runs update_physics_and_scoring (the physics the HUD needs) but never switches scoring on. The handle and pressure data
    of the Legacy sender must not change the score state in any way."""

    STEPS = 700

    def drive(self, with_input, layout, btype, brk_script):
        import managed_hud
        o = self.new_overlay()
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        for i in range(self.STEPS):
            t = 36000000 + i * 16
            if with_input:
                brk = brk_script(i)
                bp = "0.0" if brk >= layout[4] else "490.0"
                line = legacy_line(61, make(layout, rev=1, pow_=0, brk=brk), "440.0" if brk >= layout[4] else "50.0", bp, time_ms=t, speed=40.0, btype=btype)
            else:
                line = legacy_line(61, None, None, None, time_ms=t, speed=40.0, btype=btype)
            self.feed(line, o)
            managed_hud.hud_update_step(o)
        return o

    @staticmethod
    def state(o):
        return {"score": o.score, "details": dict(o.score_details), "popups": list(o.popups), "mode": o.is_scoring_mode, "save": list(o.save_data),
                "finished": getattr(o, "is_scoring_finished", False), "retry": getattr(o, "total_retry_count", 0)}

    def check_same(self, layout, btype):
        script = lambda i: 0 if i < 100 else (layout[4] if i < 400 else 0)           # released, EB held for ~5 s, released
        with_input = self.drive(True, layout, btype, script)
        without = self.drive(False, layout, btype, script)
        a, b = self.state(with_input), self.state(without)
        self.assertEqual(a, b)
        self.assertEqual(a["score"], 0)
        self.assertEqual(a["popups"], [])
        self.assertFalse(a["mode"])
        self.assertTrue(all(v == 0 for v in a["details"].values()))
        return with_input

    def test_smee_eb_with_a_low_brake_pipe_does_not_touch_the_score(self):
        self.check_same(TWO_SMEE, "Smee")

    def test_ecb_two_lever(self):
        self.check_same(TWO_ECB, "Ecb")

    def test_ecb_one_lever(self):
        self.check_same(ONE_ECB, "Ecb")

    def test_cl(self):
        self.check_same(TWO_CL, "Cl")

    def test_the_bookkeeping_is_fed_but_the_penalty_is_refused(self):
        import scoring_logic
        calls = []
        original = scoring_logic.add_score_popup

        def spy(self_, points, text, *a, **k):
            before = (self_.score, len(self_.popups))
            original(self_, points, text, *a, **k)
            calls.append((points, text, (self_.score, len(self_.popups)) == before))
        scoring_logic.add_score_popup = spy
        try:
            o = self.drive(True, TWO_SMEE, "Smee", lambda i: 10 if i >= 50 else 0)
        finally:
            scoring_logic.add_score_popup = original
        self.assertTrue(o.manual_eb_penalty_applied)                  # the bookkeeping saw the emergency brake handle ...
        self.assertTrue(any(points == -500 for points, text, refused in calls))    # ... asked for the penalty ...
        self.assertTrue(all(refused for points, text, refused in calls))           # ... and EVERY request was refused: scoring mode is off
        self.assertEqual((o.score, o.popups, o.is_scoring_mode), (0, [], False))


# ---------------------------------------------------------------------------------------------------------------------------------------
class D_StaticGuards(unittest.TestCase):
    PRODUCT = ("main.py", "hud_ui.py", "scoring_logic.py", "network.py", "managed_hud.py", "managed_mode.py", "managed_state.py", "telemetry_gate.py",
               "telemetry_contract.py", "config.py", "utils.py", "menu_ui.py")

    HOST_WORD = re.compile(r"atsex|bveex|bve5|bve6|host_?legacy|legacy_?host|is_?legacy|legacy_?mode|legacy_?sender|legacy_?telemetry", re.I)

    def test_no_python_branch_depends_on_the_sender_host(self):
        # (the retry code of the scoring has an unrelated variable use_legacy: the old LOC jump method, not a host)
        offenders = []
        for name in self.PRODUCT:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            tree = ast.parse(read_text(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                    for sub in ast.walk(node.test):
                        word = None
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            word = sub.value
                        elif isinstance(sub, ast.Name):
                            word = sub.id
                        elif isinstance(sub, ast.Attribute):
                            word = sub.attr
                        if word and self.HOST_WORD.search(word):
                            offenders.append((name, node.lineno))
        self.assertEqual(offenders, [])

    def test_the_btype_branches_are_the_old_ones(self):
        # the only host-specific word the scoring code branches on is the brake type, which the Current sender writes too
        src = read_text(os.path.join(ROOT, "scoring_logic.py"))
        self.assertNotIn("AtsEx", src)
        self.assertNotIn("BveEx", src)

    def test_managed_mode_never_switches_scoring_on(self):
        for name in ("managed_hud.py", "managed_mode.py", "managed_state.py", "telemetry_gate.py", "telemetry_contract.py"):
            src = read_text(os.path.join(ROOT, name))
            self.assertIsNone(re.search(r"is_scoring_mode\s*=\s*True", src), name)
        main_src = read_text(os.path.join(ROOT, "main.py"))
        tree = ast.parse(main_src)
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name == "run_managed":
                body = ast.get_source_segment(main_src, fn)
                self.assertNotIn("is_scoring_mode", body)
                self.assertNotIn("keyboard", body)

    def test_scoring_points_are_added_only_through_the_gated_popup(self):
        src = read_text(os.path.join(ROOT, "scoring_logic.py"))
        gated = re.search(r"def add_score_popup\(.*?\):\n\s*if \(\n\s*not getattr\(self, 'is_scoring_mode', False\)\n\s*and not force\n\s*\):\n\s*return", src, re.S)
        self.assertIsNotNone(gated)


if __name__ == "__main__":
    unittest.main()
