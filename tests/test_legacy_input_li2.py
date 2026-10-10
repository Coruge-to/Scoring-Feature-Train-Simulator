"""Phase LI2 tests: the holding speed handles and the one-lever Cl handle that the AtsEX Legacy sender now writes, read by the UNCHANGED Current reader and
drawn by the UNCHANGED HUD.

    C:\\Python314\\python.exe -m unittest discover -s tests -p "test_legacy_input_li2.py" -v

TWO DIFFERENT FEATURES, never mixed up (this file keeps them apart on purpose):
  * HoldingSpeedBrake (hold=True): the first BRAKE position is the holding speed brake, shown as the word for it in the brake column, never as H1.
  * HoldingSpeedNotchCount != 0 (hold_n): the independent holding speed notches of a TWO-lever cab: POW = -1..hold_n shown as H1..Hn; the brake column is untouched.
    The host reports the count NEGATED (5 notches = -5, the real machine of the LI2 retest and the BVE5 vehicle loader), so hold_n is <= 0 everywhere in this file.

Layers: (A) the display contract (legacy_input_reference.py states it; the literal anchors below come from the phase brief and the real-machine logs);
(B) the real Overlay (offscreen, only when UDP 54321 is free); (C) static guards: no Legacy / holding speed branch in the Python, the Current contract is reused.
No BVE, no AtsEX, no Caller is started; nothing outside a temp directory is written.
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

import legacy_input_reference as ref  # noqa: E402
import telemetry_contract as tc  # noqa: E402
import test_legacy_input_li1 as li1  # noqa: E402

ECB, SMEE, CL = ref.ECB, ref.SMEE, ref.CL
ONE, TWO = ref.ONE_LEVER, ref.TWO_LEVER
HOLD_BRAKE = "抑速"


def build(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n):
    return ref.expected_handle(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n)


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------------------------------------------------------------------
class A_HoldingSpeedBrake(unittest.TestCase):
    """cab=TwoLeverCab brake=Ecb powN=5 brkN=8 ebN=9 hold=1 b67=7 (real machine). The holding speed BRAKE: brake position 1."""

    def b(self, brk, rev=1, pow_=0, brake=ECB, pow_n=5, brk_n=8, eb_n=9):
        return build(TWO, brake, rev, pow_, brk, pow_n, brk_n, eb_n, True, 0)

    def test_the_brake_positions_in_the_order_the_user_confirmed(self):
        # brk=0 B0, 1 holding speed brake, 2 B1, 3 B2, ... 8 B7, 9 EB
        words = [self.b(k)[3].split(":")[0] for k in range(0, 10)]
        self.assertEqual(words, ["B0", HOLD_BRAKE, "B1", "B2", "B3", "B4", "B5", "B6", "B7", "EB"])

    def test_the_brake_notch_and_the_emergency_notch_on_the_wire(self):
        self.assertEqual(self.b(0)[3], "B0:0:9")
        self.assertEqual(self.b(1)[3], HOLD_BRAKE + ":1:9")
        self.assertEqual(self.b(2)[3], "B1:2:9")                 # the first service brake after the holding speed brake
        self.assertEqual(self.b(5)[3], "B4:5:9")                 # an intermediate service brake
        self.assertEqual(self.b(8)[3], "B7:8:9")                 # the last service brake (BrakeNotchCount)
        self.assertEqual(self.b(9)[3], "EB:9:9")                 # the emergency notch of the host
        self.assertEqual(self.b(10), ["drop", "brk-range"])      # beyond it is not a position (LI2 final)

    def test_the_hud_row_is_b0_holding_service_emergency(self):
        out = self.b(3)
        self.assertEqual(out[5], "後_切_前:P0_P1_P2_P3_P4_P5:B0_" + HOLD_BRAKE + "_B1_B2_B3_B4_B5_B6_B7_EB:")
        self.assertEqual(len(out[5].split(":")[2].split("_")), 10)       # one text per brake position 0..9, indexed by the brake position
        self.assertEqual(out[4], "2")

    def test_it_is_never_h1(self):
        for k in range(0, 10):
            self.assertNotRegex(self.b(k)[3], r"^H[0-9]")
            self.assertNotIn("H", self.b(k)[5].split(":")[2])
        self.assertEqual(self.b(1)[5].split(":")[3], "")                  # no independent holding speed texts: it is the BRAKE feature

    def test_the_power_column_is_the_ordinary_one(self):
        self.assertEqual([self.b(0, pow_=p)[2] for p in (0, 1, 5)], ["P0:0", "P1:1", "P5:5"])

    def test_smee_has_the_same_shape(self):
        out = build(TWO, SMEE, 1, 0, 1, 4, 9, 10, True, 0)
        self.assertEqual(out[3], HOLD_BRAKE + ":1:10")
        self.assertEqual(out[5], "後_切_前:P0_P1_P2_P3_P4:B0_" + HOLD_BRAKE + "_B1_B2_B3_B4_B5_B6_B7_B8_EB:")

    def test_the_holding_speed_notch_count_is_not_used_with_the_brake(self):
        # the brake side does not depend on HoldingSpeedNotchCount, readable or not, zero or not (the independent notches are the POWER side and only add the H texts / H positions)
        base = self.b(1)
        for hold_n in (None, 0, -1, -5, 1, 5, -100):
            out = build(TWO, ECB, 1, 0, 1, 5, 8, 9, True, hold_n)
            self.assertEqual(out[:5], base[:5], hold_n)
            self.assertEqual(out[5].rsplit(":", 1)[0], base[5].rsplit(":", 1)[0], hold_n)       # REV / POW / BRK texts of ALLTXT identical

    def test_the_independent_notches_work_together_with_the_holding_speed_brake(self):
        # LI2 final: both features at once (B2 of the 24 combinations): POW H1..H5 and BRK B0 / hold word / B1.. / EB
        self.assertEqual(build(TWO, ECB, 1, -1, 0, 5, 8, 9, True, -5)[2:4], ["H1:-1", "B0:0:9"])
        self.assertEqual(build(TWO, ECB, 1, -5, 1, 5, 8, 9, True, -5)[2:4], ["H5:-5", HOLD_BRAKE + ":1:9"])
        self.assertEqual(build(TWO, ECB, 1, -6, 0, 5, 8, 9, True, -5), ["drop", "pow-range"])
        self.assertEqual(build(TWO, ECB, 1, -1, 0, 5, 8, 9, True, 0), ["drop", "pow-range"])           # no notches: no H1

    def test_the_formerly_refused_combinations_are_built(self):
        # LI2 final: Cl + holding speed brake and one lever + holding speed brake were observed on the real BVE5 and are built; only an unreadable flag is refused
        self.assertEqual(build(TWO, CL, 1, 0, 1, 5, 2, 3, True, 0)[3], HOLD_BRAKE + ":1:3")
        self.assertEqual(build(ONE, CL, 1, 0, 1, 5, 2, 3, True, 0)[3], HOLD_BRAKE + ":1:3")
        self.assertEqual(build(ONE, ECB, 1, 0, 1, 5, 8, 9, True, 0)[3], HOLD_BRAKE + ":1:9")
        self.assertEqual(build(ONE, SMEE, 1, 0, 1, 4, 9, 10, True, 0)[3], HOLD_BRAKE + ":1:10")
        self.assertEqual(build(TWO, ECB, 1, 0, 1, 5, 8, 9, None, 0), ["drop", "hold-missing"])

    def test_the_layout_rules_still_apply(self):
        self.assertEqual(build(TWO, ECB, 1, 0, 1, 5, 8, 10, True, 0), ["drop", "eb-layout"])          # the emergency notch is brake notches + 1, never derived
        self.assertEqual(build(TWO, ECB, 1, 0, -1, 5, 8, 9, True, 0), ["drop", "brk-range"])

    def test_the_brake_list_has_one_text_per_position_for_other_sizes(self):
        for brk_n in (1, 2, 5, 8, 9):
            eb = brk_n + 1
            out = build(TWO, ECB, 1, 0, 0, 4, brk_n, eb, True, 0)
            texts = out[5].split(":")[2].split("_")
            self.assertEqual(len(texts), eb + 1, brk_n)
            self.assertEqual(texts[0], "B0")
            self.assertEqual(texts[1], HOLD_BRAKE)
            self.assertEqual(texts[-1], "EB")
            for k in range(0, eb + 1):
                self.assertEqual(build(TWO, ECB, 1, 0, k, 4, brk_n, eb, True, 0)[3].split(":")[0], texts[k], (brk_n, k))


class B_IndependentHoldingSpeed(unittest.TestCase):
    """cab=TwoLeverCab brake=Smee powN=5 brkN=8 ebN=9 hold=0, HoldingSpeedNotchCount=-5 (real machine). POW 0 P0 .. 5 P5, -1 H1 .. -5 H5."""

    def b(self, pow_, brk=0, rev=1, hold_n=-5, pow_n=5, brk_n=8, eb_n=9, brake=SMEE):
        return build(TWO, brake, rev, pow_, brk, pow_n, brk_n, eb_n, False, hold_n)

    def test_pow_minus_one_to_minus_n_are_h1_to_hn(self):
        for n in range(1, 6):
            self.assertEqual(self.b(-n)[2], "H%d:%d" % (n, -n))

    def test_below_the_formal_count_is_unavailable(self):
        self.assertEqual(self.b(-6), ["drop", "pow-range"])
        self.assertEqual(self.b(-100), ["drop", "pow-range"])
        self.assertEqual(self.b(-3, hold_n=-2), ["drop", "pow-range"])
        self.assertEqual(self.b(-2, hold_n=-2)[2], "H2:-2")

    def test_power_notches_are_unchanged(self):
        self.assertEqual(self.b(0)[2], "P0:0")
        self.assertEqual([self.b(p)[2] for p in range(1, 6)], ["P1:1", "P2:2", "P3:3", "P4:4", "P5:5"])
        self.assertEqual(self.b(6), ["drop", "pow-range"])

    def test_the_brake_column_stays_b0_to_bn_and_eb(self):
        # the host often keeps the previous brake value while a holding speed notch is held: it is shown as it is, never as the holding speed brake
        self.assertEqual([self.b(-2, brk=k)[3] for k in (0, 1, 4, 8, 9)], ["B0:0:9", "B1:1:9", "B4:4:9", "B8:8:9", "EB:9:9"])
        self.assertEqual(self.b(0, brk=1)[3], "B1:1:9")
        for k in range(0, 10):
            self.assertNotIn(HOLD_BRAKE, self.b(-1, brk=k)[3])

    def test_the_all_texts_carry_the_holding_speed_texts(self):
        out = self.b(-1)
        self.assertEqual(out[5], "後_切_前:P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5")
        self.assertEqual(out[4], "2")
        self.assertEqual(self.b(2)[5], out[5])                           # a static layout: the same texts whatever the handle position

    def test_the_formal_count_is_required_and_is_never_replaced_by_the_power_notch_count(self):
        # unreadable / not a count: POW below zero is unavailable with the reason; POW 0 and above (and the brake) are not touched (position-level fallback, no count guessed)
        self.assertEqual(self.b(-1, hold_n=None), ["drop", "holdn-missing"])
        self.assertEqual(self.b(0, hold_n=None)[:4], ["ok", "前:1", "P0:0", "B0:0:9"])
        # PowerNotchCount (5) is NOT used as the holding speed count: with 0 there is no H1
        self.assertEqual(self.b(-1, hold_n=0), ["drop", "pow-range"])
        self.assertEqual(self.b(0, hold_n=0)[5], "後_切_前:P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:")
        self.assertEqual(self.b(-1, hold_n=1), ["drop", "hold-range"])          # above 0 is not a count (the positive number the first LI2 build expected)
        self.assertEqual(self.b(-1, hold_n=100), ["drop", "hold-range"])
        self.assertEqual(self.b(-1, hold_n=-100), ["drop", "hold-range"])

    def test_the_largest_supported_count(self):
        self.assertEqual(self.b(-99, hold_n=-99)[2], "H99:-99")
        self.assertEqual(self.b(-100, hold_n=-99), ["drop", "pow-range"])

    def test_ecb_is_the_same_as_smee(self):
        self.assertEqual(self.b(-4, brake=ECB, pow_n=6, brk_n=8, eb_n=9, hold_n=-3), ["drop", "pow-range"])
        self.assertEqual(self.b(-3, brake=ECB, pow_n=6, brk_n=8, eb_n=9, hold_n=-3)[2], "H3:-3")

    def test_a_cl_car_uses_the_independent_notches_too(self):
        # (LI2 final: it does - the two-lever Cl car has the independent notches too; the test name is historical)
        self.assertEqual(build(TWO, CL, 1, -1, 0, 5, 2, 3, False, -5)[2:4], ["H1:-1", "運転:0:3"])
        self.assertEqual(build(TWO, CL, 1, -6, 0, 5, 2, 3, False, -5), ["drop", "pow-range"])
        self.assertEqual(build(TWO, CL, 1, -1, 0, 5, 2, 3, False, 0), ["drop", "pow-range"])
        self.assertEqual(build(TWO, CL, 1, 0, 0, 5, 2, 3, False, -5)[5], "後_切_前:P0_P1_P2_P3_P4_P5:運転_重なり_常用_非常:H1_H2_H3_H4_H5")


class C_OneLeverWithHoldingSpeedNotchCount(unittest.TestCase):
    """OneLeverCab, brake=Smee powN=5 brkN=8 ebN=9 hold=0, HoldingSpeedNotchCount=-5 (artificial car): the H notches never appear (pow 0..5, brk 0..9)."""

    def b(self, pow_, brk=0, hold_n=-5, brake=SMEE, pow_n=5, brk_n=8, eb_n=9):
        return build(ONE, brake, 1, pow_, brk, pow_n, brk_n, eb_n, False, hold_n)

    def test_the_setting_alone_is_not_a_reason_to_refuse(self):
        for hold_n in (0, -1, -5, -99, None, 5, -100):
            self.assertEqual(self.b(0, hold_n=hold_n)[0], "ok", hold_n)

    def test_an_ordinary_one_lever_handle_is_sent(self):
        self.assertEqual(self.b(3)[2], "P3:3")
        self.assertEqual(self.b(0, 0)[2:4], ["N:0", "N:0:9"])
        self.assertEqual(self.b(0, 5)[3], "B5:5:9")
        self.assertEqual(self.b(0, 9)[3], "EB:9:9")

    def test_it_is_identical_to_the_same_car_without_the_setting(self):
        for p in range(0, 7):
            for k in range(0, 11):
                for hold_n in (None, -1, -5, 5):
                    self.assertEqual(self.b(p, k, hold_n=hold_n), self.b(p, k, hold_n=0), (p, k, hold_n))
        self.assertEqual(self.b(0, hold_n=-5)[5], "後_切_前:N_P1_P2_P3_P4_P5:N_B1_B2_B3_B4_B5_B6_B7_B8_EB:")        # no holding speed texts

    def test_no_one_lever_h_display(self):
        for p in range(0, 6):
            for k in range(0, 10):
                out = self.b(p, k)
                if out[0] != "ok":                          # (power and brake both positive on a single handle)
                    self.assertEqual(out, ["drop", "pow-brk-both"], (p, k))
                    continue
                self.assertNotRegex(out[2], r"^H")
                self.assertNotRegex(out[3], r"^H")

    def test_pow_below_zero_is_an_unknown_case_and_unavailable(self):
        for p in (-1, -2, -5, -6):
            self.assertEqual(self.b(p), ["drop", "pow-range"], p)
        self.assertEqual(self.b(-1, hold_n=0), ["drop", "pow-range"])
        self.assertEqual(self.b(-1, brake=ECB), ["drop", "pow-range"])


class D_OneLeverCl(unittest.TestCase):
    """cab=OneLeverCab brake=Cl powN=5 brkN=2 ebN=3 (real machine): P5 .. P1, run, lap, service, emergency (LI2 final: the rest word is the RUN word)."""

    def b(self, pow_, brk, rev=1, pow_n=5, brk_n=2, eb_n=3, hold=False, hold_n=0):
        return build(ONE, CL, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n)

    def test_the_power_positions(self):
        for p in range(1, 6):
            out = self.b(p, 0)
            self.assertEqual((out[2], out[3]), ("P%d:%d" % (p, p), "運転:0:3"))

    def test_off_lap_service_emergency(self):
        self.assertEqual(self.b(0, 0)[2:4], ["運転:0", "運転:0:3"])
        self.assertEqual(self.b(0, 1)[3], "重なり:1:3")
        self.assertEqual(self.b(0, 2)[3], "常用:2:3")
        self.assertEqual(self.b(0, 3)[3], "非常:3:3")
        self.assertEqual(self.b(0, 4), ["drop", "brk-range"])         # beyond the emergency notch of the host is not a position (LI2 final)
        self.assertEqual(self.b(0, 1000), ["drop", "brk-range"])

    def test_literal_line(self):
        self.assertEqual(self.b(0, 0), ["ok", "前:1", "運転:0", "運転:0:3", "1", "後_切_前:運転_P1_P2_P3_P4_P5:運転_重なり_常用_非常:"])
        self.assertEqual(self.b(2, 0, rev=-1), ["ok", "後:-1", "P2:2", "運転:0:3", "1", "後_切_前:運転_P1_P2_P3_P4_P5:運転_重なり_常用_非常:"])

    def test_it_is_a_one_lever_handle_and_the_two_lever_cl_is_unchanged(self):
        self.assertEqual(self.b(0, 0)[4], "1")
        two = build(TWO, CL, 1, 0, 0, 5, 2, 3, False, 0)
        self.assertEqual(two[4], "2")
        self.assertEqual(two[2:4], ["P0:0", "運転:0:3"])
        self.assertEqual(two[5], "後_切_前:P0_P1_P2_P3_P4_P5:運転_重なり_常用_非常:")

    def test_the_reverser_off_word_and_the_handle_run_word_are_different_words(self):
        out = self.b(0, 0, rev=0)
        self.assertEqual(out[1], "切:0")
        self.assertEqual(out[2], "運転:0")

    def test_power_and_brake_both_positive_is_unavailable(self):
        for p in (1, 3, 5):
            for k in (1, 2, 3):
                self.assertEqual(self.b(p, k), ["drop", "pow-brk-both"], (p, k))
            self.assertEqual(self.b(p, 4), ["drop", "brk-range"], p)

    def test_out_of_range_is_unavailable(self):
        self.assertEqual(self.b(6, 0), ["drop", "pow-range"])
        self.assertEqual(self.b(-1, 0), ["drop", "pow-range"])
        self.assertEqual(self.b(0, -1), ["drop", "brk-range"])
        self.assertEqual(self.b(0, 0, rev=2), ["drop", "rev-range"])

    def test_an_unexpected_layout_is_unavailable(self):
        self.assertEqual(self.b(0, 0, brk_n=3, eb_n=4), ["drop", "cl-layout"])
        self.assertEqual(self.b(0, 0, brk_n=2, eb_n=4), ["drop", "cl-layout"])
        self.assertEqual(self.b(0, 0, brk_n=1, eb_n=2), ["drop", "cl-layout"])
        self.assertEqual(self.b(0, 0, brk_n=0, eb_n=1), ["drop", "layout-range"])
        self.assertEqual(self.b(0, 0, brk_n=2, eb_n=0), ["drop", "layout-range"])

    def test_missing_values_are_unavailable(self):
        self.assertEqual(build(ONE, CL, None, 0, 0, 5, 2, 3, False, 0), ["drop", "rev-missing"])
        self.assertEqual(build(ONE, CL, 1, None, 0, 5, 2, 3, False, 0), ["drop", "pow-missing"])
        self.assertEqual(build(ONE, CL, 1, 0, None, 5, 2, 3, False, 0), ["drop", "brk-missing"])
        self.assertEqual(build(ONE, CL, 1, 0, 0, 5, None, 3, False, 0), ["drop", "layout-missing"])
        self.assertEqual(build(ONE, CL, 1, 0, 0, 5, 2, None, False, 0), ["drop", "layout-missing"])
        self.assertEqual(build(ONE, CL, 1, 0, 0, 5, 2, 3, None, 0), ["drop", "hold-missing"])

    def test_cl_with_the_holding_speed_brake_is_built(self):
        # A4 of the 24 combinations: run / holding speed / service / emergency, with and without the independent setting
        for hold_n in (0, -5):
            self.assertEqual([self.b(0, k, hold=True, hold_n=hold_n)[3] for k in range(4)], ["運転:0:3", "抑速:1:3", "常用:2:3", "非常:3:3"])
            self.assertEqual(self.b(0, 0, hold=True, hold_n=hold_n)[5], "後_切_前:運転_P1_P2_P3_P4_P5:運転_抑速_常用_非常:")
            self.assertEqual(self.b(3, 0, hold=True, hold_n=hold_n)[2], "P3:3")
        self.assertEqual(self.b(1, 1, hold=True), ["drop", "pow-brk-both"])

    def test_the_holding_speed_notch_count_is_not_used_by_cl(self):
        for hold_n in (None, 0, -5, 5):
            self.assertEqual(self.b(0, 0, hold_n=hold_n), self.b(0, 0))
        self.assertEqual(self.b(-1, 0, hold_n=-5), ["drop", "pow-range"])


class E_TheTableAsAWhole(unittest.TestCase):
    def test_every_ok_case_obeys_the_wire_shape(self):
        cases = ref.all_cases()
        self.assertGreater(len(cases), 1500)
        for c in cases:
            if c["out"][0] != "ok":
                continue
            rev, pow_, brk, htype, alltxt = c["out"][1:]
            for text in (rev, pow_, brk, htype, alltxt):
                self.assertNotIn(",", text, c)
                self.assertNotIn("\n", text, c)
            self.assertEqual(len(rev.split(":")), 2, c)
            self.assertEqual(len(pow_.split(":")), 2, c)
            self.assertEqual(len(brk.split(":")), 3, c)
            self.assertEqual(len(alltxt.split(":")), 4, c)
            self.assertLess(len(alltxt), 1000, c)                    # even the largest supported layout (99 + 99 + 99 texts) stays one small datagram part

    def test_h_texts_only_for_the_independent_notches_of_a_two_lever_cab(self):
        for c in ref.all_cases():
            if c["out"][0] != "ok":
                continue
            htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n = c["in"]
            pow_text = c["out"][2].split(":")[0]
            hold_texts = c["out"][5].split(":")[3]
            if pow_ < 0:
                self.assertEqual(htype, TWO, c)                          # any brake kind, with or without the holding speed brake (LI2 final)
                self.assertEqual(pow_text, "H%d" % -pow_, c)
                self.assertLessEqual(-pow_, -hold_n, c)
            else:
                self.assertNotRegex(pow_text, r"^H", c)
            if hold_texts:
                self.assertEqual(htype, TWO, c)
                self.assertEqual(hold_texts, "_".join("H%d" % i for i in range(1, -hold_n + 1)), c)
            else:
                # no holding speed texts: not an independent car, or no notches (0), or a value that is not a count (unreadable, above 0, below -99)
                self.assertTrue(htype == ONE or hold_n is None or hold_n >= 0 or hold_n < -99, c)

    def test_the_brake_column_never_shows_h(self):
        for c in ref.all_cases():
            if c["out"][0] == "ok":
                self.assertNotRegex(c["out"][3].split(":")[0], r"^H", c)

    def test_the_holding_speed_brake_word_only_at_brake_position_one_of_a_hold_car(self):
        for c in ref.all_cases():
            if c["out"][0] != "ok":
                continue
            hold = c["in"][8]
            brk = c["in"][4]
            word = c["out"][3].split(":")[0]
            self.assertEqual(word == HOLD_BRAKE, bool(hold) and brk == 1, c)


class H_RealMachineSign(unittest.TestCase):
    """The LI2 candidate 0.3.0.0 FAILED on the real machine: cab=TwoLeverCab brake=Smee powN=5 brkN=8 ebN=9 hold=0 b67=7, first Tick rev=0 pow=0 brk=9, then POW -1..-5.
    The host reports NotchInfo.HoldingSpeedNotchCount NEGATED (the BVE5 vehicle loader keeps -n; the handle is clamped to Min(Max(input, -n), power notches)),
    so five independent notches read -5. The first candidate expected +5 (the sign was assumed), read -5 as 'hold-range' and dropped every Tick."""

    def r(self, pow_, brk=0, rev=1, hold_n=-5):
        return build(TWO, SMEE, rev, pow_, brk, 5, 8, 9, False, hold_n)

    def test_the_first_tick_of_the_real_car_is_built(self):
        out = self.r(0, brk=9, rev=0, hold_n=-5)
        self.assertEqual(out[0], "ok")
        self.assertEqual(out[1:5], ["切:0", "P0:0", "EB:9:9", "2"])
        self.assertEqual(out[5], "後_切_前:P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:H1_H2_H3_H4_H5")

    def test_every_position_of_the_real_car(self):
        self.assertEqual([self.r(p)[2] for p in range(-5, 6)], ["H5:-5", "H4:-4", "H3:-3", "H2:-2", "H1:-1", "P0:0", "P1:1", "P2:2", "P3:3", "P4:4", "P5:5"])
        self.assertEqual(self.r(-6), ["drop", "pow-range"])

    def test_the_positive_number_of_the_first_candidate_is_not_a_count(self):
        self.assertEqual(self.r(-1, hold_n=5), ["drop", "hold-range"])
        self.assertEqual(self.r(0, hold_n=5)[0:3], ["ok", "前:1", "P0:0"])               # position-level fallback: POW 0 and above are still built
        self.assertEqual(self.r(0, hold_n=5)[5], "後_切_前:P0_P1_P2_P3_P4_P5:B0_B1_B2_B3_B4_B5_B6_B7_B8_EB:")

    def test_the_value_range(self):
        self.assertEqual(self.r(-1, hold_n=-1)[2], "H1:-1")
        self.assertEqual(self.r(-2, hold_n=-1), ["drop", "pow-range"])
        self.assertEqual(self.r(-99, hold_n=-99)[2], "H99:-99")
        self.assertEqual(self.r(-1, hold_n=-100), ["drop", "hold-range"])
        self.assertEqual(self.r(-1, hold_n=1), ["drop", "hold-range"])
        self.assertEqual(self.r(-1, hold_n=None), ["drop", "holdn-missing"])
        self.assertEqual(self.r(-1, hold_n=0), ["drop", "pow-range"])

    def test_an_unusable_count_takes_only_the_h_positions_away(self):
        for hold_n in (None, 5, 100, -100):
            for p in range(0, 6):
                out = self.r(p, hold_n=hold_n)
                self.assertEqual(out[0], "ok", (hold_n, p))
                self.assertEqual(out[2], "P%d:%d" % (p, p))
                self.assertEqual(out[5].split(":")[3], "", hold_n)                  # no count is guessed: no holding speed texts
            for p in (-1, -3, -5):
                self.assertEqual(self.r(p, hold_n=hold_n)[0], "drop", (hold_n, p))
            self.assertEqual(self.r(6, hold_n=hold_n), ["drop", "pow-range"])

    def test_the_power_notch_count_is_never_the_holding_speed_count(self):
        self.assertEqual(self.r(-1, hold_n=0), ["drop", "pow-range"])                # powN is 5, the count 0: no H1
        self.assertEqual(self.r(-3, hold_n=-2), ["drop", "pow-range"])

    def test_the_holding_speed_brake_and_the_independent_notches_are_not_mixed(self):
        hb = build(TWO, SMEE, 1, 0, 1, 5, 8, 9, True, -5)
        self.assertEqual(hb[3], HOLD_BRAKE + ":1:9")
        self.assertEqual(hb[5].split(":")[2], "B0_抑速_B1_B2_B3_B4_B5_B6_B7_EB")      # the BRAKE feature: the hold word is in the brake list, never an H text there
        self.assertEqual(hb[5].split(":")[3], "H1_H2_H3_H4_H5")                      # the independent notches are the POWER side: their texts follow the count (LI2 final: both at once)
        self.assertEqual(build(TWO, SMEE, 1, -1, 0, 5, 8, 9, True, -5)[2:4], ["H1:-1", "B0:0:9"])     # LI2 final: both features at once
        self.assertEqual(self.r(0, brk=1)[3], "B1:1:9")                              # the independent car: brake position 1 is the ordinary B1

    def test_the_real_overlay_chain_accepts_the_real_car(self):
        # the lines of the real car are valid telemetry lines for the UNCHANGED reader
        for p in range(-5, 6):
            parsed = tc.parse_telemetry(li1.legacy_line(95, self.r(p), "0.0", "490.0", btype="Smee"))
            self.assertTrue(parsed.valid, p)
            self.assertIn("handle", parsed.tokens, p)


# ---------------------------------------------------------------------------------------------------------------------------------------
BRAKE_WORD = {ECB: "Ecb", SMEE: "Smee", CL: "Cl"}


class F_RealOverlay(li1.RealOverlayCase):
    """The real Overlay (offscreen) reads the new lines with the UNCHANGED reader and draws them with the UNCHANGED HUD."""

    def line(self, sid, out, btype):
        return li1.legacy_line(sid, out, "0.0", "490.0", btype=btype)

    def test_the_holding_speed_brake_is_read_and_drawn(self):
        o = self.overlay
        for brk, word in ((0, "B0"), (1, HOLD_BRAKE), (2, "B1"), (8, "B7"), (9, "EB")):
            self.feed(self.line(71, build(TWO, ECB, 1, 0, brk, 5, 8, 9, True, 0), "Ecb"))
            self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max, o.is_single_handle), (word, brk, 9, False))
            self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown")
            texts = self.render()
            self.assertIn(word, texts)
            self.assertNotIn("H1", texts)
        self.assertEqual(o.all_brk_texts, ["B0", HOLD_BRAKE, "B1", "B2", "B3", "B4", "B5", "B6", "B7", "EB"])

    def test_the_holding_speed_brake_is_drawn_in_the_service_brake_colour_not_the_emergency_one(self):
        o = self.overlay
        self.feed(self.line(72, build(TWO, ECB, 1, 0, 1, 5, 8, 9, True, 0), "Ecb"))
        self.assertLess(o.bve_brk_notch, o.bve_brk_max)
        self.assertNotIn("非常", o.bve_brk_text)
        self.assertNotIn("EB", o.bve_brk_text.upper())

    def test_the_independent_holding_speed_is_read_and_drawn(self):
        o = self.overlay
        for n in range(1, 6):
            self.feed(self.line(73, build(TWO, SMEE, 1, -n, 0, 5, 8, 9, False, -5), "Smee"))
            self.assertEqual((o.bve_pow_text, o.bve_pow_notch), ("H%d" % n, -n))
            self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max), ("B0", 0, 9))
            self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown")
            texts = self.render()
            self.assertIn("H%d" % n, texts)
            self.assertIn("B0", texts)
        self.feed(self.line(73, build(TWO, SMEE, 1, 0, 0, 5, 8, 9, False, -5), "Smee"))
        self.assertEqual((o.bve_pow_text, o.bve_pow_notch), ("P0", 0))
        self.assertEqual(o.all_brk_texts, ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "EB"])

    def test_below_the_formal_count_the_handle_row_is_unavailable_and_nothing_old_is_drawn(self):
        o = self.overlay
        self.feed(self.line(74, build(TWO, SMEE, 1, -2, 0, 5, 8, 9, False, -5), "Smee"))
        self.assertIn("H2", self.render())
        bad = build(TWO, SMEE, 1, -6, 0, 5, 8, 9, False, -5)
        self.assertEqual(bad, ["drop", "pow-range"])
        self.feed(li1.legacy_line(74, None, "0.0", "490.0", btype="Smee"))           # the sender then leaves the whole group (and its token) out
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")
        self.assertNotIn("H2", self.render())

    def test_the_one_lever_cab_with_a_holding_speed_setting_is_an_ordinary_one_lever_handle(self):
        o = self.overlay
        self.feed(self.line(75, build(ONE, SMEE, 1, 3, 0, 5, 8, 9, False, -5), "Smee"))
        self.assertTrue(o.is_single_handle)
        self.assertEqual(o.all_brk_texts, ["N", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "EB"])
        self.assertIn("P3", self.render())
        self.feed(self.line(75, build(ONE, SMEE, 1, 0, 4, 5, 8, 9, False, -5), "Smee"))
        self.assertIn("B4", self.render())

    def test_the_one_lever_cl_handle_is_read_and_drawn(self):
        o = self.overlay
        self.feed(self.line(76, build(ONE, CL, 1, 3, 0, 5, 2, 3, False, 0), "Cl"))
        self.assertTrue(o.is_single_handle)
        self.assertEqual((o.bve_pow_text, o.bve_pow_notch), ("P3", 3))
        self.assertEqual(o.all_brk_texts, ["運転", "重なり", "常用", "非常"])
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown")
        self.assertIn("P3", self.render())
        self.feed(self.line(76, build(ONE, CL, 1, 0, 0, 5, 2, 3, False, 0), "Cl"))
        self.assertEqual(o.bve_pow_text, "運転")
        self.assertIn("運転", self.render())
        for brk, word in ((1, "重なり"), (2, "常用"), (3, "非常")):
            self.feed(self.line(76, build(ONE, CL, 1, 0, brk, 5, 2, 3, False, 0), "Cl"))
            self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max), (word, brk, 3))
            self.assertIn(word, self.render())

    def test_a_group_that_cannot_be_built_is_not_drawn(self):
        o = self.overlay
        self.feed(li1.legacy_line(77, None, "0.0", "490.0", btype="Cl"))
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")

    def test_all_24_combinations_are_read_and_drawn_one_generation_each(self):
        import telemetry_gate as tg
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        for n, row in enumerate(ref.matrix_rows(), start=1):
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            o.telemetry_gate.on_generation(n)
            # a position in the middle of the power side (the first H notch on a two-lever cab with notches), brake at rest
            pow_ = row["pow_min"] if row["pow_min"] < 0 else 0
            out = build(htype, brake, 1, pow_, 0, pow_n, brk_n, eb_n, hold, hold_n)
            self.feed(self.line(100 + n, out, BRAKE_WORD[brake]))
            self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "shown", row["name"])
            self.assertEqual(o.is_single_handle, htype == ONE, row["name"])
            self.assertEqual(o.bve_pow_text, row["pow_texts"][str(pow_)].split(":")[0] if htype == TWO else o.bve_pow_text, row["name"])
            self.assertEqual("_".join(o.all_brk_texts), row["alltxt"].split(":")[2], row["name"])
            # the brake side: the first brake position (the holding speed word, lap or B1) and the emergency position
            for brk in (1, eb_n):
                out = build(htype, brake, 1, 0, brk, pow_n, brk_n, eb_n, hold, hold_n)
                self.feed(self.line(100 + n, out, BRAKE_WORD[brake]))
                self.assertEqual((o.bve_brk_text, o.bve_brk_notch, o.bve_brk_max), (row["brk_texts"][str(brk)], brk, eb_n), row["name"])
                self.assertIn(row["brk_texts"][str(brk)], self.render(), row["name"])

    def test_a_new_vehicle_replaces_the_holding_speed_layout(self):
        import telemetry_gate as tg
        o = self.overlay
        o.telemetry_gate = tg.TelemetryGate(strict=True)
        o.telemetry_gate.on_generation(1)
        self.feed(self.line(81, build(TWO, ECB, 1, 0, 1, 5, 8, 9, True, 0), "Ecb"))
        self.assertEqual(o.all_brk_texts[1], HOLD_BRAKE)
        o.telemetry_gate.on_generation(2)
        self.feed(self.line(82, build(TWO, ECB, 1, 0, 1, 5, 8, 9, False, 0), "Ecb"))
        self.assertEqual(o.all_brk_texts, ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "EB"])
        self.assertEqual(o.bve_brk_text, "B1")
        o.telemetry_gate.on_generation(3)
        self.feed(li1.legacy_line(83))                                   # a car whose group cannot be built: nothing of the old car is left
        self.assertEqual(self.hud_ui.hud_item_state(o, "handle"), "unavailable")
        self.assertEqual(o.all_brk_texts, [])

    def test_the_wire_line_is_accepted_by_the_contract_parser(self):
        for out, btype in ((build(TWO, ECB, 1, 0, 1, 5, 8, 9, True, 0), "Ecb"), (build(TWO, SMEE, 1, -3, 0, 5, 8, 9, False, -5), "Smee"),
                           (build(ONE, CL, 1, 0, 2, 5, 2, 3, False, 0), "Cl")):
            parsed = tc.parse_telemetry(self.line(91, out, btype))
            self.assertTrue(parsed.valid)
            self.assertIn("handle", parsed.tokens)


class I_The24Combinations(unittest.TestCase):
    """Every one of the 2 x 3 x 2 x 2 = 24 combinations (cab x brake x HoldingSpeedNotchCount x HoldingSpeedBrake) observed on the real BVE5, spelled out one by one
    (ref.matrix_rows() lists every text; ref.expected_handle is the rule). Ecb and Smee are separate rows. hold_n is the HOST value (0 or -5)."""

    ROWS = ref.matrix_rows()

    def test_there_are_exactly_24_distinct_combinations_with_ecb_and_smee_apart(self):
        self.assertEqual(len(self.ROWS), 24)
        self.assertEqual(len({r["name"] for r in self.ROWS}), 24)
        keys = {(r["in"][0], r["in"][1], r["in"][2], r["in"][3]) for r in self.ROWS}
        self.assertEqual(keys, {(h, b, hb, hn) for h in (ONE, TWO) for b in (ECB, SMEE, CL) for hb in (False, True) for hn in (0, -5)})
        for h in (ONE, TWO):
            for hb in (False, True):
                for hn in (0, -5):
                    self.assertEqual(len([r for r in self.ROWS if r["in"][:1] + r["in"][2:4] == [h, hb, hn] and r["in"][1] == ECB]), 1)
                    self.assertEqual(len([r for r in self.ROWS if r["in"][:1] + r["in"][2:4] == [h, hb, hn] and r["in"][1] == SMEE]), 1)

    def test_every_position_of_every_combination_matches_the_spelled_out_table(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            name = row["name"]
            for pow_ in range(row["pow_min"], pow_n + 1):                       # POW side at brake rest
                out = build(htype, brake, 1, pow_, 0, pow_n, brk_n, eb_n, hold, hold_n)
                self.assertEqual(out[0], "ok", (name, pow_))
                self.assertEqual(out[2].rsplit(":", 1)[0], row["pow_texts"][str(pow_)], (name, pow_))
                self.assertEqual(out[4], row["htype"], name)
                self.assertEqual(out[5], row["alltxt"], name)
            for brk in range(0, eb_n + 1):                                      # BRK side at power 0 (including the emergency notch)
                out = build(htype, brake, 1, 0, brk, pow_n, brk_n, eb_n, hold, hold_n)
                self.assertEqual(out[0], "ok", (name, brk))
                self.assertEqual(out[3], "%s:%d:%d" % (row["brk_texts"][str(brk)], brk, eb_n), (name, brk))
                self.assertEqual(out[5], row["alltxt"], name)

    def test_the_regular_series_of_every_combination_is_never_dropped(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            drops = 0
            sent = 0
            for rev in (-1, 0, 1):
                for pow_ in range(row["pow_min"], pow_n + 1):
                    sent += 1
                    drops += build(htype, brake, rev, pow_, 0, pow_n, brk_n, eb_n, hold, hold_n)[0] != "ok"
                for brk in range(0, eb_n + 1):
                    sent += 1
                    drops += build(htype, brake, rev, 0, brk, pow_n, brk_n, eb_n, hold, hold_n)[0] != "ok"
                if htype == TWO:                                                # a two-lever cab may hold power and brake at the same time
                    sent += 1
                    drops += build(htype, brake, rev, pow_n, eb_n, pow_n, brk_n, eb_n, hold, hold_n)[0] != "ok"
            self.assertEqual(drops, 0, row["name"])
            self.assertGreater(sent, 20)

    def test_the_unsafe_values_of_every_combination_are_unavailable(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            name = row["name"]

            def b(rev=1, pow_=0, brk=0, **kw):
                args = dict(pow_n=pow_n, brk_n=brk_n, eb_n=eb_n, hold=hold, hold_n=hold_n)
                args.update(kw)
                return build(htype, brake, rev, pow_, brk, args["pow_n"], args["brk_n"], args["eb_n"], args["hold"], args["hold_n"])

            self.assertEqual(b(pow_=pow_n + 1), ["drop", "pow-range"], name)            # above the power notches
            self.assertEqual(b(pow_=row["pow_min"] - 1), ["drop", "pow-range"], name)    # below the lowest position (one lever: below 0; two lever: below the host count)
            self.assertEqual(b(brk=eb_n + 1), ["drop", "brk-range"], name)              # beyond the emergency notch
            self.assertEqual(b(brk=-1), ["drop", "brk-range"], name)
            self.assertEqual(b(rev=2), ["drop", "rev-range"], name)
            self.assertEqual(b(rev=None), ["drop", "rev-missing"], name)
            self.assertEqual(b(pow_=None), ["drop", "pow-missing"], name)
            self.assertEqual(b(brk=None), ["drop", "brk-missing"], name)
            self.assertEqual(b(pow_n=None), ["drop", "layout-missing"], name)
            self.assertEqual(b(hold=None), ["drop", "hold-missing"], name)
            if htype == ONE:
                self.assertEqual(b(pow_=1, brk=1), ["drop", "pow-brk-both"], name)      # a single handle cannot hold both
                self.assertEqual(b(pow_=pow_n, brk=eb_n), ["drop", "pow-brk-both"], name)
            else:
                self.assertEqual(b(pow_=1, brk=1)[0], "ok", name)                       # two levers can
            if brake == CL:
                self.assertEqual(b(brk_n=3, eb_n=4), ["drop", "cl-layout"], name)
            else:
                self.assertEqual(b(eb_n=eb_n + 1), ["drop", "eb-layout"], name)

    def test_a_one_lever_cab_never_shows_h_whatever_the_setting(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            if htype != ONE:
                continue
            # the setting alone never changes the display: same texts as the same car without it, no H text, no holding speed texts, pow < 0 stays unavailable
            same = build(htype, brake, 1, 2, 0, pow_n, brk_n, eb_n, hold, 0)
            self.assertEqual(build(htype, brake, 1, 2, 0, pow_n, brk_n, eb_n, hold, hold_n), same, row["name"])
            self.assertEqual(same[5].split(":")[3], "", row["name"])
            self.assertEqual(build(htype, brake, 1, -1, 0, pow_n, brk_n, eb_n, hold, hold_n), ["drop", "pow-range"], row["name"])

    def test_a_two_lever_cab_with_notches_shows_h1_to_hn_in_every_brake_kind_and_with_the_holding_speed_brake(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            if htype != TWO:
                continue
            if hold_n == 0:
                self.assertEqual(build(htype, brake, 1, -1, 0, pow_n, brk_n, eb_n, hold, hold_n), ["drop", "pow-range"], row["name"])
                self.assertEqual(row["alltxt"].split(":")[3], "", row["name"])
            else:
                self.assertEqual([build(htype, brake, 1, -k, 0, pow_n, brk_n, eb_n, hold, hold_n)[2] for k in range(1, 6)], ["H1:-1", "H2:-2", "H3:-3", "H4:-4", "H5:-5"], row["name"])
                self.assertEqual(row["alltxt"].split(":")[3], "H1_H2_H3_H4_H5", row["name"])

    def test_the_host_count_other_values_in_every_two_lever_combination(self):
        for row in self.ROWS:
            htype, brake, hold, hold_n, pow_n, brk_n, eb_n = row["in"]
            if htype != TWO or hold_n == 0:
                continue
            for n in (-2, -1, -99):
                out = build(htype, brake, 1, n, 0, pow_n, brk_n, eb_n, hold, n)
                self.assertEqual(out[2], "H%d:%d" % (-n, n), (row["name"], n))
            for bad in (None, 5, 100, -100):                                    # not a count: only the H positions go away
                self.assertEqual(build(htype, brake, 1, 0, 0, pow_n, brk_n, eb_n, hold, bad)[0], "ok", (row["name"], bad))
                self.assertEqual(build(htype, brake, 1, -1, 0, pow_n, brk_n, eb_n, hold, bad)[0], "drop", (row["name"], bad))

    def test_the_golden_file_is_the_spelled_out_table(self):
        golden = os.path.join(TESTS, "legacy_input_matrix24.json")
        import json
        with open(golden, encoding="utf-8") as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(ref.matrix_rows(), ensure_ascii=False)))


# ---------------------------------------------------------------------------------------------------------------------------------------
class G_StaticGuards(unittest.TestCase):
    PRODUCT = ("main.py", "network.py", "hud_ui.py", "scoring_logic.py", "managed_hud.py", "managed_mode.py", "managed_state.py", "telemetry_gate.py",
               "telemetry_contract.py", "config.py", "utils.py", "menu_ui.py")

    def test_the_python_product_has_no_holding_speed_logic(self):
        # the handle texts come from the sender; the reader / HUD / scoring know nothing of the holding speed handles (no branch on the H-texts or on HoldingSpeed*)
        for name in self.PRODUCT:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            src = read_text(path)
            self.assertIsNone(re.search(r"""['"]H[0-9]['"]|startswith\(['"]H['"]\)|HoldingSpeed""", src), name)

    def test_the_telemetry_vocabulary_is_unchanged(self):
        self.assertEqual(tc.TOKEN_KEYS["handle"], ("REV", "POW", "BRK", "HTYPE", "ALLTXT"))
        self.assertEqual(tc.TOKEN_KEYS["bcp"], ("BCP",))
        self.assertEqual(tc.TOKEN_KEYS["bpp"], ("BPP",))


if __name__ == "__main__":
    unittest.main()
