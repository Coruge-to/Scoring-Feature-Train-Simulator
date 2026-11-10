"""Stage TB-D, slice D3 (OD-TD-3, entry E10): a Retry accepted while a pseudo-turnback chain is RECOGNIZED / ARMED (the 5.0 s window after the A arrival) must drop that chain and everything that hangs on it.
Before this slice the chain survived the Retry and, when the BVE time reached the OLD arrival + 5.0 s, the product requested a Jump to B although the train had not arrived at A again (measured at 5f36e62:
Stage 0 raw/probe-out.txt: the request came at the old arrival + 5004 ms). The REAL execute_retry, the REAL update_physics_and_scoring driver and the REAL settlement are used; execute_retry itself is not changed.
R-9 (what the SENDER does with arr_seq after a Retry) is UNKNOWN and is not guessed here: RT-7 only characterizes what the Python receiver does with a repeated key."""
import ast
import hashlib
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pseudo_turnback_machine as M  # noqa: E402

_TMP = {}


def setUpModule():
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-tbd-retry-")
    _TMP["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP["dir"].name
    os.environ["HOME"] = _TMP["dir"].name


def tearDownModule():
    for k, v in _TMP["saved"].items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _TMP["dir"].cleanup()


def source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


EXECUTE_RETRY_SHA256 = "95F04D666D9F696C49FE9FA1E64826B4169F49E63B4884D860EB9483081D87F0"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["tbd-retry"])
        import main
        import scoring_logic
        import pt_scene
        cls.main, cls.S, cls.P = main, scoring_logic, pt_scene

    def requests(self):
        """Counts the real turnback requests (the product function is wrapped, not replaced)."""
        calls = []
        original = self.S.turnback_request

        def spy(owner, request):
            calls.append((owner.bve_time_ms, request["target_index"]))
            return original(owner, request)
        self.S.turnback_request = spy
        self.addCleanup(lambda: setattr(self.S, "turnback_request", original))
        return calls

    def armed(self, special=False):
        s = self.P.Scene(self)
        if special:
            s.o.setting_start_idx, s.o.setting_end_idx = 0, 4
            s.o.bve_time_ms = self.P.T0 + 90000 - 5000 - 600
            s.o.bve_next_time = self.P.T0 + 90000
            s.approach("stepwise")
            s.stop_at(0.0)
            t = s.open_door()
        else:
            t = s.arrive_a()
        self.assertEqual(s.machine.state, M.ARMED)
        return s, t

    def settle_retry(self, s):
        o = s.o
        self.assertIsNotNone(o.jump_expectation)
        s.jump_tick()
        s.complete()
        self.assertIsNone(o.jump_expectation)
        self.assertFalse(o.is_official_jumping)

    def rearrive(self, s, seq, late_ms=20000):
        """The train goes on after the Retry (the departure releases the jump lock of the Retry) and arrives at A again with the arrival sequence number `seq`."""
        P, o = self.P, s.o
        s.step(3, bve_speed=20.0, bve_door=0, bve_location=100.0)
        o.bve_time_ms = P.T0 + 90000 - late_ms - 600
        o.bve_next_time = P.T0 + 90000
        s.step(1, bve_next_loc=P.A_MARK, bve_tgt_idx=1, bve_arr_idx=0, bve_speed=20.0, bve_location=P.A_MARK - 400.0)
        s.approach("plain")
        s.stop_at(0.3)
        s.step(1, bve_door=1, bve_arr_idx=1, bve_arr_seq=seq)
        return o.bve_time_ms

    def run_until(self, s, until_ms):
        guard = 0
        while s.o.bve_time_ms < until_ms and guard < 100000:
            s.tick(advance_ms=250, bve_speed=20.0, bve_location=100.0)
            guard += 1


class A_RetryWhileArmed(Base):
    def test_RT_1_no_jump_is_requested_at_the_old_arrival_plus_5_seconds(self):
        for special in (False, True):
            with self.subTest(special=special):
                calls = self.requests()
                s, t_a = self.armed(special)
                res = self.main.execute_retry(s.o, 0, False)
                self.assertTrue(res.accepted, res)                         # RT-2: the Retry itself is accepted
                self.settle_retry(s)
                self.run_until(s, t_a + 6000)
                self.assertEqual(calls, [], "no request without an arrival at A")
                self.assertNotEqual(s.machine.state, M.REQUESTED)
                self.assertIsNone(s.o.jump_expectation)

    def test_RT_2_the_retry_itself_is_unchanged(self):
        s, t_a = self.armed()
        before_score = s.o.score
        res = self.main.execute_retry(s.o, 0, False)
        self.assertTrue(res.accepted)
        self.assertEqual(s.o.score, s.o.save_data[0]["score"], "the score of the checkpoint is restored as ever")
        self.assertIsNotNone(s.o.retry_pending)
        self.settle_retry(s)
        self.assertEqual(len(s.o.save_data), 1)

    def test_RT_3_a_new_arrival_after_the_retry_starts_one_new_chain_from_the_new_arrival_only(self):
        calls = self.requests()
        s, t_old = self.armed()
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)
        self.settle_retry(s)
        t_new = self.rearrive(s, seq=2)
        self.assertNotEqual(t_new, t_old)
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertEqual(s.machine.arrival_ms, t_new, "the new chain belongs to the new arrival")
        s.run_to_request(t_new)
        self.assertEqual(calls, [(t_new + 10000, 2)], "exactly one request, at the NEW arrival + 10.0 s (Stage TB-H 5b (on purpose); it was 5.0 s)")

    def test_RT_4_everything_that_hangs_on_the_old_chain_is_gone(self):
        s, t_a = self.armed()
        s.tick(advance_ms=6000)                                       # Stage TB-H 5b (on purpose): the guidance of the first window is on from 5.0 s
        self.assertTrue(s.popups("疑似折り返し"), "the guidance of the old chain is on the screen")
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)
        self.settle_retry(s)
        s.step(2)
        m, o = s.machine, s.o
        self.assertEqual((m.state, m.arrival_ms, m.pair, m.key, m.awaiting_b), (M.IDLE, None, None, None, False))
        self.assertTrue(m.settlement is None or m.settlement.purpose == "retry", "only the record of the Retry itself may remain")
        self.assertEqual((m.landing, m.b_watch), (None, None))
        self.assertEqual(s.popups("疑似折り返し"), [], "the 5 s guidance of the old arrival is removed")
        self.assertIsNone(o.jump_expectation)
        self.assertFalse(self.S.official_jump_f1_hold(o), "no F1 hold of the old chain")
        self.assertIsNotNone(m.fixed, "the fixed section of the Run stays (the Run goes on)")

    def test_RT_5_repeated_retries_never_bring_the_old_chain_back(self):
        calls = self.requests()
        s, t_a = self.armed()
        first = self.main.execute_retry(s.o, 0, False)
        self.assertTrue(first.accepted)
        second = self.main.execute_retry(s.o, 0, False)                    # a second request while the first is still in flight (accepted or refused: either way)
        self.assertIn(second.accepted, (True, False))
        self.settle_retry(s)
        self.run_until(s, t_a + 11000)                                # Stage TB-H 5b (on purpose): past the old 10.0 s request time
        self.assertEqual(calls, [])
        self.assertEqual(s.machine.state, M.IDLE)

    def test_RT_6_a_chain_of_another_generation_or_session_is_not_reused(self):
        for how in ("generation", "session-off"):
            with self.subTest(how=how):
                s, t_a = self.armed()
                if how == "generation":
                    s.o.current_scenario_id = s.o.current_scenario_id + 1
                else:
                    s.o.is_scoring_mode = False
                s.step(1)
                self.assertIn(s.machine.state, (M.IDLE, M.DISCARDED))

    def test_RT_7_characterization_a_repeated_arrival_key_after_a_completed_request(self):
        """UNKNOWN on the sender side (R-9). The receiver: the key (generation, list_id, A, arr_seq) that was REQUESTED is never requested again (PU-7)."""
        calls = self.requests()
        s, t_a = self.armed()
        s.run_to_request(t_a)
        self.assertEqual(len(calls), 1)
        s.jump_tick()
        s.complete()
        o = s.o
        o.bve_arr_idx = 2
        s.step(10)
        self.assertTrue(self.main.execute_retry(o, 0, False).accepted)
        self.settle_retry(s)
        t2 = self.rearrive(s, seq=1)                                          # the SAME arrival sequence number as the requested one: a repeated key
        self.assertEqual(s.machine.state, M.IDLE, "PU-7: the issued key is not requested twice")
        s.tick(advance_ms=t2 + 6000 - o.bve_time_ms)
        self.assertEqual(len(calls), 1)

    def test_RT_7b_characterization_a_new_arrival_sequence_number_after_a_completed_request_is_a_new_arrival(self):
        """UNKNOWN on the sender side (R-9): what the sender writes as arr_seq after a Retry. The receiver: a different key is a new arrival and starts a new chain."""
        s, t_a = self.armed()
        s.run_to_request(t_a)
        s.jump_tick()
        s.complete()
        s.o.bve_arr_idx = 2
        s.step(10)
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)
        self.settle_retry(s)
        self.rearrive(s, seq=2)
        self.assertEqual(s.machine.state, M.ARMED)

    def test_RT_10_the_issued_key_of_an_earlier_request_survives_the_drop_of_a_waiting_chain(self):
        """PU-7 belongs to the Run, not to the chain: dropping a chain that only waits (the guard) must not forget which arrivals were already requested."""
        calls = self.requests()
        s, t_a = self.armed()
        s.run_to_request(t_a)                                                   # the key (generation, list, A, 1) is requested
        s.jump_tick()
        s.complete()
        s.o.bve_arr_idx = 2
        s.step(10)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)
        self.settle_retry(s)
        self.rearrive(s, seq=2)                                                 # a NEW arrival: a chain waits (ARMED)
        self.assertEqual(s.machine.state, M.ARMED)
        self.assertTrue(self.main.execute_retry(s.o, 0, False).accepted)        # the Retry drops that waiting chain
        self.settle_retry(s)
        self.assertEqual(s.machine.state, M.IDLE)
        self.rearrive(s, seq=1)                                                 # the SAME key as the requested one comes back
        self.assertEqual(s.machine.state, M.IDLE, "the key of the earlier request is still issued")

    def test_RT_9_a_requested_chain_is_not_dropped_by_the_guard(self):
        s, t_a = self.armed()
        s.run_to_request(t_a)
        self.assertEqual(s.machine.state, M.REQUESTED)
        s.step(3)
        self.assertEqual(s.machine.state, M.REQUESTED, "its own transaction is not a Retry or a start")
        self.assertEqual(s.o.jump_expectation.purpose, "turnback")


class B_ExecuteRetryIsUnchanged(Base):
    def test_RT_8_execute_retry_is_byte_identical_and_the_entries_are_not_multiplied(self):
        src = source("scoring_logic.py")
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_retry")
        segment = ast.get_source_segment(src, fn)
        self.assertEqual(hashlib.sha256(segment.encode("utf-8")).hexdigest().upper(), EXECUTE_RETRY_SHA256, "execute_retry changed")
        import re
        self.assertEqual(len(re.findall(r"(?<!def )\bbegin_official_jump\(self,", src)), 2, "execute_retry and turnback_request")
        self.assertEqual(len(re.findall(r"\bsend_jump_command\(", src)), 2)


if __name__ == "__main__":
    unittest.main()
