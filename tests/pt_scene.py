"""Pseudo-turnback scene rig (test code only): the REAL update_physics_and_scoring of main.Overlay driven tick by tick in BVE time (current_time = bve_time_ms / 1000, as Overlay.update_logic does),
with a PairSet published to the Overlay. The product is only called; nothing is faked except the seams of tests/sia_rig.py.

Stations (index: name, position, timing): 0 S0 0 m / 1 A 1000 m (arrival time only) / 2 B 1500 m (departure time only) / 3 C 3000 m / 4 D 5000 m (terminal). PTPAIR: A=1, B=2, ContinueScoring."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sia_rig as R  # noqa: E402
import pseudo_turnback_contract as PC  # noqa: E402
import jump_wire  # noqa: E402

T0 = 36000000
A_MARK = 1000.0
B_MARK = 1500.0
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
PTPAIR = "PTPAIR:1:%s:5:1:1-2-0" % R.SCOPE_LIST_ID


def station(name, loc, **kw):
    d = R.station(name, loc, timing=kw.pop("timing", True), terminal=kw.pop("terminal", False))
    d.update(def_time=-1, raw_arr=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def station_list():
    return [station("S0", 0.0, raw_dep=T0), station("A", A_MARK, raw_arr=T0 + 90000), station("B", B_MARK, raw_dep=T0 + 150000), station("C", 3000.0), station("D", 5000.0, terminal=True)]


def checkpoint0(sl, idx=0):
    s = sl[idx]
    return {"loc": s["location"], "time_ms": T0, "score": 0, "target_loc": s["location"], "station_name": s["name"], "stop_error": 0.0, "score_details": dict(ZERO),
            "station_index": idx, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, len(sl)), "station_location": s["location"], "role": "scoring_start"}


class Scene(object):
    def __init__(self, test, with_pairs=True, jump_available=True, drive=True):
        self.main, self.S = test.main, test.S
        previous = getattr(test, "_scene", None)
        if previous is not None:
            previous.close()
        test._scene = self
        self.rig = R.Rig(self.main)
        self.closed = False
        test.addCleanup(self.close)
        self.o = o = self.rig.o
        self.sl = station_list()
        o.station_list = self.sl
        o.toggle_menu = lambda adv: None
        o.send_jump_command = lambda cmd: None
        self.sent = []
        self.wall = 100.0
        self.n = 0
        self.rows = []
        self.drive = drive              # False: the machine is driven by hand (the machine-level contract tests of TB-A / TB-B); the product driver is switched off for this scene
        if not drive:
            original_drive = self.S.turnback_drive
            self.S.turnback_drive = lambda owner, current_time: None
            test.addCleanup(lambda: setattr(self.S, 'turnback_drive', original_drive))
        self.auto_fix = True            # the rig stands in for the scoring start button: the section is fixed (product turnback_fix_section) whenever the start/end settings it was given change
        self._fix_key = None
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        o.setting_start_idx = 0
        o.setting_end_idx = 4
        o.bve_train_length = 300.0
        o.bve_is_pass = 0
        o.bve_doordir = 1
        o.bve_margin_f = o.bve_margin_b = 5.0
        o.bve_time_ms = T0 + 30000
        o.bve_next_time = T0 + 90000
        o.is_official_jumping = False
        o.prev_is_pass = 0
        o.prev_is_timing = 1
        o.prev_doordir = 1
        o.is_official_retry = False
        o.bve_brk_notch = 8
        o.bve_calc_g = 0.0
        o.is_first_udp = False
        o.save_data = [checkpoint0(self.sl)]
        o.bve_next_loc = o.prev_next_loc = A_MARK
        o.bve_tgt_idx, o.bve_arr_idx, o.bve_arr_seq = 1, 0, 0
        o.bve_location, o.bve_speed = A_MARK - 400.0, 30.0
        o.bve_door = o.prev_door = 0
        o.has_departed, o.is_first_station, o.jump_lock = True, False, False
        o.bve_current_station_name = "A"
        o.bve_brk_notch = 0
        R.bind_identity(o, arr_idx=0, tgt_idx=1)
        self.S.reset_station_evaluation_state(o)
        if with_pairs:
            ps, why = PC.decode_ptpair(PTPAIR, len(self.sl))
            assert why is None, why
            self.S.turnback_machine_of(o).set_pairset(ps)

    def fix(self):
        fn = getattr(self.S, "turnback_fix_section", None)
        if fn is not None:
            fn(self.o)

    def close(self):
        if not self.closed:
            self.closed = True
            self.rig.close()

    # -- the tick (BVE time; the wall clock argument is deliberately unrelated) ----------------------------------------------------------------------
    def tick(self, advance_ms=16, wall_advance=None, **fields):
        o = self.o
        if self.auto_fix and self._fix_key != (o.setting_start_idx, o.setting_end_idx):
            self._fix_key = (o.setting_start_idx, o.setting_end_idx)
            self.fix()
        for k, v in fields.items():
            setattr(o, k, v)
        o.bve_time_ms += advance_ms
        self.wall += (advance_ms / 1000.0) if wall_advance is None else wall_advance
        self.n += 1
        current_time = o.bve_time_ms / 1000.0
        o.last_update_time = current_time
        self.main.update_physics_and_scoring(o, current_time, 0.016)
        self.rows.append((self.n, o.bve_time_ms, tuple(sorted((p["category"], p["text"]) for p in o.popups))))

    def step(self, n=1, advance_ms=16, **fields):
        for i in range(n):
            self.tick(advance_ms, **(fields if i == 0 else {}))

    # -- drive to the arrival at A -----------------------------------------------------------------------------------------------------------------
    def approach(self, braking="plain"):
        """The approach to A. braking: 'plain' (a constant notch: no basic braking credit) or 'stepwise' (notch 3 then 1: the basic braking succeeds)."""
        self.tick(16)
        plain = braking == "plain"
        self.step(1, bve_speed=5.0, bve_location=A_MARK - 100.0, bve_brk_notch=4 if plain else 3)
        self.step(1, bve_speed=2.0, bve_location=A_MARK - 10.0, bve_brk_notch=4 if plain else 3)
        if not plain:
            self.step(1, bve_speed=1.0, bve_location=A_MARK - 3.0, bve_brk_notch=1)
        self.stop_notch = 8 if plain else 1

    def stop_at(self, error_m):
        """The stop `error_m` short of the mark (0.0 = the 0 cm stop)."""
        self.step(3, bve_speed=0.0, bve_location=A_MARK - error_m, bve_brk_notch=getattr(self, "stop_notch", 1))

    def open_door(self):
        """The door-open edge at A: the arrival judged by evaluate_arrival at THIS tick."""
        self.step(1, bve_door=1, bve_arr_idx=1, bve_arr_seq=1)
        return self.o.bve_time_ms

    # -- the whole chain with the PRODUCT wiring (Stage TB-C): the request is made by the driver of update_physics_and_scoring, the completion by the real _note_jump_complete / _settle_jump_complete ------------------
    def arrive_a(self, late_ms=5000, start=0, end=4):
        """The arrival at A (door-open edge); returns the BVE time of the arrival. `late_ms`: how late the train is against the scheduled arrival (operating time band)."""
        o = self.o
        o.setting_start_idx, o.setting_end_idx = start, end
        o.bve_time_ms = T0 + 90000 - late_ms - 600
        o.bve_next_time = T0 + 90000
        self.approach("plain")
        self.stop_at(0.3)
        return self.open_door()

    def run_to_request(self, t_a):
        """BVE time up to arrival + 5.0 s: the driver makes the request on the tick that reaches it."""
        o = self.o
        self.tick(advance_ms=t_a + 5000 - o.bve_time_ms)
        return o.jump_expectation

    def jump_tick(self, late_target=False):
        """The telemetry of the Jump: the JUMP count, the B position and time; the A -> B NEXTLOC switch in the SAME tick (early) or one tick after the completion (late, see target_to_b)."""
        o = self.o
        exp = o.jump_expectation
        b = self.sl[exp.station_index]
        self.step(3)
        o.bve_time_ms = exp.time_ms
        fields = dict(bve_jump_count=getattr(o, "bve_jump_count", 0) + 1, bve_location=b["location"], bve_speed=0.0, bve_door=0)
        if not late_target:
            fields.update(bve_next_loc=b["location"], bve_tgt_idx=exp.station_index)
        self.step(1, **fields)

    def completion_text(self, **over):
        exp = self.o.jump_expectation
        text, why = jump_wire.format_completion_v2(over.get("command", exp.command), over.get("idx", exp.station_index), over.get("loc", exp.location), exp.time_ms, 1, tuple(over.get("scope", exp.scope)))
        assert why is None, why
        return text

    def complete(self, **over):
        o = self.o
        o._note_jump_complete(self.completion_text(**over))
        o._settle_jump_complete()

    def target_to_b(self, idx=2):
        b = self.sl[idx]
        self.step(1, bve_next_loc=b["location"], bve_tgt_idx=idx)

    def depart_b(self, order="close_then_go", c_loc=None):
        """The departure telemetry of B: the NEXTLOC switch to C while the train stands (close_then_go) or after jump_lock was released by a moving train (moving_switch)."""
        o = self.o
        b = self.sl[2]
        c_loc = self.sl[3]["location"] if c_loc is None else c_loc
        o.bve_time_ms = b["raw_dep"] - 100
        o.bve_next_time = b["raw_dep"]
        if order == "close_then_go":
            self.step(2, bve_door=0, bve_speed=0.0)
            self.step(1, advance_ms=100, bve_next_loc=c_loc, bve_tgt_idx=3, bve_speed=0.0)
            self.step(3, bve_speed=1.5, bve_location=b["location"] + 3.0)
        else:
            self.step(2, bve_door=0, bve_speed=2.0, bve_location=b["location"] + 1.0)
            self.step(1, advance_ms=100, bve_next_loc=c_loc, bve_tgt_idx=3, bve_speed=2.5, bve_location=b["location"] + 2.0)
            self.step(3, bve_speed=3.0, bve_location=b["location"] + 4.0)

    # -- observations ---------------------------------------------------------------------------------------------------------------------------------
    def popups(self, category=None):
        return [p for p in self.o.popups if category is None or p["category"] == category]

    def texts(self):
        return sorted(p["text"] for p in self.o.popups)

    @property
    def machine(self):
        return self.S.turnback_machine_of(self.o)
