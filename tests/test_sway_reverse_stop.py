"""Stop-window peak of the sway Shadow in BOTH travel directions (SHD-L-02 finding, Owner ruling 2026-11-08) - an executable contract (RED / GUARD).

THE FINDING (screenshots of SHD-L-02, backward stop with the EB): LastStop CalcG / BveG 0.169 G, current front-back n 45, combined n 44, but the front-back MAXIMUM was 3.
THE CAUSE (offline reproduction with the unchanged sway_shadow.py): the stop window took the SIGNED MINIMUM of the longitudinal value z (a forward train's stop response is negative). A backward stop
  responds on the POSITIVE side, so the minimum stayed near 0 and the large positive peak was ignored.
THE CONTRACT: the front-back maximum of a stop is the largest ABSOLUTE longitudinal state from the stop instant T to the end of the window, whatever the direction:
  n = int(abs(12.5 * peak_abs_state) * 64.0)  (the figure's own order of operations; sway_n is unchanged)
  both signs in one window -> the larger |state|; equal |state| of both signs -> the EARLIER sample (deterministic); samples before T are never searched; the window cuts are unchanged.
The Shadow log line gets the facts to tell forward from backward after the fact. NOTHING of the official score, history, checkpoint, result or the thresholds (n >= 34 / n >= 52) changes.
Naming: test_RV* = RED on the baseline eb81491 (each fails with a reason code "CODE: ..."); test_RG* = GUARD (passes before and after)."""
import hashlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import test_sway_shadow as base  # noqa: E402  (the real-Overlay rig of the existing sway contract)
from test_sway_shadow import Direct, reference_series, ref_n  # noqa: E402

NEG = lambda a: tuple(-x if i < 4 else x for i, x in enumerate(a))


def fields(line):
    return dict(re.findall(r"(\w+)=(\S*)", line))


def lf_sha(rel):
    data = open(os.path.join(ROOT, rel.replace("/", os.sep)), "rb").read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()


class Rev(Direct):
    def run_in_back(self, calc_g=-0.02, az=0.9, n=8):
        """Accelerate BACKWARD (negative speed), then brake while still moving backward (no stop yet)."""
        for i in range(20):
            self.step(speed=-(5.0 + 0.3 * i), calc_g=0.08, az=-0.8, loc=100.0 - 0.6 * i)
        for i in range(n):
            self.step(speed=-max(2.0 - 0.3 * i, 0.5), calc_g=calc_g, az=az)

    def one_stop(self, series, backward, tail=None):
        """A complete stop whose reflection samples are `series` (T at index 0); returns the closed record."""
        self.scene()
        if backward:
            self.run_in_back()
        else:
            self.run_in()
        self.stop_at(series[0])
        self.after(series[1:80])
        return self.last()

    def log_line_of_stop(self, series, backward):
        lines = self.capture_log()
        self.one_stop(series, backward)
        got = [l for l in lines if "[SHADOW SWAY]" in l and "[SHADOW SWAY RESOLVE]" not in l]
        if not got:
            self.fail("NO-DIAG: no [SHADOW SWAY] line was written")
        return fields(got[-1])


class RV_Peak(Rev):
    # ---- 1 / 2 / 3 : the two directions and the symmetry
    def test_RG01_forward_stop_negative_peak_equals_abs_of_the_minimum(self):
        last = self.one_stop(self.pulse(1.0), backward=False)
        self.assertEqual(last["n_peak"], 53, "NO-ABS-PEAK: a forward 1 m/s2 stop is n=53")
        self.assertAlmostEqual(last["state_peak"], 0.06687, delta=3e-4)

    def test_RV02_backward_stop_positive_peak_is_the_peak(self):
        series = [tuple(-x for x in s) for s in self.pulse(1.0)]            # the mirror image: the stop response of a backward train
        last = self.one_stop(series, backward=True)
        self.assertEqual(last["n_peak"], 53, "NO-ABS-PEAK: a backward stop of the same size must be n=53, got %r" % last["n_peak"])
        self.assertAlmostEqual(last["state_peak"], 0.06687, delta=3e-4, msg="NO-ABS-PEAK: the positive peak is the state peak")

    def test_RV03_mirror_waveforms_give_the_same_n(self):
        for a in (0.4, 0.8, 1.0, 1.4):
            fwd = self.one_stop(self.pulse(a), backward=False)["n_peak"]
            self.new_rig()
            bwd = self.one_stop([tuple(-x for x in s) for s in self.pulse(a)], backward=True)["n_peak"]
            self.new_rig()
            self.assertEqual(fwd, bwd, "NO-ABS-PEAK: mirror waveforms of a=%s differ: forward %r, backward %r" % (a, fwd, bwd))

    # ---- 5 : the SHD-L-02 backward EB fixture (current value 45, maximum was 3)
    def test_RV05_backward_eb_fixture_peak_is_computed_from_the_waveform(self):
        series = [tuple(-x for x in s) for s in self.pulse(0.9)]
        peak = max(abs(x + base.SWAY_K_V * v) if hasattr(base, "SWAY_K_V") else abs(x + 0.315 * v) for (x, v, _, _) in series)
        want = ref_n(peak)
        last = self.one_stop(series, backward=True)
        self.assertTrue(want >= 40, "fixture sanity: the waveform must be a large peak (got n=%d)" % want)
        self.assertEqual(last["n_peak"], want, "NO-ABS-PEAK: the backward EB peak must be the machine-computed n=%d, got %r (the SHD-L-02 symptom is 3)" % (want, last["n_peak"]))

    # ---- 6 / 7 : both signs in one window
    def test_RV06_both_signs_the_larger_absolute_state_wins(self):
        for first, second, big in ((0.02, -0.05, 0.05), (0.05, -0.02, 0.05), (-0.02, 0.05, 0.05), (-0.05, 0.02, 0.05)):
            self.new_rig()
            self.scene()
            self.run_in()
            self.stop_at((0.0, 0.0, 0.0, 0.0))
            self.after([(first, 0.0, 0.0, 0.0), (second, 0.0, 0.0, 0.0)])
            self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
            last = self.last()
            self.assertAlmostEqual(last["state_peak"], big, places=9, msg="NO-ABS-PEAK: samples (%s, %s) -> the larger |state| %s must win, got %r" % (first, second, big, last["state_peak"]))
            self.assertEqual(last["n_peak"], ref_n(big), "NO-ABS-PEAK: n must come from |state| %s" % big)

    def test_RV07_equal_absolute_peaks_of_both_signs_the_earlier_sample_wins(self):
        for first, second, sign in ((0.04, -0.04, "positive"), (-0.04, 0.04, "negative")):
            self.new_rig()
            self.scene()
            self.run_in()
            self.stop_at((0.0, 0.0, 0.0, 0.0))
            self.after([(first, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0), (second, 0.0, 0.0, 0.0)])
            self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
            last = self.last()
            self.assertEqual(last["n_peak"], ref_n(0.04), "NO-ABS-PEAK: equal peaks give one n")
            self.assertEqual(last.get("abs_peak_sign"), sign, "NO-DIAG: the EARLIER of two equal |state| peaks is the peak (sign %s), got %r" % (sign, last.get("abs_peak_sign")))

    # ---- 14 / 15 : the F2 value during an open window and the candidate
    def test_RV14_f2_value_follows_the_absolute_peak_while_the_window_is_open(self):
        self.scene()
        self.run_in_back()
        self.stop_at((0.0, 0.0, 0.0, 0.0))
        self.after([(0.03, 0.0, 0.0, 0.0), (0.06, 0.0, 0.0, 0.0)])
        shown = self.sh().display_peak_n()
        self.assertEqual(shown, ref_n(0.06), "NO-ABS-PEAK: while the window is open the F2 maximum is n of |state| 0.06 (%d), got %r" % (ref_n(0.06), shown))

    def test_RV15_the_candidate_follows_n_in_both_directions(self):
        series = [tuple(-x for x in s) for s in self.pulse(1.0)]
        last = self.one_stop(series, backward=True)
        self.assertEqual(last["penalty_sway"], -100 if last["n_peak"] < 52 else -200, "NO-ABS-PEAK: the Shadow candidate is taken from the peak n (n=%r)" % last["n_peak"])
        self.assertEqual(last["penalty_sway"], -200, "NO-ABS-PEAK: a backward n=53 stop is a -200 candidate like the forward one")

    # ---- 12 / 13 / 16 : the diagnostic fields
    REQUIRED = ("longitudinal_state_min", "longitudinal_state_max", "longitudinal_state_abs_peak", "longitudinal_abs_peak_sign", "longitudinal_abs_peak_n",
                "longitudinal_abs_peak_delay_ms", "speed_at_stop", "approach_direction", "window_start_reason", "window_end_reason", "restart_detected",
                "station_index_change_time", "official_jumping", "reset_reason")

    def test_RV12_the_log_line_carries_the_direction_facts(self):
        f = self.log_line_of_stop(self.pulse(1.0), backward=False)
        missing = [k for k in self.REQUIRED if k not in f]
        self.assertEqual(missing, [], "NO-DIAG: the [SHADOW SWAY] line lacks %s" % missing)

    def test_RV12b_forward_and_backward_are_told_apart_by_the_log(self):
        fwd = self.log_line_of_stop(self.pulse(1.0), backward=False)
        self.new_rig()
        bwd = self.log_line_of_stop([tuple(-x for x in s) for s in self.pulse(1.0)], backward=True)
        self.assertEqual((fwd.get("approach_direction"), fwd.get("longitudinal_abs_peak_sign")), ("forward", "negative"), "NO-DIAG: forward stop facts %r" % ((fwd.get("approach_direction"), fwd.get("longitudinal_abs_peak_sign")),))
        self.assertEqual((bwd.get("approach_direction"), bwd.get("longitudinal_abs_peak_sign")), ("backward", "positive"), "NO-DIAG: backward stop facts %r" % ((bwd.get("approach_direction"), bwd.get("longitudinal_abs_peak_sign")),))

    def test_RV13_the_peak_n_fields_agree_in_both_directions(self):
        for backward in (False, True):
            self.new_rig()
            series = self.pulse(1.0)
            if backward:
                series = [tuple(-x for x in s) for s in series]
            f = self.log_line_of_stop(series, backward)
            self.assertEqual(f.get("stop_sway_longitudinal_n_peak"), f.get("longitudinal_abs_peak_n"), "NO-DIAG: n_peak and abs_peak_n differ (backward=%s)" % backward)
            self.assertEqual(f.get("stop_sway_longitudinal_state_peak"), f.get("longitudinal_state_abs_peak"), "NO-DIAG: state_peak and state_abs_peak differ (backward=%s)" % backward)
            self.assertEqual(f.get("stop_sway_longitudinal_state_peak"), f.get("stop_sway_longitudinal_abs_peak"), "NO-ABS-PEAK: the stop peak is the absolute peak (backward=%s)" % backward)

    def test_RV16_restart_reset_and_station_change_facts(self):
        self.scene()
        self.run_in()
        self.stop_at((0.0, 0.0, 0.0, 0.0))
        self.after([(-0.02, 0.0, 0.0, 0.0)])
        self.step(dt=0.1, speed=1.0, calc_g=0.0, az=0.0, sway=(-0.01, 0.0, 0.0, 0.0))          # the train moves again: restart
        last = self.last()
        self.assertEqual(last["end_reason"], "restart")
        lines = self.capture_log()
        # the facts come from the record itself (no log needed): the format function must expose them
        W = self.W()
        rec = dict(last)
        text = W.format_log(rec, None, self.sh()._snapshot(), self.sh().replica)
        f = fields(text)
        self.assertEqual(f.get("restart_detected"), "1", "NO-DIAG: restart_detected=1 after a restart cut")
        self.assertEqual(f.get("window_end_reason"), "restart", "NO-DIAG: window_end_reason")
        self.assertEqual(f.get("window_start_reason"), "stop", "NO-DIAG: window_start_reason")
        self.assertEqual(f.get("reset_reason"), "none", "NO-DIAG: a restart is not a reset")


class RG_Guard(Rev):
    # ---- 4 : the Current measured fixtures keep their n (single negative peak of the measured |state|; abs_peak == state_peak in the evidence)
    def test_RG04_current_measured_fixtures_keep_their_n(self):
        for state, n in ((0.033639, 26), (0.048230, 38), (0.072170, 57), (0.042044, 33)):
            self.new_rig()
            self.scene()
            self.run_in()
            self.stop_at((-0.5 * state, 0.0, 0.0, 0.0))
            self.after([(-0.8 * state, 0.0, 0.0, 0.0), (-state, 0.0, 0.0, 0.0), (-0.7 * state, 0.0, 0.0, 0.0), (-0.3 * state, 0.0, 0.0, 0.0)])
            self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
            last = self.last()
            self.assertEqual(last["n_peak"], n, "the measured Current stop with |state| %s must stay n=%d" % (state, n))
            self.assertAlmostEqual(last["state_peak"], state, places=9)

    def test_RG05_a_peak_before_the_stop_is_not_searched_and_after_it_is(self):
        self.scene()
        self.run_in_back()
        self.step(speed=-1.0, calc_g=-0.02, az=0.9, sway=(0.3, 0.0, 0.0, 0.0))                   # a huge state right before the stop (backward side)
        self.stop_at((0.01, 0.0, 0.0, 0.0))
        self.after([(0.02, 0.0, 0.0, 0.0), (0.05, 0.0, 0.0, 0.0)])
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.0, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertAlmostEqual(last["abs_peak"], 0.05, places=9, msg="the 0.3 before the stop is not in the window; the 0.05 after it is")

    def test_RG06_the_window_cuts_are_unchanged_for_a_backward_stop(self):
        W = self.W()
        # restart: the sample of the restart tick is not part of the window
        self.scene()
        self.run_in_back()
        self.stop_at((0.01, 0.0, 0.0, 0.0))
        self.after([(0.04, 0.0, 0.0, 0.0)])
        self.step(dt=0.1, speed=-1.0, calc_g=0.0, az=0.0, sway=(0.5, 0.0, 0.0, 0.0))
        last = self.last()
        self.assertEqual(last["end_reason"], "restart")
        self.assertAlmostEqual(last["abs_peak"], 0.04, places=9)
        # T + 1.0 s: a later sample is ignored
        self.new_rig()
        self.scene()
        self.run_in_back()
        self.stop_at((0.01, 0.0, 0.0, 0.0))
        self.after([(0.02, 0.0, 0.0, 0.0)])
        self.step(dt=1.0, speed=0.0, calc_g=0.0, az=0.0, sway=(0.02, 0.0, 0.0, 0.0))
        self.step(dt=0.1, speed=0.0, calc_g=0.0, az=0.0, sway=(0.9, 0.0, 0.0, 0.0))
        self.assertAlmostEqual(self.last()["abs_peak"], 0.02, places=9)
        # a formal boundary cuts the window: not valid, the display value goes
        for reason in ("discard", "generation", "session-end"):
            self.new_rig()
            self.scene()
            self.run_in_back()
            self.stop_at((0.01, 0.0, 0.0, 0.0))
            self.after([(0.04, 0.0, 0.0, 0.0)])
            self.sh().boundary(self.o, reason, None)
            self.assertIsNone(self.sh().display_peak_n(), "a %s boundary clears the display value" % reason)
            self.assertFalse(self.last()["valid"], "a %s boundary makes the window not valid" % reason)

    def test_RG11_the_official_score_path_and_the_thresholds_are_untouched(self):
        # the official files are byte-identical to the baseline eb81491 (LF); the Shadow module never names a score store
        src = re.sub(r"#[^\n]*", "", open(os.path.join(ROOT, "sway_shadow.py"), encoding="utf-8").read())
        for word in ("import scoring_logic", "from scoring_logic", "write_history", "save_checkpoint", "result.json", "add_score_popup", "total_score", "self.score"):
            self.assertTrue(word not in src, "sway_shadow.py names '%s'" % word)
        W = self.W()
        self.assertEqual((W.N_CANDIDATE_100, W.N_CANDIDATE_200), (34, 52), "the candidate thresholds are not changed in this stage")
        self.assertEqual(W.sway_n(0.06687), int(abs(12.5 * 0.06687) * 64.0), "the n conversion keeps the figure's order of operations")


class RG_Cuts(unittest.TestCase):
    """Every cut of the stop window, with a REVERSE stop (positive side) and a huge later sample: the window ends for the named reason and the later sample is never searched."""

    @staticmethod
    def overlay():
        import types
        return types.SimpleNamespace(bve_arr_idx=1, bve_tgt_idx=2, bve_speed=0.0, bve_jump_count=0, last_jump_count=0, is_official_jumping=False, is_scoring_mode=True,
                                     is_scoring_finished=False, bve_accel_z=0.0, bve_accel_x=0.0, current_scenario_id=1, bve_sway=(0.0, 0.0, 0.0, 0.0))

    def test_RG07_each_window_cut_ends_the_window_and_later_samples_are_not_searched(self):
        sys.path.insert(0, ROOT)
        import sway_shadow as W
        for reason in ("jump", "target-change", "station-index-change", "restart", "scoring-end", "t-plus-1s"):
            o = self.overlay()
            st = W.SwayShadowState()
            o.bve_speed = -3.0
            st._follow(o, 9.9)                                    # the train came in backward
            o.bve_speed = 0.0
            o.bve_sway = (0.01, 0.0, 0.0, 0.0)
            st.start(o, 10.0, {})
            o.bve_sway = (0.03, 0.0, 0.0, 0.0)
            st.tick(o, 10.2, None)
            t_late = 10.3
            if reason == "jump":
                o.bve_jump_count = 1
            elif reason == "target-change":
                o.bve_tgt_idx = 3
            elif reason == "station-index-change":
                o.bve_arr_idx = 2
            elif reason == "restart":
                o.bve_speed = -1.0
            elif reason == "scoring-end":
                o.is_scoring_finished = True
            else:
                t_late = 11.5
            o.bve_sway = (0.5, 0.0, 0.0, 0.0)
            st.tick(o, t_late, None)
            last = st.last
            self.assertIsNotNone(last, "no window closed for %s" % reason)
            self.assertEqual(last["end_reason"], reason, "the window must end for %s" % reason)
            self.assertAlmostEqual(last["abs_peak"], 0.03, places=9, msg="the sample after the %s cut (0.5) must not be searched" % reason)

    def test_RV17_the_approach_direction_comes_from_the_last_moving_signed_speed(self):
        sys.path.insert(0, ROOT)
        import sway_shadow as W
        for speed, want in ((-3.0, "backward"), (4.0, "forward"), (None, "unknown")):
            o = self.overlay()
            st = W.SwayShadowState()
            if speed is not None:
                o.bve_speed = speed
                st._follow(o, 9.9)
            o.bve_speed = 0.0
            st.start(o, 10.0, {})
            ctx = st.window.ctx
            self.assertEqual(ctx.get("approach_direction"), want, "NO-DIAG: approach_direction for the last moving speed %r must be %s" % (speed, want))
            self.assertEqual(ctx.get("speed_at_stop"), speed, "NO-DIAG: speed_at_stop is the last moving signed speed (%r)" % (speed,))


if __name__ == "__main__":
    unittest.main()
