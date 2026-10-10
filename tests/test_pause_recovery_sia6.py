"""Phase SI-A6 - the pause data recovery: P-to-P only for a token of a concrete operation (F5 while paused), never for "Session ON / Driving OFF / PAUSED / no data".

The physical facts (SR session, 2026-10-10) the tests are built on:
    pause + F5 (same scenario)        BVE inherits the Pause, no Tick, no new data       -> needs the recovery (IMPLEMENTED)
    first load / F5 while RUNNING     no Pause                                           -> no P
    pause + scenario list (same or another scenario)   BVE starts normally (no Pause)   -> no P
    pause + BVE timetable jump / pause + TS Scoring ON                                   -> NO Tick-free signal exists: no token, no P (NOT IMPLEMENTED)
The Caller's state block is the only channel (bytes 48..55 = the Bridge's load marker); the keys are a fake with the same surface as the Win32 one.
"""
import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)

import sia_rig as R  # noqa: E402
import managed_state as ms  # noqa: E402
import pause_recovery as pr  # noqa: E402
import test_managed_hud_e4 as E4  # noqa: E402
from test_managed_input_sia3 import ManagedCase  # noqa: E402

CREATED = ms.LOAD_CREATED
TICK = ms.LOAD_TICK_SEEN
F5 = pr.VK_F5
P = pr.VK_P


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class RecoveryCase(ManagedCase):
    """Helpers for the story of one pause, in the vocabulary of the Caller's state block."""

    def settled_pause(self, generation=1, load=CREATED | TICK, driving=True):
        """A scenario that ran and was then paused by somebody: Session ON, Driving ON (the Caller's own Tick goes on in a Pause - phase D1), STATUS PAUSED for 1.5 s."""
        r = self.r
        r.publish(True, driving, generation, load=load)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(30, seconds=0.05)

    def fresh_pause(self, generation=1, load=CREATED | TICK, driving=True, ticks=1, seconds=0.02):
        """Phase SI-A6.1: the Pause that was made a moment ago - the newest STATUS is PAUSED and that is all that has happened since (no waiting of any kind)."""
        r = self.r
        r.publish(True, driving, generation, load=load)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        if ticks:
            r.tick(ticks, seconds=seconds)

    def arm(self, generation=1):
        self.settled_pause(generation)
        self.r.press(F5)
        self.assertTrue(self.r.recovery.active, "F5 in a settled pause must arm a token")

    def reload(self, generation):
        """BVE closed and opened the scenario again (the Bridge: Session OFF, a new generation, the marker cleared)."""
        self.r.publish(False, False, generation, load=0)
        self.r.tick(2)

    def created(self, generation, load=CREATED):
        self.r.publish(False, False, generation, load=load)
        self.r.tick(1)

    def to_first_press(self, generation=2):
        """From a settled pause at generation-1: F5, the reload, ScenarioCreated, the quiet time -> the first P."""
        self.arm(generation - 1)
        self.reload(generation)
        self.created(generation)
        self.r.tick(8, seconds=0.05)

    def p_count(self):
        return len(self.posted_keys(R.KEY_P))

    def steps(self):
        return [e.split("step=")[1].split()[0] for e in self.r.events("kickstart")]

    def reasons(self):
        out = []
        for line in self.r.events("recovery-token"):
            m = re.search(r"reason=(\S+)", line)
            if m:
                out.append(m.group(1))
        return out

    def tokens(self):
        return [re.search(r"state=(\S+)", line).group(1) for line in self.r.events("recovery-token")]

    def data_after_first_press(self, generation=2, time_ms=36000000, status="RUNNING", stations=True):
        """What the Tick that the first P causes brings: Session ON (the Bridge), STATUS, the station list and the telemetry of the generation."""
        r = self.r
        r.publish(True, False, generation, load=CREATED | TICK)
        r.send("STATUS:LOADED:" + status)
        if stations:
            r.send(self.MR.STALIST, self.MR.tele(generation, time_ms=time_ms))
        else:
            r.send(self.MR.tele(generation, time_ms=time_ms))
        r.tick(2)


# ===================================================================================================================================================
class A_LoadMarkerOfTheStateBlock(unittest.TestCase):
    def setUp(self):
        self.inst = E4.new_instance()
        self.pid = 4242

    def parse(self, **kw):
        return ms.parse_state(E4.make_block(self.pid, self.inst, **kw), self.pid, self.inst)

    def test_a_block_without_the_marker_is_no_information_and_not_an_error(self):
        snap, reason = self.parse(session=True, generation=3, count=1)
        self.assertIsNone(reason)
        self.assertEqual((snap.load_supported, snap.load_info, snap.created_seen, snap.tick_seen), (False, 0, False, False))

    def test_the_marker_is_read_together_with_the_generation(self):
        for info, created, tick in ((0, False, False), (CREATED, True, False), (TICK, False, True), (CREATED | TICK, True, True)):
            snap, reason = self.parse(generation=5, count=2, load_info=info, load_magic=ms.LOAD_MAGIC)
            self.assertIsNone(reason)
            self.assertEqual((snap.generation, snap.load_supported, snap.created_seen, snap.tick_seen), (5, True, created, tick), info)

    def test_a_foreign_magic_is_no_information_and_its_bits_are_not_trusted(self):
        for magic in (1, 0x4C4F4432, 0xFFFFFFFF):
            snap, reason = self.parse(generation=5, count=2, load_info=CREATED | TICK, load_magic=magic)
            self.assertIsNone(reason, magic)
            self.assertEqual((snap.load_supported, snap.load_info, snap.created_seen), (False, 0, False), magic)

    def test_unknown_bits_are_dropped_not_rejected(self):
        snap, reason = self.parse(generation=1, count=1, load_info=CREATED | 0x8, load_magic=ms.LOAD_MAGIC)
        self.assertIsNone(reason)
        self.assertEqual(snap.load_info, CREATED)

    def test_a_torn_copy_is_still_rejected_whatever_the_marker_says(self):
        snap, reason = self.parse(generation=1, count=1, head=3, tail=3, load_info=CREATED, load_magic=ms.LOAD_MAGIC)
        self.assertEqual((snap, reason), (None, "torn"))

    def test_version_and_size_and_the_old_fields_are_unchanged(self):
        self.assertEqual((ms.STATE_VERSION, ms.STATE_SIZE), (1, 64))
        snap, _ = self.parse(session=True, driving=True, generation=9, count=4, load_info=TICK, load_magic=ms.LOAD_MAGIC)
        self.assertEqual((snap.session, snap.driving, snap.generation, snap.change_count), (True, True, 9, 4))

    def test_the_gate_does_not_react_to_the_marker_alone(self):
        g = ms.HudGate()
        a = ms.StateSnapshot(True, False, False, 2, 1, 2, True, 0)
        b = ms.StateSnapshot(True, False, False, 2, 2, 4, True, CREATED)
        self.assertIsNotNone(g.apply(a))
        self.assertIsNone(g.apply(b))                                           # same Session / Driving / generation: no HUD state change

    def test_the_c_sharp_source_documents_the_same_layout(self):
        text = read(os.path.join("TsScoringPlugin", "Handshake", "Caller", "src", "AppStatePublisher.cs"))
        self.assertIn("48 uint32  LoadInfo", text)
        self.assertIn("52 uint32  LoadMagic", text)
        self.assertIn("0x4C4F4431", text)


# ===================================================================================================================================================
class B_TheTokenIsCreatedOnlyByTheF5OfASettledPause(RecoveryCase):
    """F5 while the sender says PAUSED for a second or more, with a scenario (Session ON): in a real Pause the Caller's Tick goes on, so Driving is ON."""
    def test_f5_in_a_settled_pause_arms_a_token_and_nothing_is_pressed_or_suppressed(self):
        r = self.r
        self.settled_pause()
        posted = len(self.api.posted)
        r.press(F5)
        t = r.recovery.token
        self.assertEqual((t.kind, t.phase, t.gen0, t.pid), (pr.KIND_F5_RELOAD, pr.PHASE_ARMED, 1, r.args.bve_pid))
        self.assertEqual(t.status0, "PAUSED")
        self.assertEqual((t.first_sent, t.second_sent), (False, False))
        self.assertEqual(len(self.api.posted), posted)                         # F5 is not re-sent, nothing at all is posted
        self.assertEqual(self.held(), [])                                      # F5 is not suppressed: no key hook of any kind
        self.assertEqual(self.p_count(), 0)

    def test_one_token_per_f5_not_one_per_slot(self):
        r = self.r
        self.settled_pause()
        r.keys.down.add(F5)
        r.tick(30)
        self.assertEqual(r.recovery.created, 1)

    def test_f5_while_running_creates_no_token(self):
        r = self.r
        r.go_active(generation=1)
        r.send("STATUS:LOADED:RUNNING")
        r.publish(True, True, 1, load=CREATED | TICK)
        r.press(F5)
        self.assertFalse(r.recovery.active)
        self.assertEqual(r.recovery.created, 0)

    def test_f5_within_a_second_of_the_pause_starting_creates_a_token(self):
        """Phase SI-A6.1 (real machine: F5 at an ordinary speed after P made NO token because a 1 s wait was asked): nothing is asked of the user any more."""
        r = self.r
        self.fresh_pause(ticks=10, seconds=0.05)                              # 0.5 s of Pause
        r.press(F5)
        self.assertEqual(r.recovery.created, 1)

    def test_a_pause_that_ended_and_began_again_makes_a_token_for_an_f5_right_after_it(self):
        r = self.r
        self.settled_pause()
        r.send("STATUS:LOADED:RUNNING")
        r.tick(2)
        r.press(F5)                                                           # F5 while RUNNING in between: nothing
        self.assertEqual(r.recovery.created, 0)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(5, seconds=0.05)
        r.press(F5)
        self.assertEqual(r.recovery.created, 1)                               # the second Pause is a Pause from its first slot on

    def test_f5_in_a_pause_with_driving_off_creates_a_token_too(self):
        r = self.r
        self.settled_pause(driving=False)
        self.assertEqual(r.hud.mode, "waiting")
        r.press(F5)
        self.assertEqual(r.recovery.created, 1)

    def test_f5_in_a_pause_with_driving_on_creates_a_token(self):
        """The real Pause: the Caller's Tick goes on (phase D1: BVE5 and BVE6), so Driving stays ON and the HUD mode is `active`."""
        r = self.r
        self.settled_pause(driving=True)
        self.assertEqual(r.hud.mode, "active")
        r.press(F5)
        self.assertEqual(r.recovery.created, 1)

    def test_f5_in_a_pause_that_the_sender_does_not_report_creates_no_token(self):
        r = self.r
        r.publish(True, False, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:RUNNING")                                       # a title screen / a selection screen: Driving is OFF but BVE is not paused
        r.tick(2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_f5_without_a_status_creates_no_token(self):
        r = self.r
        r.publish(True, False, 1, load=CREATED | TICK)
        r.tick(2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_f5_in_another_program_creates_no_token(self):
        r = self.r
        self.settled_pause()
        r.keys.foreground = r.args.bve_pid + 1
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_f5_without_a_session_creates_no_token(self):
        r = self.r
        r.publish(False, False, 1, load=CREATED)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_f5_after_the_state_was_closed_creates_no_token(self):
        r = self.r
        self.settled_pause()
        r.publish(True, False, 1, closed=True, load=CREATED | TICK)
        r.tick(2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_an_f5_that_was_already_down_is_not_an_edge(self):
        r = self.r
        r.keys.down.add(F5)
        self.settled_pause()                                                   # F5 is held while the pause becomes "settled"
        r.tick(5)
        self.assertEqual(r.recovery.created, 0)

    def test_no_load_marker_means_no_token_and_one_note(self):
        """An older Bridge / Caller: the end of the reload cannot be known, so no P may ever be sent for it."""
        r = self.r
        self.settled_pause(load=None)
        self.assertFalse(r.hud._reader.last.load_supported)
        r.press(F5)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)
        self.assertEqual(self.tokens(), ["unavailable"])
        self.reload(2)
        self.created(2, load=None)
        r.tick(40, seconds=0.1)
        self.assertEqual(self.p_count(), 0)

    def test_a_second_f5_replaces_the_pending_token(self):
        r = self.r
        self.arm()
        r.press(F5)
        self.assertEqual((r.recovery.created, r.recovery.expired), (2, 1))
        self.assertEqual(self.reasons(), [pr.R_REPEATED_F5])
        self.assertTrue(r.recovery.active)
        self.assertEqual(self.p_count(), 0)

    def test_only_the_f5_kind_can_be_created(self):
        r = self.r
        self.settled_pause()
        snap = r.hud._reader.last
        for kind in (pr.KIND_TIMETABLE_JUMP, pr.KIND_SCORING_ON, "anything-else"):
            self.assertFalse(r.recovery.begin(kind, snap), kind)
        self.assertFalse(r.recovery.active)
        self.assertEqual(pr.IMPLEMENTED_KINDS, frozenset((pr.KIND_F5_RELOAD,)))
        self.assertEqual(set(pr.ALL_KINDS) - pr.IMPLEMENTED_KINDS, {pr.KIND_TIMETABLE_JUMP, pr.KIND_SCORING_ON})

    def test_one_token_at_a_time(self):
        r = self.r
        self.arm()
        self.assertFalse(r.recovery.begin(pr.KIND_F5_RELOAD, r.hud._reader.last))
        self.assertEqual(r.recovery.created, 1)


# ===================================================================================================================================================
class C_TheF5RecoveryIsPressedExactlyTwice(RecoveryCase):
    def test_the_whole_round_trip(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.assertEqual(r.recovery.token.phase, pr.PHASE_LOADING)
        r.tick(300, seconds=0.05)                                             # 15 s of loading: BVE needs seconds, and nothing may be pressed meanwhile
        self.assertEqual(self.p_count(), 0)
        self.created(2)
        r.tick(5, seconds=0.05)                                               # ScenarioCreated is only 0.25 s old: the quiet time is not over
        self.assertEqual(self.p_count(), 0)
        r.tick(4, seconds=0.05)
        self.assertEqual(self.p_count(), 1)
        self.assertEqual(r.recovery.token.phase, pr.PHASE_FIRST_SENT)
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 1)                                   # one first P
        self.data_after_first_press(2, time_ms=36000000)
        self.assertEqual(self.p_count(), 1)                                   # the data is there but the BVE time has not moved yet
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)
        self.assertFalse(r.recovery.active)
        self.assertEqual((r.recovery.completed, r.recovery.first_presses, r.recovery.second_presses), (1, 1, 1))
        r.send(self.MR.tele(2, time_ms=36001000))
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 2)                                   # one second P
        self.assertEqual(self.steps(), ["first", "second"])
        self.assertEqual(self.tokens(), ["armed", "loading", "done"])
        for message in self.api.posted:
            self.assertEqual((message[0], message[2]), (5000, R.KEY_P))       # only P, only to the BVE window of this process

    def test_the_diagnostics_are_fixed_words_and_a_few_lines(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(2)
        lines = r.events("recovery-token") + r.events("kickstart")
        self.assertLessEqual(len(lines), 5)
        for line in lines:
            self.assertIsNone(re.search(r"[\\/]|station|name", line.lower().replace("recovery-token", "")), line)
        self.assertIn("token=f5", r.events("kickstart")[0])
        self.assertIn("f5_to_gen_ms=", r.events("recovery-token")[1])

    def test_the_generation_alone_is_not_the_completion_of_the_load(self):
        r = self.r
        self.arm()
        self.reload(2)
        r.tick(500, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_a_pressed_p_before_the_first_is_never_doubled(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.created(2)
        r.keys.down.add(P)                                                    # the user presses P at the same time
        r.tick(3, seconds=0.05)
        r.keys.down.discard(P)
        r.tick(10, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.reasons(), [pr.R_MANUAL_P])

    def test_the_second_p_waits_for_every_condition(self):
        r = self.r
        self.to_first_press()
        r.publish(True, False, 2, load=CREATED | TICK)
        r.tick(2)
        r.send(self.MR.tele(2, time_ms=36000000))                              # telemetry but no station list
        r.tick(3)
        r.send("STATUS:LOADED:RUNNING")
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(3)
        self.assertEqual(self.p_count(), 1)                                   # no station list yet
        r.send(self.MR.STALIST, self.MR.tele(2, time_ms=36001000))
        r.tick(2)
        r.send(self.MR.tele(2, time_ms=36001500))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)

    def test_the_second_p_waits_for_the_sender_to_say_running(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2, status="PAUSED")
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(5)
        self.assertEqual(self.p_count(), 1)
        r.send("STATUS:LOADED:RUNNING", self.MR.tele(2, time_ms=36001000))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)

    def test_the_second_p_waits_for_the_bve_time_to_move(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2, time_ms=36000000)
        for _ in range(5):
            r.send(self.MR.tele(2, time_ms=36000000))
            r.tick(2)
        self.assertEqual(self.p_count(), 1)
        r.send(self.MR.tele(2, time_ms=36000100))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)

    def test_the_second_p_does_not_need_driving_to_be_on(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2)
        self.assertEqual(r.hud.mode, "waiting")                                # Driving turns ON only a moment later in the Caller; the recovery does not wait for it
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)

    def test_the_station_list_of_the_old_generation_is_not_the_new_one(self):
        r = self.r
        r.go_active(sid=1, generation=1)
        self.assertEqual(len(self.o.station_list), 3)
        self.settled_pause(1)
        r.press(F5)
        self.assertTrue(r.recovery.active)
        self.reload(2)
        self.assertEqual(self.o.station_list, [])
        self.created(2)
        r.tick(8, seconds=0.05)
        self.assertEqual(self.p_count(), 1)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 1)                                   # the old list does not satisfy the second half

    def test_two_pauses_two_recoveries(self):
        r = self.r
        self.to_first_press(2)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)
        r.send(self.MR.tele(2, time_ms=36001000))
        r.publish(True, True, 2, load=CREATED | TICK)
        r.tick(3)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(30, seconds=0.05)                                              # the second Pause settles
        r.press(F5)
        self.reload(3)
        self.created(3)
        r.tick(8, seconds=0.05)
        self.assertEqual(self.p_count(), 3)
        self.data_after_first_press(3, time_ms=36000000)
        r.send(self.MR.tele(3, time_ms=36000500))
        r.tick(2)
        self.assertEqual(self.p_count(), 4)
        self.assertEqual((r.recovery.created, r.recovery.completed), (2, 2))


# ===================================================================================================================================================
class D_TheTokenIsClosedWithoutAnyPress(RecoveryCase):
    def assertClosed(self, reason, presses=0):
        self.assertFalse(self.r.recovery.active)
        self.assertEqual(self.reasons()[-1], reason)
        self.assertEqual(self.p_count(), presses)

    def test_f5_that_reloads_nothing_expires_by_the_one_timer(self):
        r = self.r
        self.arm()
        r.tick(30, seconds=0.05)                                              # 1.5 s: still waiting
        self.assertTrue(r.recovery.active)
        r.tick(20, seconds=0.05)
        self.assertClosed(pr.R_NO_RELOAD)

    def test_a_list_load_long_after_an_f5_that_did_nothing_is_not_the_reload(self):
        r = self.r
        self.arm()
        r.tick(60, seconds=0.05)                                              # 3 s: the token expired
        self.reload(2)                                                        # the user now picks a scenario from the list (BVE starts it normally)
        self.created(2)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_a_manual_p_closes_the_token_in_every_phase(self):
        r = self.r
        self.arm()
        r.keys.down.add(P)
        r.tick(2)
        r.keys.down.discard(P)
        self.assertClosed(pr.R_MANUAL_P)
        self.arm()                                                            # again, now in the loading phase
        self.reload(2)
        r.keys.down.add(P)
        r.tick(2)
        r.keys.down.discard(P)
        r.tick(40, seconds=0.05)
        self.assertClosed(pr.R_MANUAL_P)

    def test_a_manual_p_after_the_first_press_closes_the_token_so_there_is_no_second_press(self):
        r = self.r
        self.to_first_press()
        r.keys.down.add(P)
        r.tick(2)
        r.keys.down.discard(P)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(4)
        self.assertClosed(pr.R_MANUAL_P, presses=1)

    def test_data_that_arrives_without_our_p_closes_the_token(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.created(2)
        r.publish(True, True, 2, load=CREATED | TICK)                          # the user pressed P: BVE ticks, the Session comes up
        r.tick(2)
        r.tick(20, seconds=0.05)
        self.assertClosed(pr.R_SELF_RECOVERED)

    def test_a_tick_seen_without_a_session_closes_the_token_too(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.created(2, load=CREATED | TICK)
        r.tick(20, seconds=0.05)
        self.assertClosed(pr.R_SELF_RECOVERED)

    def test_telemetry_without_our_p_closes_the_token(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.created(2)
        r.send(self.MR.STALIST, self.MR.tele(2, time_ms=36000000))
        r.tick(20, seconds=0.05)
        self.assertClosed(pr.R_SELF_RECOVERED)

    def test_another_generation_while_loading_closes_the_token(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.reload(3)                                                        # the user picked a scenario from the list before the load ended
        self.created(3)
        r.tick(40, seconds=0.05)
        self.assertClosed(pr.R_GENERATION_CHANGED)

    def test_a_generation_that_skips_one_is_not_the_reload(self):
        r = self.r
        self.arm()
        self.reload(3)
        r.tick(40, seconds=0.05)
        self.assertClosed(pr.R_GENERATION_SKIPPED)

    def test_the_generation_wrap_is_the_next_generation(self):
        self.assertEqual(pr.next_generation(1), 2)
        self.assertEqual(pr.next_generation(0x7FFFFFFF), 1)
        r = self.r
        self.arm(generation=0x7FFFFFFF)
        self.reload(1)
        self.assertEqual(r.recovery.token.phase, pr.PHASE_LOADING)

    def test_session_off_after_the_scenario_came_up_closes_the_token(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2)
        r.publish(False, False, 2, load=CREATED | TICK)                        # the scenario was closed again before the second P
        r.tick(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(5)
        self.assertClosed(pr.R_SESSION_OFF, presses=1)

    def test_the_state_block_closing_closes_the_token(self):
        r = self.r
        self.arm()
        r.publish(True, False, 1, closed=True, load=CREATED | TICK)
        r.tick(3)
        self.assertClosed(pr.R_STATE_CLOSED)

    def test_the_loss_of_the_state_block_closes_the_token(self):
        r = self.r
        self.arm()
        r.source.data = b""
        r.tick(3)
        self.assertIsNotNone(r.hud.failsafe)
        self.assertFalse(r.recovery.active)
        self.assertEqual(self.reasons()[-1], pr.R_STATE_LOST)
        r.tick(30)
        self.assertEqual(self.p_count(), 0)

    def test_the_window_of_this_process_gone_closes_the_token_instead_of_pressing_elsewhere(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.created(2)
        self.win.alive = False
        r.tick(40, seconds=0.6)
        self.assertClosed(pr.R_WINDOW_LOST)

    def test_the_second_p_is_not_sent_to_a_window_that_is_gone(self):
        r = self.r
        self.to_first_press()
        self.data_after_first_press(2)
        self.win.alive = False
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(40, seconds=0.6)
        self.assertClosed(pr.R_WINDOW_LOST, presses=1)

    def test_the_second_p_must_follow_within_the_one_timer(self):
        r = self.r
        self.to_first_press()
        r.tick(250, seconds=0.05)                                             # 12.5 s and no data at all
        self.assertClosed(pr.R_SECOND_TIMEOUT, presses=1)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(5)
        self.assertEqual(self.p_count(), 1)

    def test_a_new_generation_after_the_first_p_closes_the_token(self):
        r = self.r
        self.to_first_press()
        self.reload(3)
        r.tick(5)
        self.assertClosed(pr.R_GENERATION_CHANGED, presses=1)

    def test_shutdown_closes_the_token_and_reports_the_counters(self):
        r = self.r
        self.arm()
        r.hud.shutdown()
        self.assertFalse(r.recovery.active)
        self.assertEqual(self.reasons()[-1], pr.R_SHUTDOWN)
        self.assertTrue(r.events("recovery-summary"))
        self.assertEqual(self.p_count(), 0)

    def test_nothing_is_pressed_after_the_token_ended(self):
        r = self.r
        self.arm()
        r.keys.down.add(P)
        r.tick(2)
        r.keys.down.discard(P)
        self.reload(2)
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertEqual(self.p_count(), 0)


# ===================================================================================================================================================
class E_NoTokenNoPress(RecoveryCase):
    """Every other way to get "Session ON / Driving OFF / PAUSED / no data" - or a new generation - sends no P at all."""

    def test_the_first_load_of_a_scenario(self):
        r = self.r
        self.reload(1)
        self.created(1)
        r.tick(20, seconds=0.05)
        r.publish(True, False, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")                                         # the short PAUSED window right after the first Tick
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(r.events("kickstart"), [])

    def test_the_old_si_a4_condition_alone_sends_nothing(self):
        r = self.r
        for generation in (1, 2, 3):
            r.publish(True, False, generation, load=CREATED | TICK)
            r.tick(2)
            r.send("STATUS:LOADED:PAUSED")
            r.tick(60, seconds=0.05)
            r.publish(False, False, generation, load=0)
            r.tick(2)
        self.assertEqual(self.p_count(), 0)

    def test_session_on_and_driving_on_with_a_paused_status_and_no_telemetry_sends_nothing(self):
        r = self.r
        r.publish(True, True, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_session_on_driving_off_paused_without_a_window_search(self):
        r = self.r
        r.publish(True, False, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        searches = self.win.searches
        r.tick(40, seconds=0.6)
        self.assertEqual(self.win.searches, searches)

    def test_a_scenario_picked_from_the_list_while_paused_another_scenario(self):
        r = self.r
        self.settled_pause()
        self.reload(2)                                                        # no F5: the list
        self.created(2)
        r.tick(100, seconds=0.05)
        r.publish(True, False, 2, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(r.recovery.created, 0)

    def test_a_scenario_picked_from_the_list_while_paused_the_same_scenario(self):
        r = self.r
        self.settled_pause()
        r.publish(False, False, 1, load=0)                                     # the scenario closed ...
        r.tick(2)
        r.publish(False, False, 2, load=0)                                     # ... and the list opened it again: a new instance
        r.tick(2)
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_f5_while_running_then_the_reload(self):
        r = self.r
        r.go_active(generation=1)
        r.send("STATUS:LOADED:RUNNING")
        r.publish(True, True, 1, load=CREATED | TICK)
        r.tick(2)
        r.press(F5)
        self.reload(2)
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(r.recovery.created, 0)

    def test_a_timetable_jump_while_paused_has_no_token_and_no_press(self):
        """BVE's own timetable jump while paused: no BveEX event, no Tick, the sender's JUMP counter only moves in a Tick. Nothing to see, nothing pressed."""
        r = self.r
        r.go_active(generation=1)
        r.publish(True, False, 1, load=CREATED | TICK)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(30, seconds=0.1)
        r.send(self.MR.tele(1, time_ms=36600000, JUMP=1))                      # even a JUMP counter that moved (the Tick that BVE did not run)
        r.tick(60, seconds=0.1)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(r.recovery.created, 0)

    def test_the_official_jump_of_ts_scoring_has_no_token_and_no_press(self):
        r = self.r
        r.go_active(speed=5.0)
        r.start_scoring_via_menu()
        r.o.is_official_jumping = True
        r.send(self.MR.tele(1, speed=5.0, JUMP=2))
        r.tick(60, seconds=0.1)
        self.assertEqual(r.events("kickstart"), [])                            # (the scoring menu's own P to pause the game is a different, existing feature)
        self.assertEqual(r.recovery.created, 0)

    def test_ts_scoring_switched_on_while_paused_has_no_token(self):
        """A new Caller cycle, a new application: no state, no token, no press until the normal life of a scenario starts."""
        r = self.r
        r.tick(100, seconds=0.1)
        self.assertEqual((self.p_count(), r.recovery.created), (0, 0))


# ===================================================================================================================================================
class F_TheOldKickStartIsGone(unittest.TestCase):
    def test_the_overlay_has_no_managed_kick_start_except_the_recovery_press(self):
        tree = ast.parse(read("main.py"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        for gone in ("kick_start_managed", "kick_start_wanted", "kick_start_managed_waiting"):
            self.assertNotIn(gone, names)
        self.assertIn("press_p_for_recovery", names)
        self.assertIn("_kick_start_first_press", names)                       # the normal (manual) mode keeps it
        self.assertIn("_kick_start_second_press", names)

    def test_the_managed_step_does_not_call_the_first_half(self):
        tree = ast.parse(read("main.py"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "managed_window_step")
        called = sorted({n.func.attr for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)})
        self.assertNotIn("_kick_start_first_press", called)
        self.assertIn("_run_input_and_scoring_step", called)

    def test_the_normal_mode_still_runs_the_first_half(self):
        tree = ast.parse(read("main.py"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "update_logic")
        called = {n.func.attr for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("_kick_start_first_press", called)
        self.assertIn("_run_input_and_scoring_step", called)

    def test_the_hud_and_the_input_controller_have_no_waiting_kick_start(self):
        for name in ("managed_hud.py", "managed_input.py"):
            tree = ast.parse(read(name))
            names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            for gone in ("_tick_waiting_kickstart", "tick_waiting_kickstart", "kick_start_wanted"):
                self.assertNotIn(gone, names, name)
            self.assertNotIn("kick_start_managed", read(name).replace("kick_start_managed_", ""))

    def test_p_is_posted_only_by_press_p_for_recovery_in_the_managed_modules(self):
        for name in ("managed_hud.py", "managed_input.py", "pause_recovery.py", "managed_state.py"):
            text = read(name)
            self.assertNotIn("PostMessage", text.replace("press_p_for_recovery", ""), name)
            self.assertNotIn("SendInput", text, name)
            self.assertNotIn("keybd_event", text, name)

    def test_the_recovery_installs_no_hook_and_suppresses_nothing(self):
        text = read("pause_recovery.py")
        self.assertNotIn("keyboard.", text)
        self.assertNotIn("on_press", text)
        self.assertNotIn("suppress=", text)
        self.assertNotIn("SetWindowsHookEx", text)
        tree = ast.parse(text)
        calls = sorted({n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and "user32" in ast.dump(n.func)})
        self.assertEqual(calls, ["GetAsyncKeyState", "GetForegroundWindow", "GetWindowThreadProcessId"])

    def test_the_recovery_reads_nothing_from_bve(self):
        text = read("pause_recovery.py")
        for word in ("ReadProcessMemory", "OpenProcess", "pymem", "win32process.", "EnumWindows"):
            self.assertNotIn(word, text)

    def test_the_recovery_is_a_pure_module_with_only_two_win32_names(self):
        tree = ast.parse(read("pause_recovery.py"))
        imports = sorted({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
        self.assertEqual(imports, ["ctypes", "managed_state", "time"])

    def test_the_two_blocked_operations_have_no_creation_path(self):
        """The only place a token is made is begin(); _maybe_arm calls it with KIND_F5_RELOAD alone."""
        text = read("pause_recovery.py")
        self.assertEqual(re.findall(r"self\.begin\((\w+)", text), ["KIND_F5_RELOAD"])
        self.assertIn("IMPLEMENTED_KINDS = frozenset((KIND_F5_RELOAD,))", text)

    def test_the_time_constants_are_exactly_four(self):
        """Phase SI-A6.1: PAUSE_SETTLED_S (the 1 s the user had to wait after P) is gone; the three that remain are unchanged.
        Phase SI-A6.2: ONE constant is added, PAUSE_INTENT_TTL_S (the life of a PauseIntent: the lag of the sender's STATUS, ~150 ms, plus the application's own latency)."""
        self.assertEqual(sorted(n for n in dir(pr) if re.match(r"^[A-Z0-9_]+_(S|MS)$", n)), ["F5_TO_GENERATION_MAX_S", "FIRST_QUIET_S", "PAUSE_INTENT_TTL_S", "SECOND_MAX_S"])
        self.assertEqual((pr.F5_TO_GENERATION_MAX_S, pr.FIRST_QUIET_S, pr.SECOND_MAX_S), (2.0, 0.3, 10.0))
        self.assertEqual(pr.PAUSE_INTENT_TTL_S, 0.3)
        self.assertFalse(hasattr(pr, "PAUSE_SETTLED_S"))

    def test_the_creation_does_not_look_at_how_long_the_pause_lasted(self):
        tree = ast.parse(read("pause_recovery.py"))                           # (the comments and the module text may name the old constant as history)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertFalse({"PAUSE_SETTLED_S", "_status_since", "_status"} & names)
        self.assertNotIn("_follow_status", defined)


# ===================================================================================================================================================
class H_F5RightAfterThePause(RecoveryCase):
    """Phase SI-A6.1. Real machine (Caller 0.12.0.0): P then F5 at an ordinary speed made generation +1 and NO token (the 1 s wait that was asked was not over), so no P-to-P
    and no HUD; the same build with a 5 s wait worked. The user is asked for no wait. What separates this from a normal load is the F5 edge and what follows it."""

    def test_f5_in_the_very_slot_after_the_paused_status_arrives_makes_the_token(self):
        r = self.r
        self.fresh_pause(ticks=0)
        r.press(F5)
        self.assertEqual((r.recovery.created, r.recovery.token.phase), (1, pr.PHASE_ARMED))
        self.assertEqual(self.p_count(), 0)

    def test_f5_after_a_fraction_of_a_second_makes_the_token_whatever_the_speed(self):
        for ticks, seconds in ((1, 0.02), (5, 0.02), (10, 0.05), (19, 0.05), (40, 0.05)):
            with self.subTest(pause_s=ticks * seconds):
                self.tearDown()
                self.setUp()
                self.fresh_pause(ticks=ticks, seconds=seconds)
                self.r.press(F5)
                self.assertEqual(self.r.recovery.created, 1)

    def test_the_whole_round_trip_from_a_fresh_pause_presses_p_exactly_twice(self):
        r = self.r
        self.fresh_pause(generation=1, ticks=3)
        r.press(F5)
        self.assertTrue(r.recovery.active)
        self.reload(2)
        self.created(2)
        r.tick(4, seconds=0.05)
        self.assertEqual(self.p_count(), 0)                                   # the quiet time is not over
        r.tick(6, seconds=0.05)
        self.assertEqual(self.p_count(), 1)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(3)
        self.assertEqual(self.p_count(), 2)
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 2)
        self.assertEqual(self.tokens(), ["armed", "loading", "done"])
        self.assertEqual(self.steps(), ["first", "second"])
        self.assertEqual((r.recovery.created, r.recovery.completed, r.recovery.expired), (1, 1, 0))

    def test_f5_while_running_still_makes_no_token(self):
        r = self.r
        r.publish(True, True, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(1)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_the_short_paused_window_of_a_load_alone_makes_no_token_and_no_press(self):
        """No F5, no token: the PAUSED window that follows a load is not an operation (SI-A4 pressed P here, three loads out of three)."""
        r = self.r
        self.reload(1)
        self.created(1)
        r.tick(8, seconds=0.05)
        r.publish(True, True, 1, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(12, seconds=0.05)                                              # the 0.35-0.5 s window
        r.send("STATUS:LOADED:RUNNING")
        r.tick(60, seconds=0.05)
        self.assertEqual((r.recovery.created, self.p_count()), (0, 0))

    def test_f5_in_the_short_paused_window_of_a_load_closes_itself_and_presses_nothing(self):
        """The one case the old 1 s rule excluded: F5 while the short PAUSED window of a load is on. A running reload ticks by itself, so the token closes itself."""
        r = self.r
        self.fresh_pause(ticks=3)
        r.press(F5)
        self.assertEqual(r.recovery.created, 1)
        self.reload(2)
        self.created(2)
        r.publish(True, True, 2, load=CREATED | TICK)                          # BVE was not paused: the Tick came 12-63 ms after ScenarioCreated
        r.tick(2, seconds=0.03)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.reasons(), [pr.R_SELF_RECOVERED])
        self.assertFalse(r.recovery.active)

    def test_a_generation_change_without_an_f5_after_a_fresh_pause_makes_no_token(self):
        r = self.r
        self.fresh_pause(ticks=3)
        self.reload(2)                                                         # a list load, not F5
        self.created(2)
        r.tick(60, seconds=0.05)
        self.assertEqual((r.recovery.created, self.p_count()), (0, 0))

    def test_a_list_load_of_the_same_scenario_after_a_fresh_pause_presses_nothing(self):
        r = self.r
        self.fresh_pause(ticks=3)
        r.publish(False, False, 1, load=0)
        r.tick(2)
        r.publish(False, False, 2, load=0)
        r.tick(2)
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertEqual((r.recovery.created, self.p_count()), (0, 0))

    def test_the_token_of_a_fresh_pause_expires_when_the_generation_is_not_plus_one(self):
        r = self.r
        self.fresh_pause(ticks=3)
        r.press(F5)
        self.reload(3)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.reasons(), [pr.R_GENERATION_SKIPPED])
        self.assertEqual(self.p_count(), 0)

    def test_no_press_before_scenario_created_whatever_the_speed_of_the_f5(self):
        r = self.r
        self.fresh_pause(ticks=0)
        r.press(F5)
        self.reload(2)
        r.tick(300, seconds=0.05)                                              # a 15 s load, never ScenarioCreated
        self.assertEqual(self.p_count(), 0)
        self.assertTrue(r.recovery.active)

    def test_new_telemetry_that_arrives_by_itself_means_no_press(self):
        r = self.r
        self.fresh_pause(ticks=2)
        r.press(F5)
        self.reload(2)
        self.created(2)
        r.send(self.MR.STALIST, self.MR.tele(2, time_ms=36000000))
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.reasons(), [pr.R_SELF_RECOVERED])

    def test_first_and_second_are_at_most_one_each(self):
        r = self.r
        self.fresh_pause(ticks=2)
        r.press(F5)
        self.reload(2)
        self.created(2)
        r.tick(150, seconds=0.05)
        self.assertEqual(self.p_count(), 1)                                    # no data after the first P: still one, however long it takes
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(3)
        for _ in range(5):
            r.send(self.MR.tele(2, time_ms=36001000))
            r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 2)
        self.assertEqual((r.recovery.first_presses, r.recovery.second_presses), (1, 1))

    def test_a_manual_p_after_a_fresh_pause_f5_closes_the_token(self):
        r = self.r
        self.fresh_pause(ticks=2)
        r.press(F5)
        self.reload(2)
        r.keys.down.add(P)
        r.tick(2)
        r.keys.down.discard(P)
        self.created(2)
        r.tick(60, seconds=0.05)
        self.assertEqual(self.reasons(), [pr.R_MANUAL_P])
        self.assertEqual(self.p_count(), 0)

    def test_an_older_bridge_or_caller_without_the_marker_still_presses_nothing(self):
        r = self.r
        self.fresh_pause(load=None, ticks=2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)
        self.reload(2)
        self.created(2, load=None)
        r.tick(200, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.tokens(), ["unavailable"])

    def test_f5_in_another_program_or_without_a_session_makes_no_token_after_a_fresh_pause(self):
        r = self.r
        self.fresh_pause(ticks=2)
        r.keys.foreground = r.args.bve_pid + 1
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)
        r.keys.foreground = r.args.bve_pid
        r.publish(False, False, 1, load=CREATED)
        r.tick(2)
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_without_the_loaded_flag_of_the_overlay_no_token(self):
        r = self.r
        self.fresh_pause(ticks=2)
        self.o.is_bve_loaded = False
        r.press(F5)
        self.assertEqual(r.recovery.created, 0)


# ===================================================================================================================================================
class G_TheTimerFollowsTheRecovery(RecoveryCase):
    def test_a_waiting_state_is_watched_at_the_fast_interval_and_a_hidden_one_is_not(self):
        r = self.r
        r.tick(2)
        self.assertEqual(r.timer.intervals[-1], mh_idle())
        self.settled_pause()
        self.assertEqual(r.timer.intervals[-1], mh_active())
        r.publish(False, False, 1, load=0)
        r.tick(3)
        self.assertEqual(r.timer.intervals[-1], mh_idle())

    def test_a_pending_token_keeps_the_fast_interval(self):
        r = self.r
        self.arm()
        self.reload(2)
        self.assertEqual(r.hud.mode, "hidden")
        self.assertEqual(r.timer.intervals[-1], mh_active())


# ===================================================================================================================================================
class PauseIntentCase(RecoveryCase):
    """Phase SI-A6.2. Real machine (SF, SI-A6.1): P then F5 faster than the sender's STATUS (<= ~150 ms behind a P) - the newest STATUS was still RUNNING at the F5 edge, no token,
    no P-to-P, no HUD. The physical P is now watched: it records a short-lived PauseIntent that stands in for STATUS=PAUSED at the F5 edge, and does nothing else."""

    def running_session(self, generation=1, load=CREATED | TICK, driving=True):
        """A scenario that runs: Session ON, the sender says RUNNING (STATUS has arrived: the Overlay knows BVE is loaded)."""
        r = self.r
        r.publish(True, driving, generation, load=load)
        r.tick(2)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(3, seconds=0.05)

    def slot(self, *down, n=1, seconds=0.016):
        """n timer slots with exactly these virtual keys physically down (the 16 ms timer of the application)."""
        self.r.keys.down = set(down)
        self.r.tick(n, seconds=seconds)

    def release_all(self, n=1):
        self.slot(n=n)

    def finish_round_trip(self, generation=1):
        """Everything after the token: the reload, ScenarioCreated, the quiet time, the first P, the data, the BVE time, the second P, done - each P exactly once."""
        r = self.r
        g = generation + 1
        self.reload(g)
        self.assertEqual(r.recovery.token.phase, pr.PHASE_LOADING)
        self.assertEqual(self.p_count(), 0)                                   # no P before ScenarioCreated
        self.created(g)
        r.tick(8, seconds=0.05)
        self.assertEqual(self.p_count(), 1)                                   # the new data did not come by itself: first P
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 1)
        self.data_after_first_press(g)
        r.send(self.MR.tele(g, time_ms=36000500))                              # new telemetry, station list, the BVE time moved
        r.tick(3)
        self.assertEqual(self.p_count(), 2)
        r.send(self.MR.tele(g, time_ms=36001000))
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 2)                                   # first and second exactly once
        self.assertEqual(self.tokens(), ["armed", "loading", "done"])
        self.assertEqual(self.steps(), ["first", "second"])
        self.assertEqual((r.recovery.created, r.recovery.completed, r.recovery.expired), (1, 1, 0))
        self.assertEqual((r.recovery.first_presses, r.recovery.second_presses), (1, 1))
        for message in self.api.posted:
            self.assertEqual((message[0], message[2]), (5000, R.KEY_P))       # only P, only to the BVE window of this process: F5 is never re-sent

    def assertViaIntent(self):
        r = self.r
        self.assertEqual(r.recovery.created, 1)
        self.assertEqual(r.recovery.token.status0, "RUNNING")                  # the STATUS had not said PAUSED yet
        self.assertIn("via=pause-intent", r.events("recovery-token")[0])
        self.assertEqual((r.recovery.intents_created, r.recovery.intents_consumed), (1, 1))
        self.assertIsNone(r.recovery.intent)

    def assertNothingHappened(self, intents=None):
        r = self.r
        self.assertEqual((r.recovery.created, self.p_count(), self.tokens()), (0, 0, []))
        if intents is not None:
            self.assertEqual(r.recovery.intents_created, intents)


class I_MechanicalMinimumPF5(PauseIntentCase):
    """The completion condition: the shortest P -> F5 a machine can make, with the STATUS still RUNNING, makes the token and the whole recovery. A human is slower than this."""

    def test_1_p_down_p_up_then_f5_down_in_the_next_slot(self):
        self.running_session()
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.assertViaIntent()
        self.slot()
        self.finish_round_trip()

    def test_2_p_down_and_f5_down_in_the_same_observation_slot(self):
        self.running_session()
        self.slot(P, F5)                                                      # one slot sees both edges: the P is taken first
        self.assertViaIntent()
        self.slot()
        self.finish_round_trip()

    def test_3_p_then_f5_at_once_and_the_paused_status_arrives_late(self):
        for p_still_down in (False, True):
            with self.subTest(p_still_down=p_still_down):
                self.tearDown()
                self.setUp()
                r = self.r
                self.running_session()
                self.slot(P)
                self.slot(P, F5) if p_still_down else self.slot(F5)
                self.assertViaIntent()
                self.slot()
                self.assertEqual(r.hud._reader.last.generation, 1)
                r.send("STATUS:LOADED:PAUSED")                                # the STATUS comes AFTER the F5 edge
                r.tick(2)
                self.assertTrue(r.recovery.active)                            # one token, not disturbed
                self.assertEqual(r.recovery.created, 1)
                self.finish_round_trip()

    def test_4_the_paused_status_arrives_before_the_f5_the_existing_path(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        r.send("STATUS:LOADED:PAUSED")
        self.slot(n=3)
        self.assertIsNone(r.recovery.intent)                                  # the STATUS took over: the intent is gone
        self.assertEqual(r.recovery.last_intent_end, pr.I_PAUSED)
        self.slot(F5)
        self.assertEqual(r.recovery.created, 1)
        self.assertIn("via=status", r.events("recovery-token")[0])
        self.assertEqual((r.recovery.intents_created, r.recovery.intents_consumed), (1, 0))
        self.slot()
        self.finish_round_trip()

    def test_5_p_alone_sends_nothing_and_the_intent_dies_by_itself(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.assertIsNotNone(r.recovery.intent)
        self.slot()
        r.tick(100, seconds=0.05)
        self.assertIsNone(r.recovery.intent)
        self.assertEqual(r.recovery.last_intent_end, pr.I_TTL)
        self.assertNothingHappened(intents=1)

    def test_6_f5_alone_while_running_makes_no_token(self):
        self.running_session()
        self.slot(F5)
        self.slot()
        self.assertNothingHappened(intents=0)
        self.reload(2)
        self.created(2)
        self.r.tick(100, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_7_p_then_f5_while_already_paused_p_is_no_intent(self):
        r = self.r
        self.settled_pause()
        self.slot(P)                                                          # a P at PAUSED ends the Pause: not an intent to make one
        self.assertIsNone(r.recovery.intent)
        self.slot()
        self.slot(F5)
        self.assertEqual((r.recovery.created, r.recovery.intents_created), (1, 0))
        self.assertIn("via=status", r.events("recovery-token")[0])            # the (stale) STATUS=PAUSED path as before
        self.assertEqual(self.p_count(), 0)

    def test_8_p_that_ts_scoring_holds_back_is_no_intent_so_p_then_f5_makes_nothing(self):
        r = self.r
        r.go_active(speed=5.0)
        r.start_scoring_via_menu()
        self.assertTrue(self.scoring_on())
        r.publish(True, True, 1, load=CREATED | TICK)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(3, seconds=0.05)
        self.assertTrue(self.o.sys_keys_blocked)                              # TS Scoring holds P (and F7) back from BVE
        before = len(self.api.posted)                                         # (the scoring menu has P presses of its own: only what the recovery adds is judged)
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.slot()
        self.assertEqual((r.recovery.intents_created, r.recovery.created, len(self.api.posted) - before, r.events("kickstart")), (0, 0, 0, []))

    def test_8b_an_open_menu_holds_p_back_too(self):
        r = self.r
        r.go_active(speed=5.0)
        r.send("STATUS:LOADED:RUNNING")
        r.tap("f1")
        self.assertEqual(self.o.menu_state, 1)
        before = len(self.api.posted)
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.assertEqual((r.recovery.intents_created, r.recovery.created, len(self.api.posted) - before, r.events("kickstart")), (0, 0, 0, []))

    def test_9_p_then_f5_with_another_program_in_front(self):
        """(foreground at the P slot, between the slots, at the F5 slot): 'other' is the window of another process."""
        for p_fg, between_fg, f5_fg in (("other", "other", "other"), ("other", "bve", "bve"), ("bve", "other", "bve"), ("bve", "bve", "other")):
            with self.subTest(p=p_fg, between=between_fg, f5=f5_fg):
                self.tearDown()
                self.setUp()
                r = self.r
                self.running_session()
                pid = {"bve": r.args.bve_pid, "other": r.args.bve_pid + 1}
                r.keys.foreground = pid[p_fg]
                self.slot(P)
                r.keys.foreground = pid[between_fg]
                self.slot()
                r.keys.foreground = pid[f5_fg]
                self.slot(F5)
                self.slot()
                self.assertEqual((r.recovery.created, self.p_count()), (0, 0))
                self.reload(2)
                self.created(2)
                r.tick(60, seconds=0.05)
                self.assertEqual(self.p_count(), 0)
    def test_10_a_manual_p_while_the_token_is_pending_closes_it_and_sends_nothing(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.assertViaIntent()
        self.slot()
        for phase in ("armed", "loading"):
            with self.subTest(phase=phase):
                if phase == "loading":
                    self.reload(2)
                self.slot(P)
                self.slot()
                self.assertFalse(r.recovery.active)
                self.assertEqual(self.reasons()[-1], pr.R_MANUAL_P)
                if phase == "armed":
                    self.slot(F5)                                             # start again: a new token from the F5 (STATUS is not PAUSED, no intent: none)
                    self.slot()
                    self.assertFalse(r.recovery.active)
                    break
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_the_whole_round_trip_at_the_slowest_pace_the_intent_still_covers(self):
        """P, then F5 at the end of the intent's life (0.26 s of the 0.3 s) with the STATUS still RUNNING: still one token."""
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        r.tick(12, seconds=0.02)
        self.slot(F5)
        self.assertViaIntent()
        self.slot()
        self.finish_round_trip()


class J_PauseIntentContract(PauseIntentCase):
    # -- what makes an intent ------------------------------------------------------------------------------------------------------------------
    def test_a_p_edge_in_a_running_scenario_makes_one_intent_with_the_facts(self):
        r = self.r
        self.running_session(generation=3)
        self.slot(P)
        it = r.recovery.intent
        self.assertEqual((it.pid, it.generation, it.status0, it.consumed), (r.args.bve_pid, 3, "RUNNING", False))
        self.assertGreater(it.change_count, 0)
        self.assertEqual(r.recovery.intents_created, 1)
        self.assertEqual(self.api.posted, [])
        self.assertEqual(self.held(), [])
        self.assertEqual(self.tokens(), [])                                   # nothing is reported for an intent alone

    def test_one_intent_per_p_not_one_per_slot(self):
        r = self.r
        self.running_session()
        self.slot(P, n=30)
        self.assertEqual(r.recovery.intents_created, 1)

    def test_a_held_p_is_not_an_edge(self):
        r = self.r
        r.keys.down.add(P)
        self.running_session()                                                # P is held before anything is watched
        self.slot(P, n=5)
        self.assertEqual(r.recovery.intents_created, 0)

    def test_the_intent_alone_never_presses_anything(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        r.tick(200, seconds=0.05)
        self.assertEqual((self.p_count(), len(self.api.posted)), (0, 0))

    def test_no_intent_without_a_session(self):
        r = self.r
        r.tick(3)
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)
        r.publish(False, False, 1, load=CREATED)
        r.tick(2)
        self.slot()
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)

    def test_no_intent_when_the_status_is_paused_or_unknown(self):
        r = self.r
        r.publish(True, False, 1, load=CREATED | TICK)                        # no STATUS at all
        r.tick(3)
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)
        self.slot()
        r.send("STATUS:LOADED:PAUSED")
        r.tick(3, seconds=0.05)
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)

    def test_no_intent_for_a_p_in_another_program(self):
        r = self.r
        self.running_session()
        r.keys.foreground = r.args.bve_pid + 1
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)

    def test_no_intent_while_a_token_is_pending(self):
        r = self.r
        self.arm()
        self.slot(P)
        self.assertEqual(self.reasons(), [pr.R_MANUAL_P])
        self.assertEqual(r.recovery.intents_created, 0)
        self.assertIsNone(r.recovery.intent)

    def test_an_intent_in_the_waiting_mode_driving_off(self):
        r = self.r
        self.running_session(driving=False)
        self.assertEqual(r.hud.mode, "waiting")
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.assertViaIntent()

    # -- how it ends without a token -----------------------------------------------------------------------------------------------------------------
    def end_of_intent(self, why):
        self.assertIsNone(self.r.recovery.intent)
        self.assertEqual(self.r.recovery.last_intent_end, why)

    def f5_makes_no_token(self):
        self.slot(F5)
        self.slot()
        self.assertEqual((self.r.recovery.created, self.p_count()), (0, 0))

    def test_the_ttl_expires_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        r.tick(25, seconds=0.02)                                              # 0.5 s later
        self.end_of_intent(pr.I_TTL)
        self.f5_makes_no_token()

    def test_session_off_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.publish(False, False, 1, load=0)
        r.tick(2)
        self.end_of_intent(pr.I_STATE)
        r.publish(True, True, 1, load=CREATED | TICK)
        r.tick(2)
        self.f5_makes_no_token()

    def test_closed_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.publish(True, True, 1, closed=True, load=CREATED | TICK)
        r.tick(2)
        self.end_of_intent(pr.I_STATE)

    def test_the_loss_of_the_state_block_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.source.data = b""
        r.tick(3)
        self.assertIsNotNone(r.hud.failsafe)
        self.end_of_intent(pr.I_STATE)

    def test_stop_and_the_end_of_the_process_end_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.hud.shutdown()
        self.assertIsNone(r.recovery.intent)
        self.assertEqual(self.p_count(), 0)

    def test_another_generation_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.reload(2)
        self.assertIsNone(r.recovery.intent)
        self.created(2)
        r.publish(True, True, 2, load=CREATED | TICK)
        r.tick(2)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(2)
        self.f5_makes_no_token()

    def test_another_generation_with_the_session_still_on_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.publish(True, True, 2, load=CREATED | TICK)                        # a new scenario instance without a Session-OFF slot in between
        r.tick(2)
        self.end_of_intent(pr.I_GENERATION)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(2)
        self.f5_makes_no_token()

    def test_a_p_after_the_session_went_off_is_no_intent_even_with_a_running_status(self):
        r = self.r
        self.running_session()
        r.publish(False, False, 1, load=CREATED | TICK)
        r.tick(3)
        r.send("STATUS:LOADED:RUNNING")
        r.tick(2)
        self.assertTrue(self.o.is_bve_loaded)
        self.slot(P)
        self.assertEqual(r.recovery.intents_created, 0)
        snap = r.hud._reader.last                                             # (and the creation itself refuses a state without a Session, whatever calls it)
        self.assertFalse(snap.session)
        r.recovery._on_p_edge(snap, "hidden", r.hud.clock())
        self.assertIsNone(r.recovery.intent)

    def test_another_pid_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.recovery.intent.pid += 1
        r.tick(1)
        self.end_of_intent(pr.I_PID)
        self.f5_makes_no_token()

    def test_the_window_of_this_bve_not_in_front_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.keys.foreground = r.args.bve_pid + 1                                # another window, or this one is gone
        r.tick(1)
        self.end_of_intent(pr.I_FOREGROUND)
        r.keys.foreground = r.args.bve_pid
        self.f5_makes_no_token()

    def test_a_second_p_takes_the_pause_back_and_ends_it(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        self.slot(P)
        self.slot()
        self.assertEqual(r.recovery.intents_created, 1)
        self.end_of_intent(pr.I_REPEATED_P)
        self.f5_makes_no_token()

    def test_the_status_paused_ends_it_silently_and_the_status_is_the_evidence(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(2)
        self.end_of_intent(pr.I_PAUSED)
        self.assertEqual(self.tokens(), [])

    def test_the_intent_does_not_survive_a_running_bve_whatever_the_f5(self):
        """The P did not pause (a dialog, a key BVE ignored): the STATUS stays RUNNING, the intent dies by its TTL and a late F5 makes no token."""
        r = self.r
        self.running_session()
        self.slot(P)
        for _ in range(40):
            r.send("STATUS:LOADED:RUNNING")
            r.tick(1, seconds=0.02)
        self.end_of_intent(pr.I_TTL)
        self.f5_makes_no_token()

    # -- what an intent-made token does and does not do ---------------------------------------------------------------------------------------------
    def make_token(self):
        self.running_session()
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.slot()

    def test_the_intent_token_still_needs_the_generation_plus_one(self):
        r = self.r
        self.make_token()
        self.reload(3)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.reasons(), [pr.R_GENERATION_SKIPPED])
        self.assertEqual(self.p_count(), 0)

    def test_the_intent_token_expires_when_the_f5_reloads_nothing(self):
        r = self.r
        self.make_token()
        r.tick(60, seconds=0.05)
        self.assertEqual(self.reasons(), [pr.R_NO_RELOAD])
        self.assertEqual(self.p_count(), 0)

    def test_no_p_before_scenario_created(self):
        r = self.r
        self.make_token()
        self.reload(2)
        r.tick(400, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertTrue(r.recovery.active)

    def test_data_that_arrives_by_itself_means_no_p(self):
        r = self.r
        self.make_token()
        self.reload(2)
        self.created(2)
        r.send(self.MR.STALIST, self.MR.tele(2, time_ms=36000000))
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.reasons(), [pr.R_SELF_RECOVERED])

    def test_a_reload_that_ticks_by_itself_the_pause_was_not_made_means_no_p(self):
        r = self.r
        self.make_token()
        self.reload(2)
        self.created(2)
        r.publish(True, True, 2, load=CREATED | TICK)
        r.tick(2, seconds=0.03)
        r.tick(40, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.assertEqual(self.reasons(), [pr.R_SELF_RECOVERED])

    def test_a_list_load_after_a_p_without_f5_sends_nothing(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        r.send("STATUS:LOADED:PAUSED")
        r.tick(10, seconds=0.05)
        self.reload(2)                                                        # BVE's scenario list: no F5 edge
        self.created(2)
        r.tick(100, seconds=0.05)
        self.assertNothingHappened()

    def test_the_first_load_and_a_load_without_a_session_send_nothing(self):
        r = self.r
        self.slot(P)
        self.reload(1)
        self.created(1)
        r.tick(100, seconds=0.05)
        self.assertNothingHappened(intents=0)

    def test_an_older_bridge_or_caller_without_the_marker_sends_nothing_even_with_an_intent(self):
        r = self.r
        self.running_session(load=None)
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.slot()
        self.assertEqual(r.recovery.created, 0)
        self.assertEqual(self.tokens(), ["unavailable"])
        self.reload(2)
        self.created(2, load=None)
        r.tick(200, seconds=0.05)
        self.assertEqual(self.p_count(), 0)

    def test_without_the_loaded_flag_of_the_overlay_no_token(self):
        r = self.r
        self.running_session()
        self.slot(P)
        self.slot()
        self.o.is_bve_loaded = False
        self.slot(F5)
        self.assertEqual(r.recovery.created, 0)

    def test_the_f5_edge_uses_the_intent_up_even_when_it_makes_no_token(self):
        r = self.r
        self.running_session()
        self.slot(P)
        r.keys.foreground = r.args.bve_pid + 1
        self.slot(F5)                                                         # F5 in another program: no token, and the intent is spent
        self.assertIsNone(r.recovery.intent)
        r.keys.foreground = r.args.bve_pid
        self.slot()
        self.f5_makes_no_token()

    def test_a_second_pause_is_a_second_intent_and_a_second_recovery(self):
        r = self.r
        self.make_token()
        self.finish_round_trip_from_token()
        self.slot(P)
        self.slot()
        self.slot(F5)
        self.assertEqual(r.recovery.created, 2)
        self.assertEqual(r.recovery.intents_consumed, 2)

    def finish_round_trip_from_token(self):
        r = self.r
        self.reload(2)
        self.created(2)
        r.tick(8, seconds=0.05)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(3)
        self.assertEqual(self.p_count(), 2)
        r.send("STATUS:LOADED:RUNNING")
        r.publish(True, True, 2, load=CREATED | TICK)
        r.tick(3)

    def test_the_diagnostics_stay_few_and_fixed_words(self):
        r = self.r
        self.make_token()
        self.reload(2)
        self.created(2)
        r.tick(8, seconds=0.05)
        self.data_after_first_press(2)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(3)
        lines = r.events("recovery-token") + r.events("kickstart")
        self.assertLessEqual(len(lines), 5)
        for line in lines:
            self.assertIsNone(re.search(r"[\\/]|station|name", line.lower().replace("recovery-token", "")), line)
        self.assertIn("via=pause-intent", lines[0])
        self.assertEqual(len([l for l in r.events("recovery-token") if "state=armed" in l]), 1)

    def test_the_summary_reports_the_intent_counters(self):
        r = self.r
        self.make_token()
        r.hud.shutdown()
        summary = r.events("recovery-summary")
        self.assertTrue(summary)
        self.assertIn("rec_intent=1", summary[0])
        self.assertIn("rec_intent_used=1", summary[0])

    # -- structure: the intent is observation only -----------------------------------------------------------------------------------------------
    def test_only_the_two_token_steps_press_p(self):
        tree = ast.parse(read("pause_recovery.py"))
        callers = set()
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "press_p_for_recovery":
                        callers.add(fn.name)
        self.assertEqual(callers, {"_advance_loading", "_advance_first_sent"})
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "press_p_for_recovery"]
        self.assertEqual(len(calls), 2)

    def test_the_intent_code_reads_keys_only_through_the_key_api(self):
        text = read("pause_recovery.py")
        self.assertEqual(sorted(set(re.findall(r"self\._keys\.(\w+)", text))), ["foreground_pid", "is_down"])
        self.assertEqual(sorted(set(re.findall(r"user32\.(\w+)", text))), ["GetAsyncKeyState", "GetForegroundWindow", "GetWindowThreadProcessId"])
        tree = ast.parse(text)
        imports = sorted({a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names})
        self.assertEqual(imports, ["ctypes", "managed_state", "time"])

    def test_the_intent_has_no_path_to_begin_but_the_f5_edge(self):
        text = read("pause_recovery.py")
        self.assertEqual(re.findall(r"self\.begin\((\w+)", text), ["KIND_F5_RELOAD"])
        self.assertEqual(len(re.findall(r"self\.intent = PauseIntent\(", text)), 1)


def mh_idle():
    import managed_hud
    return managed_hud.IDLE_INTERVAL_MS


def mh_active():
    import managed_hud
    return managed_hud.ACTIVE_INTERVAL_MS


if __name__ == "__main__":
    unittest.main()
