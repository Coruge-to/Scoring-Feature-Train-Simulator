"""TB-G C-01 landing-order rig (test code only; used by test_pt_tbg_landing_order.py).

Reproduces the EVENT ORDER of the real C-01 run (Current, managed) at the pair-1 landing, with the real product functions only (update_physics_and_scoring, _note_jump_complete,
_settle_jump_complete, the turnback driver). Real order (C-01 logs, 2026-11-01 13:31:27.525-.543):
  1. A is an OPERATIONAL stop (closed doors): arrival judged by the operational-stop path of update_physics_and_scoring, not by a door-open edge.
  2. A + 5.0 s: the official Jump is requested once (jump-command-sent).
  3. The Jump completes: the telemetry already names B (location, speed 0, NEXTLOC / target B, arrived StationIndex B = 'stidx arr=3 tgt=3 why=t-q').
  4. jump-complete-accepted -> _settle_jump_complete ABSORBS the sender's jump counter (main.py:1187-1188: bve_jump_count = last_jump_count = completed count), so the existing
     jump rule (scoring_logic.py:1830) never sees a change: NO '[JUMP DETECT]' line exists in the desktop log for this run (the START Jump of the same run has none either).
  5. The next scoring tick (1 ms later): turnback-fail.
Orders: complete_first (the real one; JUMP count absorbed by the settlement) / detect_first (what tests/pt_scene.py jump_tick does: a scoring tick sees JUMP count + 1 BEFORE the completion)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pt_scene as P  # noqa: E402
import pseudo_turnback_machine as M  # noqa: E402

COLUMNS = ("step", "bve_ms", "score", "stop_detail", "history", "checkpoints", "latest_cp_idx", "latest_cp_origin", "arr", "tgt", "awaiting_b", "chain", "jump_txn_open",
           "scoring_on", "jump_lock", "official_jumping", "has_scored_stop", "generation", "route_pairset", "run_pairset", "abort_reason")


class Flow(object):
    """One scripted run on a pt_scene.Scene with a per-step trace and spies on the checkpoint creators / the safe stop."""

    def __init__(self, test, operational=True, advance_arr=True, order="complete_first"):
        self.S = test.S
        self.scene = s = P.Scene(test)
        self.o = s.o
        self.operational, self.advance_arr, self.order = operational, advance_arr, order
        self.rows = []
        self.events = []                 # ordered product events: (name, detail)
        self.sent = []
        self.stop_callers = []
        S = self.S
        flow = self

        def send(cmd):
            flow.sent.append(cmd)
        s.o.send_jump_command = send
        for name in ("create_save_data", "create_turnback_b_checkpoint", "turnback_stop_scoring"):
            original = getattr(S, name)
            setattr(S, name, self._wrap(name, original))
            test.addCleanup(setattr, S, name, original)
        original_diag = S.turnback_diag

        def diag(owner, event, **fields):
            flow.events.append(("diag:" + event, dict(fields)))
            return original_diag(owner, event, **fields)
        S.turnback_diag = diag
        test.addCleanup(setattr, S, "turnback_diag", original_diag)

    def _wrap(self, name, original):
        flow = self

        def wrapper(owner, *args, **kwargs):
            before = (owner.score, len(owner.save_data))
            if name == "turnback_stop_scoring":
                caller_line = sys._getframe(1).f_lineno
                flow.stop_callers.append((sys._getframe(1).f_code.co_name, caller_line))
            result = original(owner, *args, **kwargs)
            flow.events.append((name, {"score_before": before[0], "history_before": before[1], "history_after": len(owner.save_data), "result": result, "args": args}))
            return result
        return wrapper

    # ---- trace -------------------------------------------------------------------------------------------------------------------------------------
    def snap(self, step):
        o, m = self.o, self.scene.machine
        last = o.save_data[-1] if o.save_data else {}
        self.rows.append((step, o.bve_time_ms, o.score, o.score_details.get("stop"), len(o.save_data), len(o.save_data), last.get("station_index"), last.get("origin", "-"),
                          o.bve_arr_idx, o.bve_tgt_idx, bool(m.awaiting_b), m.state, o.jump_expectation is not None, bool(o.is_scoring_mode), bool(o.jump_lock),
                          bool(o.is_official_jumping), bool(o.has_scored_stop_this_station), getattr(o, "current_scenario_id", None), m.pairset is not None,
                          m.fixed is not None, getattr(o, "internal_abort_reason", "")))

    def tsv(self):
        return "\n".join(["\t".join(COLUMNS)] + ["\t".join(str(c) for c in row) for row in self.rows]) + "\n"

    # ---- the script ----------------------------------------------------------------------------------------------------------------------------------
    def to_arrival_at_a(self):
        s, o = self.scene, self.o
        if self.operational:
            o.bve_doordir = 0
            o.setting_start_idx, o.setting_end_idx = 0, 4
            o.bve_time_ms = P.T0 + 90000 - 5000 - 600
            o.bve_next_time = P.T0 + 90000
            s.approach("plain")
            s.step(1, bve_speed=0.0, bve_location=P.A_MARK - 0.3, bve_brk_notch=8, bve_arr_idx=1, bve_arr_seq=1)
            s.step(2, bve_speed=0.0)
            self.t_a = s.machine.arrival_ms
        else:
            self.t_a = s.arrive_a()
        self.snap("A-arrived")

    def to_request(self):
        self.scene.run_to_request(self.t_a)
        self.exp = self.o.jump_expectation
        self.snap("requested(+10.0s)")

    def land(self):
        """The Jump lands at B and is completed. Returns nothing; the product tick that follows is `after(n)`."""
        s, o = self.scene, self.o
        exp = o.jump_expectation
        b = s.sl[exp.station_index]
        s.step(3)
        o.bve_time_ms = exp.time_ms
        fields = dict(bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=b["location"], bve_speed=0.0, bve_door=0, bve_next_loc=b["location"], bve_tgt_idx=exp.station_index)
        if self.advance_arr:
            fields.update(bve_arr_idx=exp.station_index, bve_arr_seq=o.bve_arr_seq + 1)      # 'stidx arr=3 tgt=3 why=t-q' (C-01 13:31:27.542)
        if self.order == "detect_first":
            s.step(1, **fields)
            self.snap("telemetry-tick(JUMP+1 seen)")
            s.complete()
        else:
            for k, v in fields.items():
                setattr(o, k, v)          # the telemetry is applied; no scoring tick runs before the settlement
            self.snap("telemetry-applied(no tick)")
            s.complete()                  # _note_jump_complete + _settle_jump_complete: absorbs the sender's JUMP counter
        self.snap("settled")

    def after(self, n=3):
        for i in range(n):
            self.scene.step(1)
            self.snap("tick+%d" % (i + 1))

    def run(self, n_after=3):
        self.to_arrival_at_a()
        self.to_request()
        self.land()
        self.after(n_after)
        return self

    # ---- observations ----------------------------------------------------------------------------------------------------------------------------------
    def names(self):
        return [e[0] for e in self.events]

    def fail_reasons(self):
        return [e[1].get("reason") for e in self.events if e[0] == "diag:turnback-fail"]

    def depart_b_and_arrive_c(self, c_dist=800.0):
        """B departure (close_then_go) -> the arrival at C (operational or door edge as the flow's A). Returns the score/history after the arrival at C."""
        s, o = self.scene, self.o
        b, c = s.sl[2], s.sl[3]
        c["location"] = b["location"] + c_dist
        c["raw_dep"] = P.T0 + 400000
        o.bve_time_ms = b["raw_dep"] - 100
        o.bve_next_time = b["raw_dep"]
        s.step(2, bve_door=0, bve_speed=0.0)
        s.step(1, advance_ms=100, bve_next_loc=c["location"], bve_tgt_idx=3, bve_speed=0.0)
        s.step(3, bve_speed=1.5, bve_location=b["location"] + 3.0, bve_brk_notch=0)       # the driver releases the brake to depart (a held notch 8 while moving is a legitimate emergency-brake penalty)
        cl = c["location"]
        o.bve_is_pass = 0
        s.step(1, bve_speed=5.0, bve_location=cl - 30.0, bve_brk_notch=4)
        s.step(1, bve_speed=2.0, bve_location=cl - 10.0, bve_brk_notch=4)
        if self.operational:
            s.step(1, bve_speed=0.0, bve_location=cl - 0.3, bve_brk_notch=8, bve_arr_idx=3, bve_arr_seq=o.bve_arr_seq + 1)      # operational stop: the arrival is the stop itself (as at A)
            s.step(12, bve_speed=0.0)
        else:
            s.step(3, bve_speed=0.0, bve_location=cl - 0.3, bve_brk_notch=8)
            s.step(1, bve_door=1, bve_arr_idx=3, bve_arr_seq=o.bve_arr_seq + 1)
            s.step(10)
        self.snap("C-arrived")

    # ---- later events of the same run (added for the formal test) ---------------------------------------------------------------------------------------
    def telemetry_landing(self, exp, station_index, arr_seq_step=1):
        """The telemetry of ANY official Jump to `station_index` (the real order of this flow: `order`): the Jump count, the position, NEXTLOC / target and the arrived StationIndex of the station, then the completion."""
        s, o = self.scene, self.o
        b = s.sl[station_index]
        s.step(3)
        o.bve_time_ms = exp.time_ms
        fields = dict(bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=b["location"], bve_speed=0.0, bve_door=0, bve_next_loc=b["location"], bve_tgt_idx=station_index,
                      bve_arr_idx=station_index, bve_arr_seq=o.bve_arr_seq + arr_seq_step)
        if self.order == "detect_first":
            s.step(1, **fields)
            s.complete()
        else:
            for k, v in fields.items():
                setattr(o, k, v)
            s.complete()

    def depart_b_only(self, order="close_then_go"):
        """The first departure from B (the product's own rule releases jump_lock): the doors close, the train moves. The brake is released (a held notch while moving is a legitimate penalty)."""
        self.o.bve_brk_notch = 0
        self.scene.depart_b(order)

    def retry_to_b(self, index=1):
        """A Retry to the history place `index` (the B checkpoint) and its Jump completed in this flow's real order. Returns the RetryResult."""
        import main as _main
        o = self.o
        res = _main.execute_retry(o, index, False)
        if res.accepted:
            self.telemetry_landing(o.jump_expectation, 2)
            self.snap("retry-settled")
        return res
