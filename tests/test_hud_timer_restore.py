"""Phase HUD-TIMER (RED -> GREEN): the HUD timer goes back to ACTIVE_INTERVAL_MS (16 ms) once the HUD can really update, whatever order the start-up happens in.

Defect (pre-existing, not PID related): the state block is already ACTIVE at start() -> 16 ms; the first tick finds the AppDirectory monitor still waiting for the
Caller's ReadyAccepted -> IDLE_INTERVAL_MS (100 ms) and returns; when the directory is ready the state is still ACTIVE, no state change happens, `_on_change` is never
called and the timer stays at 100 ms (about 9 Hz) for the life of the process. The 100 ms idle contract stays: it is only for a HUD that can not be shown.

HUD-R1  ACTIVE start, no directory wait -> 16
HUD-R2  ACTIVE start, directory waits 1 tick -> 100 while it waits (existing contract), 16 after it is ready
HUD-R3  ACTIVE start, directory waits 3 ticks -> 16 after it is ready
HUD-R4  the state stays ACTIVE and no change event happens: 100 -> 16 still happens (no state line is written for it)
HUD-R5  a real IDLE keeps 100
HUD-R6  ACTIVE -> IDLE: 100
HUD-R7  IDLE -> ACTIVE: 16
HUD-R8  while the directory still waits nothing is updated and the timer stays at 100
HUD-R9  OFS-1: after the grace of a driving-off the timer is 100 again
HUD-R10 the telemetry wait / input release contract is unchanged
HUD-R11 no Current / Legacy branch: the same sequence gives the same intervals for both argument sets
HUD-R12 deterministic: every start order (wait ticks 0..5, ACTIVE at start or published later) ends at the same interval
HUD-R13 two controllers in one process restore independently
No real sleep: the timer and the directory readiness are fixtures.
"""
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import managed_app_directory as mad  # noqa: E402
import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import test_managed_hud_e4 as e4  # noqa: E402

ACTIVE, IDLE = mh.ACTIVE_INTERVAL_MS, mh.IDLE_INTERVAL_MS


class FakeMonitor(object):
    """RuntimeDirectoryMonitor stand-in: `waits` polls answer WAIT_READY (the Caller has not accepted AppReady yet), then MONITORING."""

    def __init__(self, waits):
        self.waits = waits
        self.polls = 0
        self.reader = types.SimpleNamespace(close=lambda: None)

    def poll(self):
        self.polls += 1
        if self.waits > 0:
            self.waits -= 1
            return mad.RuntimeDirectoryResult(mad.RUNTIME_WAIT_READY)
        return mad.RuntimeDirectoryResult(mad.RUNTIME_MONITORING)


class Case(e4.ControllerCase):
    def build(self, waits, active_at_start, monitor=True):
        if active_at_start:
            self.publish(True, True, 1)
        self.monitor = FakeMonitor(waits) if monitor else None
        self.hud = mh.ManagedHudController(self.overlay, self.reader, self.api, self.args, self.log, update_step=lambda o: self.steps.append(1),
                                           timer=self.timer, clock=self.clock, directory_monitor=self.monitor)
        self.hud.start()

    def interval(self):
        return self.timer.intervals[-1]


class HUD_R1_R4_Restore(Case):
    def test_r1_active_start_no_directory_wait(self):
        self.build(0, True)
        self.pump(5)
        self.assertEqual(self.interval(), ACTIVE)

    def test_r2_directory_waits_one_tick(self):
        self.build(1, True)
        self.pump(1)
        self.assertEqual(self.interval(), IDLE, "while the directory waits the existing contract holds")
        self.pump(1)
        self.assertEqual(self.interval(), ACTIVE, "the first tick after the directory is ready restores 16 ms")

    def test_r3_directory_waits_three_ticks(self):
        self.build(3, True)
        self.pump(3)
        self.assertEqual(self.interval(), IDLE)
        self.pump(2)
        self.assertEqual(self.interval(), ACTIVE)

    def test_r4_no_state_change_event_is_needed(self):
        self.build(2, True)
        before = len(self.log.events("state"))
        self.pump(10)
        self.assertEqual(self.interval(), ACTIVE)
        self.assertEqual(len(self.log.events("state")), before, "the restore is not a state change: no state line, no hud-update-start of its own")
        self.assertEqual(len(self.log.events("hud-update-start")), 1)


class HUD_R5_R9_IdleContractIsKept(Case):
    def test_r5_a_real_idle_keeps_100(self):
        self.build(0, False)
        self.pump(30)
        self.assertEqual(self.interval(), IDLE)
        self.assertEqual(self.timer.intervals, [IDLE])
        self.assertEqual(len(self.steps), 0)

    def test_r5_a_real_idle_behind_a_waiting_directory_keeps_100(self):
        self.build(3, False)
        self.pump(30)
        self.assertEqual(self.timer.intervals, [IDLE])

    def test_r6_active_to_idle_is_100(self):
        self.build(0, True)
        self.pump(5)
        self.publish(False, False, 1)
        self.pump(3)
        self.assertEqual(self.interval(), IDLE)

    def test_r7_idle_to_active_is_16(self):
        self.build(0, False)
        self.pump(5)
        self.publish(True, True, 1)
        self.pump(3)
        self.assertEqual(self.interval(), ACTIVE)

    def test_r7_repeated_idle_active_idle_active(self):
        self.build(0, False)
        for _ in range(4):
            self.publish(True, True, 1)
            self.pump(3)
            self.assertEqual(self.interval(), ACTIVE)
            self.publish(False, False, 1)
            self.pump(3)
            self.assertEqual(self.interval(), IDLE)

    def test_r8_a_waiting_directory_starts_no_update_and_no_fast_timer(self):
        self.build(1000, True)
        self.pump(60)
        self.assertEqual(self.interval(), IDLE)
        self.assertEqual(len(self.steps), 0)
        self.assertEqual(self.overlay.shows, 0)

    def test_r9_ofs1_grace_ends_in_100(self):
        self.build(0, True)
        self.pump(5)
        self.publish(True, False, 1)                       # driving off, session on: the grace period
        self.pump(5)
        self.assertEqual(self.interval(), ACTIVE, "inside the grace the HUD is not hidden and the timer is not slowed")
        self.pump(40)                                      # 40 x 20 ms > HIDE_GRACE_S
        self.assertEqual(self.interval(), IDLE)

    def test_r9_back_to_driving_inside_the_grace_stays_16(self):
        self.build(0, True)
        self.pump(5)
        self.publish(True, False, 1)
        self.pump(5)
        self.publish(True, True, 1)
        self.pump(40)
        self.assertEqual(self.interval(), ACTIVE)


class HUD_R10_TelemetryWaitAndInput(Case):
    def test_r10_telemetry_wait_still_hides_and_releases_the_input(self):
        released = []
        self.build(0, True)
        self.hud._telemetry = types.SimpleNamespace(ready=False)
        self.hud._input = types.SimpleNamespace(release=lambda reason, **k: released.append(reason), tick_waiting=lambda: released.append("tick-waiting"), on_pause=lambda *a, **k: None,
                                                on_inactive=lambda *a, **k: None, on_shutdown=lambda *a, **k: None)
        self.pump(5)
        self.assertEqual(len(self.steps), 0)
        self.assertTrue(released, "the input is told to release (release or tick_waiting) every tick of the telemetry wait")
        self.assertFalse(self.overlay.visible)


class HUD_R11_R13_Determinism(Case):
    def test_r11_no_current_legacy_branch(self):
        with open(os.path.join(ROOT, "managed_hud.py"), encoding="utf-8") as handle:
            src = handle.read().lower()
        self.assertNotIn("legacy", src.split("def tick(self)")[1].split("def _on_change")[0])

    def test_r12_every_start_order_ends_at_the_same_interval(self):
        results = set()
        for waits in range(0, 6):
            for active in (True, False):
                case = Case("run")
                case.setUp()
                case.build(waits, active)
                if not active:
                    case.publish(True, True, 1)
                case.pump(12)
                results.add(case.interval())
        self.assertEqual(results, {ACTIVE})

    def test_r13_two_controllers_restore_independently(self):
        one, two = Case("run"), Case("run")
        one.setUp()
        two.setUp()
        one.build(1, True)
        two.build(4, True)
        one.pump(3)
        two.pump(2)                                        # still waiting for its own directory: its own timer is slowed, the other one is not
        self.assertEqual((one.interval(), two.interval()), (ACTIVE, IDLE))
        two.pump(6)
        self.assertEqual((one.interval(), two.interval()), (ACTIVE, ACTIVE))


if __name__ == "__main__":
    unittest.main()
