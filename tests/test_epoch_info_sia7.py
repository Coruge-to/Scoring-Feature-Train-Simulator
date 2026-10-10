"""Phase SI-A7 (M1a) - the Ready epoch of the Bridge as the managed application sees it: parsed and shown, and NOTHING acts on it.

The Caller copies the Bridge's Ready epoch (ReadyEpoch + TickSeenInEpoch) into the 4 bytes at offset 56 of its state block (AppStatePublisher.cs, "EpochInfo").
`Session ON with TickSeenInEpoch = 0` can only be a held ScenarioReady that was published again WITHOUT a Tick (TS Scoring switched OFF -> ON during a pause).
M1a is the observation step: managed_state.py reads the word, managed_hud.py writes one diagnostic line when it changes, and that is all. In particular
  * no recovery token is created from it (KIND_SCORING_ON has no creation path; IMPLEMENTED_KINDS is unchanged),
  * no key (P, F5, anything) is sent because of it - first P, second P and the "Pause re-ON recovery" belong to M1b, which this phase does not start,
  * an old Bridge / Caller (EpochInfo 0) behaves exactly as before.
Layers: (A) the word: layout, parsing, "no information" and the rejections that must not change; (B) the old application reading the new block;
(C) a real Windows mapping; (D) the diagnostic line; (E) no token / no key whatever the epoch says; (F) static guards.
"""
import os
import re
import subprocess
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import managed_state as ms  # noqa: E402
import pause_recovery as pr  # noqa: E402
import test_managed_hud_e4 as E4  # noqa: E402
import test_pause_recovery_sia6 as SIA6  # noqa: E402
import sia_rig as R  # noqa: E402

CALLER_SRC = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Caller", "src")
BEFORE_SIA7_COMMIT = "42850d1b897493bef10afc5130ae3d790fb4d5ea"        # the last commit before Phase SI-A7: the managed_state.py of the "old application"
CREATED = ms.LOAD_CREATED
TICK = ms.LOAD_TICK_SEEN


def info(number, tick):
    """The EpochInfo word for (ReadyEpoch, TickSeenInEpoch), packed the way AppStateLayout.PackEpochInfo does."""
    return ms.EPOCH_SUPPORTED | (ms.EPOCH_TICK_SEEN if tick else 0) | ((number & 0xFFFF) << 8)


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def git_show(commit, name):
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (commit, name)], capture_output=True, timeout=60)
    except Exception:
        return None
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


# ===================================================================================================================================================
class A_TheEpochInfoWord(unittest.TestCase):
    def setUp(self):
        self.inst = E4.new_instance()
        self.pid = 4242

    def parse(self, **kw):
        return ms.parse_state(E4.make_block(self.pid, self.inst, **kw), self.pid, self.inst)

    def test_layout_is_the_one_the_caller_documents(self):
        text = read(CALLER_SRC, "AppStatePublisher.cs")
        self.assertIn("56 uint32  EpochInfo", text)
        self.assertEqual(ms.OFF_EPOCH_INFO, 56)
        self.assertEqual(ms.OFF_EPOCH_INFO + ms._EPOCH.size, ms.OFF_TAIL)                     # 56..59, then the tail at 60
        self.assertEqual((ms.EPOCH_SUPPORTED, ms.EPOCH_TICK_SEEN, ms.EPOCH_NUMBER_SHIFT, ms.EPOCH_NUMBER_MASK), (1, 2, 8, 0xFFFF))
        for name, value in (("OffEpochInfo", 56), ("EpochSupported", 1), ("EpochTickSeen", 2), ("EpochNumberShift", 8), ("EpochNumberMask", 0xFFFF)):
            m = re.search(r"public const (?:int|uint) %s = (0x[0-9A-Fa-f]+|\d+)u?;" % name, text)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1), 0), value, name)
        # Version, Size and every earlier offset are unchanged
        self.assertEqual((ms.STATE_VERSION, ms.STATE_SIZE, ms.OFF_HEAD, ms.OFF_FLAGS, ms.OFF_GENERATION, ms.OFF_CHANGE_COUNT, ms.OFF_LOAD_INFO, ms.OFF_LOAD_MAGIC, ms.OFF_TAIL),
                         (1, 64, 32, 36, 40, 44, 48, 52, 60))

    def test_a_block_without_the_word_is_no_information_and_not_an_error(self):
        snap, reason = self.parse(session=True, driving=True, generation=3, count=2, load_info=CREATED | TICK, load_magic=ms.LOAD_MAGIC)
        self.assertIsNone(reason)
        self.assertEqual((snap.epoch_info, snap.epoch_supported, snap.epoch_tick_seen, snap.ready_epoch), (0, False, False, 0))

    def test_the_word_is_read_together_with_everything_else(self):
        for number, tick in ((1, False), (1, True), (2, False), (2, True), (7, False), (65535, True)):
            snap, reason = self.parse(session=True, driving=False, generation=5, count=4, load_info=CREATED | TICK, load_magic=ms.LOAD_MAGIC, epoch_info=info(number, tick))
            self.assertIsNone(reason, (number, tick))
            self.assertEqual((snap.epoch_supported, snap.epoch_tick_seen, snap.ready_epoch), (True, tick, number), (number, tick))
            self.assertEqual((snap.session, snap.driving, snap.generation, snap.change_count, snap.load_supported, snap.load_info), (True, False, 5, 4, True, CREATED | TICK))

    def test_the_epoch_number_is_the_low_16_bits(self):
        snap, _ = self.parse(epoch_info=info(0x12345, False))
        self.assertEqual(snap.ready_epoch, 0x2345)
        snap, _ = self.parse(epoch_info=info(0x10000, True))
        self.assertEqual((snap.epoch_supported, snap.ready_epoch, snap.epoch_tick_seen), (True, 0, True))     # a wrapped number is still "supported"

    def test_a_word_that_does_not_parse_is_no_information_never_an_error(self):
        # no Supported bit, an unknown bit in 2..7, an unknown bit in 24..31: the information is dropped, the block stays valid (a loss of the block would end the HUD)
        for bad in (0x00000002, 0x00000100, 0x0000FF00, 0x00000004, 0x00000008, 0x00000080 | 1, 0x01000000 | 1, 0x80000000 | 1, 0xFFFFFFFF, 0xFFFFFFFE):
            snap, reason = self.parse(session=True, generation=2, count=1, epoch_info=bad)
            self.assertIsNone(reason, hex(bad))
            self.assertEqual((snap.epoch_info, snap.epoch_supported, snap.epoch_tick_seen, snap.ready_epoch), (0, False, False, 0), hex(bad))
            self.assertEqual((snap.session, snap.generation), (True, 2))

    def test_every_rejection_of_the_block_still_holds_whatever_the_word_says(self):
        good = info(2, False)
        cases = {
            "short": E4.make_block(self.pid, self.inst, epoch_info=good)[:63], "magic": E4.make_block(self.pid, self.inst, magic=1, epoch_info=good),
            "version": E4.make_block(self.pid, self.inst, version=2, epoch_info=good), "size": E4.make_block(self.pid, self.inst, size=128, epoch_info=good),
            "pid": E4.make_block(self.pid + 1, self.inst, epoch_info=good), "instance": E4.make_block(self.pid, E4.new_instance(), epoch_info=good),
            "torn": E4.make_block(self.pid, self.inst, head=3, tail=3, epoch_info=good), "flags": E4.make_block(self.pid, self.inst, flags=8, epoch_info=good),
        }
        for reason, data in cases.items():
            snap, got = ms.parse_state(data, self.pid, self.inst)
            self.assertIsNone(snap, reason)
            self.assertEqual(got, reason)
        self.assertEqual(ms.parse_state(E4.make_block(self.pid, self.inst, head=4, tail=6, epoch_info=good), self.pid, self.inst)[1], "torn")

    def test_a_snapshot_built_the_old_way_has_no_epoch(self):
        snap = ms.StateSnapshot(True, False, False, 2, 1, 2)                              # the eight-argument form of every earlier test
        self.assertEqual((snap.epoch_info, snap.epoch_supported, snap.epoch_tick_seen, snap.ready_epoch), (0, False, False, 0))
        self.assertEqual(ms.StateSnapshot(True, False, False, 2, 1, 2, True, 1), ms.StateSnapshot(True, False, False, 2, 1, 2, True, 1, 0))

    def test_an_epoch_flag_without_the_supported_bit_is_not_carried_by_the_constructor(self):
        self.assertEqual(ms.StateSnapshot(False, False, False, 0, 0, 0, False, 0, 0x300).epoch_info, 0)

    def test_the_epoch_is_part_of_snapshot_identity_but_the_gate_ignores_it(self):
        a = ms.StateSnapshot(True, True, False, 4, 1, 2, True, 3, info(2, False))
        b = ms.StateSnapshot(True, True, False, 4, 2, 4, True, 3, info(2, True))
        self.assertNotEqual(a, b)
        g = ms.HudGate()
        self.assertIsNotNone(g.apply(a))
        self.assertIsNone(g.apply(b))                                                     # the tick flag alone changes no HUD state
        c = ms.StateSnapshot(True, True, False, 4, 3, 6, True, 3, 0)
        self.assertIsNone(g.apply(c))                                                     # nor does losing the information

    def test_epoch_changes_and_tick_changes_are_visible_through_the_reader(self):
        args = E4.args_for()
        source = E4.FakeSource(E4.make_block(args.bve_pid, args.instance))
        reader = ms.StateReader(args, source, E4.Log())
        self.assertTrue(reader.open())
        self.assertFalse(reader.last.epoch_supported)
        seen = []
        for count, (number, tick) in enumerate(((1, False), (1, True), (2, False), (2, False), (2, True), (3, False)), start=1):
            source.data = E4.make_block(args.bve_pid, args.instance, True, True, False, 4, count, load_info=CREATED | TICK, load_magic=ms.LOAD_MAGIC, epoch_info=info(number, tick))
            snap = reader.poll()
            seen.append((snap.ready_epoch, snap.epoch_tick_seen))
        self.assertEqual(seen, [(1, False), (1, True), (2, False), (2, False), (2, True), (3, False)])
        source.data = E4.make_block(args.bve_pid, args.instance, True, True, False, 4, 9)
        self.assertFalse(reader.poll().epoch_supported)                                   # the information can disappear again (an older Bridge, a withdrawn state)
        self.assertIsNone(reader.lost)


# ===================================================================================================================================================
class B_TheOldApplicationReadsTheNewBlock(unittest.TestCase):
    """A managed_state.py from before Phase SI-A7 (the last commit before it) must read a block that carries the new word exactly as before."""

    @classmethod
    def setUpClass(cls):
        text = git_show(BEFORE_SIA7_COMMIT, "managed_state.py")
        if text is None:
            raise unittest.SkipTest("git or the pre-SI-A7 commit is not available")
        cls.old = types.ModuleType("managed_state_before_sia7")
        cls.old.__file__ = os.path.join(ROOT, "managed_state_before_sia7.py")
        exec(compile(text, cls.old.__file__, "exec"), cls.old.__dict__)

    def test_the_old_module_has_no_epoch_at_all(self):
        self.assertFalse(hasattr(self.old, "OFF_EPOCH_INFO"))
        self.assertFalse(hasattr(self.old.StateSnapshot, "epoch_supported"))

    def test_the_old_parse_ignores_the_word_and_returns_the_same_state(self):
        inst, pid = E4.new_instance(), 4242
        for word in (0, info(1, False), info(2, True), info(65535, False), 0xFFFFFFFF):
            data = E4.make_block(pid, inst, True, True, False, 6, 3, load_info=CREATED | TICK, load_magic=ms.LOAD_MAGIC, epoch_info=word)
            old, old_reason = self.old.parse_state(data, pid, inst)
            new, new_reason = ms.parse_state(data, pid, inst)
            self.assertIsNone(old_reason, hex(word))
            self.assertIsNone(new_reason, hex(word))
            for field in ("session", "driving", "closed", "generation", "change_count", "head", "load_supported", "load_info"):
                self.assertEqual(getattr(old, field), getattr(new, field), (field, hex(word)))

    def test_the_old_parse_rejects_what_the_new_one_rejects(self):
        inst, pid = E4.new_instance(), 4242
        for kw in (dict(magic=1), dict(version=2), dict(size=128), dict(head=3, tail=3), dict(flags=8)):
            data = E4.make_block(pid, inst, epoch_info=info(2, False), **kw)
            self.assertEqual(self.old.parse_state(data, pid, inst)[1], ms.parse_state(data, pid, inst)[1], kw)


# ===================================================================================================================================================
class C_ARealWindowsMapping(unittest.TestCase):
    def setUp(self):
        self.args = E4.args_for()
        self.log = E4.Log()
        self.writer = E4.Win32BlockWriter(self.args.bve_pid, self.args.instance)

    def tearDown(self):
        self.writer.dispose()

    def put(self, count, number, tick, session=True):
        self.writer._put(E4.make_block(self.args.bve_pid, self.args.instance, session, session, False, 2, count, load_info=CREATED, load_magic=ms.LOAD_MAGIC,
                                       epoch_info=0 if number is None else info(number, tick)))

    def test_the_word_travels_through_a_real_named_mapping(self):
        reader = ms.StateReader(self.args, ms.Win32StateSource(), self.log)
        try:
            self.assertTrue(reader.open())
            self.assertFalse(reader.last.epoch_supported)
            self.put(1, 2, False)
            snap = reader.poll()
            self.assertEqual((snap.epoch_supported, snap.ready_epoch, snap.epoch_tick_seen, snap.generation), (True, 2, False, 2))
            self.put(2, 2, True)
            self.assertTrue(reader.poll().epoch_tick_seen)
            self.put(3, None, False)
            self.assertFalse(reader.poll().epoch_supported)
            self.assertIsNone(reader.lost)
        finally:
            reader.close()


# ===================================================================================================================================================
class D_TheDiagnosticLine(E4.ControllerCase):
    """managed_hud.py writes one `epoch-info` line when the epoch changes - and not a single line for a block that never had one."""

    def publish_epoch(self, session, number, tick, generation=1):
        self.count += 1
        self.source.data = E4.make_block(self.args.bve_pid, self.args.instance, session, session, False, generation, self.count, load_info=CREATED | TICK,
                                         load_magic=ms.LOAD_MAGIC, epoch_info=0 if number is None else info(number, tick))

    def test_a_block_without_the_word_never_produces_the_line(self):
        self.hud.start()
        self.publish(True, True, 1)
        self.pump(200)
        self.publish(True, False, 2)
        self.pump(50)
        self.assertEqual(self.log.events("epoch-info"), [])

    def test_one_line_per_change_with_what_it_was(self):
        self.hud.start()
        self.publish_epoch(True, 1, False)
        self.pump(5)
        self.publish_epoch(True, 1, False)
        self.pump(5)                                                                      # identical: nothing
        self.publish_epoch(True, 1, True)
        self.pump(5)
        self.publish_epoch(True, 2, False)
        self.pump(5)
        self.publish_epoch(True, None, False)
        self.pump(5)
        lines = self.log.events("epoch-info")
        self.assertEqual(len(lines), 4, lines)
        self.assertIn("ready_epoch=1", lines[0])
        self.assertIn("supported=1", lines[0])
        self.assertIn("tick_seen=0", lines[0])
        self.assertIn("was_supported=0", lines[0])
        self.assertIn("tick_seen=1", lines[1])
        self.assertIn("was_tick_seen=0", lines[1])
        self.assertIn("ready_epoch=2", lines[2])
        self.assertIn("was_epoch=1", lines[2])
        self.assertIn("supported=0", lines[3])
        self.assertIn("was_supported=1", lines[3])
        for line in lines:
            self.assertLessEqual(len(line), 160, line)                                    # the Caller transcribes at most 160 characters of an application line

    def test_an_epoch_that_is_already_there_at_start_is_reported_once(self):
        self.count += 1
        self.source.data = E4.make_block(self.args.bve_pid, self.args.instance, True, False, False, 3, self.count, epoch_info=info(2, False))
        self.hud.start()
        self.pump(20)
        lines = self.log.events("epoch-info")
        self.assertEqual(len(lines), 1)
        self.assertIn("ready_epoch=2", lines[0])
        self.assertIn("session=1", lines[0])

    def test_the_line_changes_neither_the_hud_state_nor_the_state_lines(self):
        self.hud.start()
        self.publish_epoch(True, 1, False)
        self.pump(5)
        before = (self.hud.mode, len(self.log.events("state")), self.overlay.shows)
        self.publish_epoch(True, 1, True)
        self.pump(5)
        self.publish_epoch(True, 2, False)
        self.pump(5)
        self.assertEqual((self.hud.mode, len(self.log.events("state")), self.overlay.shows), before)

    def test_the_line_names_no_value_that_is_not_a_number_or_a_flag(self):
        self.hud.start()
        self.publish_epoch(True, 5, True)
        self.pump(3)
        line = self.log.events("epoch-info")[0]
        for key, value in re.findall(r"(\w+)=(\S+)", line):
            if key in ("event", "pid"):
                continue
            self.assertRegex(value, r"^\d+$", key)


# ===================================================================================================================================================
class E_NothingActsOnTheEpoch(SIA6.RecoveryCase):
    """Whatever the epoch says, no recovery token is created and no key is sent. (Every condition of the future `scoring-on` token is made true here.)"""

    def paused_with_epoch(self, epoch, generation=1, ticks=40):
        r = self.r
        r.publish(True, True, generation, load=CREATED | TICK, epoch=epoch)
        r.tick(2)
        r.send("STATUS:LOADED:PAUSED")
        r.tick(ticks, seconds=0.05)

    def assert_nothing_happened(self):
        r = self.r
        self.assertFalse(r.recovery.active)
        self.assertEqual(r.events("recovery-token"), [])
        self.assertEqual(r.events("kickstart"), [])
        self.assertEqual(self.api.posted, [])                                             # not a single posted key of any kind
        self.assertEqual(self.p_count(), 0)

    def test_every_condition_of_the_future_token_true_and_still_nothing(self):
        # Session ON, Driving ON (the Caller's own Tick goes on in a Pause), load marker supported, epoch supported, TickSeenInEpoch = 0, STATUS PAUSED for 2 s,
        # no telemetry of the generation, the BVE window found: this is the picture M1b will react to. M1a must not.
        self.paused_with_epoch((2, False), ticks=60)
        self.r.tick(100, seconds=0.05)
        self.assert_nothing_happened()

    def test_the_epoch_moving_through_all_its_states_creates_nothing(self):
        for epoch in ((1, False), (1, True), (2, False), (2, True), (3, False), None, (4, False)):
            self.paused_with_epoch(epoch, ticks=30)
        self.assert_nothing_happened()

    def test_a_new_epoch_while_paused_is_not_a_reason_to_press_anything(self):
        self.paused_with_epoch((1, True))
        self.r.publish(True, True, 1, load=CREATED | TICK, epoch=(2, False))              # TS Scoring switched OFF -> ON during the pause
        self.r.tick(100, seconds=0.05)
        self.assert_nothing_happened()

    def test_the_epoch_does_not_disturb_the_f5_recovery_that_exists(self):
        # The whole F5 round trip of SI-A6 with an epoch in every block (the epoch persists across publish()): one token, first P once, second P once, same words
        r = self.r
        r.publish(False, False, 0, epoch=(2, False))
        self.arm()
        self.reload(2)
        self.assertEqual(r.recovery.token.phase, pr.PHASE_LOADING)
        r.tick(300, seconds=0.05)
        self.assertEqual(self.p_count(), 0)
        self.created(2)
        r.tick(9, seconds=0.05)
        self.assertEqual(self.p_count(), 1)
        self.data_after_first_press(2, time_ms=36000000)
        r.send(self.MR.tele(2, time_ms=36000500))
        r.tick(2)
        self.assertEqual(self.p_count(), 2)
        self.assertEqual((r.recovery.completed, r.recovery.first_presses, r.recovery.second_presses), (1, 1, 1))
        r.tick(60, seconds=0.05)
        self.assertEqual(self.p_count(), 2)
        self.assertEqual(self.tokens(), ["armed", "loading", "done"])
        self.assertEqual(self.steps(), ["first", "second"])

    def test_the_implemented_kinds_are_the_ones_of_sia6(self):
        self.assertEqual(pr.IMPLEMENTED_KINDS, frozenset((pr.KIND_F5_RELOAD,)))
        self.assertEqual(set(pr.ALL_KINDS) - pr.IMPLEMENTED_KINDS, {pr.KIND_TIMETABLE_JUMP, pr.KIND_SCORING_ON})
        self.assertEqual((pr.FIRST_QUIET_S, pr.SECOND_MAX_S, pr.F5_TO_GENERATION_MAX_S, pr.PAUSE_INTENT_TTL_S), (0.3, 10.0, 2.0, 0.3))

    def test_asking_for_a_scoring_on_token_is_still_refused(self):
        r = self.r
        self.paused_with_epoch((2, False))
        snap = r.hud._reader.last
        for kind in (pr.KIND_SCORING_ON, pr.KIND_TIMETABLE_JUMP):
            self.assertFalse(r.recovery.begin(kind, snap, "status"))
        self.assert_nothing_happened()


# ===================================================================================================================================================
class F_StaticGuards(unittest.TestCase):
    EPOCH_NAMES = re.compile(r"epoch_supported|epoch_tick_seen|ready_epoch|epoch_info|OFF_EPOCH_INFO|EPOCH_SUPPORTED|EPOCH_TICK_SEEN")

    def test_only_the_state_reader_and_the_diagnostic_line_know_the_epoch(self):
        for name in sorted(n for n in os.listdir(ROOT) if n.endswith(".py")):
            text = read(ROOT, name)
            if name in ("managed_state.py", "managed_hud.py"):
                self.assertRegex(text, self.EPOCH_NAMES, name)
            else:
                self.assertNotRegex(text, self.EPOCH_NAMES, name)

    def test_the_hud_reads_the_epoch_of_a_snapshot_in_one_method_only(self):
        text = read(ROOT, "managed_hud.py")
        start = text.index("    def _note_epoch(self, snapshot):")
        end = text.index("    def _on_generation(self, generation):")
        outside = text[:start] + text[end:]
        self.assertEqual(re.findall(r"snapshot\.(?:epoch_\w+|ready_epoch)", outside), [])
        self.assertEqual(len(re.findall(r"self\._note_epoch\(snapshot\)", text)), 2)         # tick() and start(): nothing else calls it
        self.assertEqual(len(re.findall(r"_epoch_last", text)), 4)

    def test_no_new_press_path_and_no_scoring_on_creation(self):
        text = read(ROOT, "pause_recovery.py")
        self.assertEqual(len(re.findall(r"self\._o\.press_p_for_recovery\(", text)), 2)   # _advance_loading and _advance_first_sent: the SI-A6 call sites, no third
        self.assertIn("IMPLEMENTED_KINDS = frozenset((KIND_F5_RELOAD,))", text)
        self.assertNotIn("epoch", text.lower())
        self.assertEqual(len(re.findall(r"KIND_SCORING_ON", text)), 2)                    # the constant and ALL_KINDS - no creation path
        unchanged = git_show(BEFORE_SIA7_COMMIT, "pause_recovery.py")
        if unchanged is not None:
            self.assertEqual(text.replace("\r\n", "\n"), unchanged.replace("\r\n", "\n"), "pause_recovery.py is not part of Phase SI-A7 M1a")

    def test_the_other_modules_of_the_application_are_untouched_by_this_phase(self):
        for name in ("managed_input.py", "managed_mode.py", "main.py", "scoring_logic.py", "telemetry_gate.py", "telemetry_contract.py", "hud_ui.py", "menu_ui.py"):
            before = git_show(BEFORE_SIA7_COMMIT, name)
            if before is None:
                self.skipTest("git or the pre-SI-A7 commit is not available")
            self.assertEqual(read(ROOT, name).replace("\r\n", "\n"), before.replace("\r\n", "\n"), name)

    def test_the_state_reader_still_ignores_unknown_bits_it_does_not_understand(self):
        text = read(ROOT, "managed_state.py")
        self.assertIn("anything else is \"no information\"", text)
        self.assertNotIn("raise", text[text.index("def parse_state"):text.index("# Sources of the 64 bytes")])


if __name__ == "__main__":
    unittest.main()
