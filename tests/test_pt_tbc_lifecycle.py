"""Stage TB-C, slice C1 / CH-11: nothing of the pseudo-turnback chain, its transaction, the fixed section or the B records outlives its scoring session. Lifecycle events: scenario reload, a new scoring start,
an abort, a finished scoring, soft-off; from three starting states (ARMED / REQUESTED with an open transaction / AWAITING_B). The display update never raises with the scoring off."""
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
    _TMP["dir"] = tempfile.TemporaryDirectory(prefix="ts-ch-11-")
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


class FakeClient(object):
    def __init__(self):
        self.cancelled = []

    def cancel(self, reason):
        self.cancelled.append(reason)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["ch-11"])
        import main
        import scoring_logic
        import jump_transaction
        import jump_wire
        import station_identity
        import managed_input
        import pt_scene
        cls.main, cls.S, cls.JT, cls.JW, cls.SI, cls.MI, cls.P = main, scoring_logic, jump_transaction, jump_wire, station_identity, managed_input, pt_scene

    def build(self, kind):
        """The chain in one of three states, built with the PRODUCT wiring: ARMED (after the A arrival), REQUESTED (the Jump is open), AWAITING_B (the completion proved the Jump, the B target has not arrived)."""
        s = self.P.Scene(self)
        o = s.o
        s.sl[2]["location"] = self.P.A_MARK + 500.0
        t_a = s.arrive_a()
        if kind != "ARMED":
            s.run_to_request(t_a)
        if kind == "AWAITING_B":
            s.jump_tick(late_target=True)
            s.complete()
            s.tick(16)
            assert s.machine.awaiting_b and o.is_scoring_mode
        o.jump_client = FakeClient()
        return s

    def observe(self, s):
        o = s.o
        m = o.__dict__.get("turnback_machine")
        return "machine=%s awaiting_b=%s pairset=%s | mark=%s exp=%s pending=%s jumping=%s scoring=%s finished=%s hist=%s client_cancels=%s" % (
            "dropped" if m is None else m.state, None if m is None else m.awaiting_b, None if m is None else (m.pairset is not None),
            getattr(o, "has_scored_time_this_station", None), o.jump_expectation is not None, o.retry_pending is not None, o.is_official_jumping,
            o.is_scoring_mode, o.is_scoring_finished, len(o.save_data), o.jump_client.cancelled if o.jump_client is not None else None)

    def fire(self, s, event):
        o = s.o
        if event == "generation(reset_generation_state)":
            o.reset_generation_state()
        elif event == "scenario-reload(SCENARIO_ID changes)":
            o.apply_telemetry_text("SCENARIO_ID:%d" % (o.current_scenario_id + 1))
        elif event == "new-scoring-start":
            o.is_scoring_mode = False
            o.menu_state, o.menu_cursor = 10, 1
            o.scoring_start_gate = None
            o.was_advancing_before_menu = False
            self.P.R.bind_identity(o, arr_idx=-1, tgt_idx=0)
            o.bve_location, o.bve_speed = 0.0, 0.0
            o.handle_menu_enter(False)
        elif event == "scoring-finished":
            o.is_scoring_finished = True
        elif event == "scoring-aborted(is_scoring_mode off)":
            o.is_scoring_mode = False
        elif event == "soft-off(discard_scoring_session)":
            self.MI.discard_scoring_session(o)
        elif event == "shutdown(_jump_transaction_finish)":
            o._jump_transaction_finish("shutdown")


class Lifecycle(Base):
    def check(self, kind, event):
        s = self.build(kind)
        self.fire(s, event)
        if event != "new-scoring-start":
            s.step(1)                                    # one scoring tick: must not raise, and is where a lazy discard may happen
        o = s.o
        m = o.__dict__.get("turnback_machine")
        if m is not None:
            self.assertEqual(m.state in ("idle", "discarded"), True, "%s/%s: the chain survived: %s" % (kind, event, m.state))
            self.assertFalse(m.awaiting_b, "%s/%s: awaiting_b survived" % (kind, event))
        if event == "new-scoring-start":
            self.assertTrue(o.jump_expectation is None or o.jump_expectation.purpose == "start", "%s/%s: a turnback transaction survived" % (kind, event))
        elif not event.startswith(("scoring-aborted", "scoring-finished")):
            self.assertIsNone(o.jump_expectation, "%s/%s: the transaction survived" % (kind, event))
        if kind == "AWAITING_B" and event.startswith(("soft-off", "new-scoring-start")):         # (after a reload / an abort the scoring is off: the mark means nothing and the next start resets it)
            self.assertFalse(getattr(o, "has_scored_time_this_station", False), "%s/%s: the B mark survived" % (kind, event))

def _add(kind, event):
    name = "test_L_%s_%s" % (kind, event.split("(")[0].replace("-", "_"))
    setattr(Lifecycle, name, lambda self, k=kind, e=event: self.check(k, e))


for _k in ("ARMED", "REQUESTED", "AWAITING_B"):
    for _e in ("scenario-reload(SCENARIO_ID changes)", "new-scoring-start", "scoring-aborted(is_scoring_mode off)", "soft-off(discard_scoring_session)", "scoring-finished"):
        _add(_k, _e)


def _display_update_with_the_scoring_off(self):
    """The guidance window of an ARMED chain must not raise when the scoring is off (measured at 73c2125: IndexError on popups[-1], add_score_popup refuses outside a scoring)."""
    s = self.build("ARMED")
    s.o.is_scoring_mode = False
    s.o.popups.clear()
    s.o.bve_time_ms = s.machine.arrival_ms + 100
    self.S.turnback_display_update(s.o, s.o.bve_time_ms / 1000.0)


Lifecycle.test_L_display_update_with_the_scoring_off_never_raises = _display_update_with_the_scoring_off

if __name__ == "__main__":
    unittest.main()
