"""Phase SI-R5.1 - the CHARACTERIZATION scenarios of the five 1 m reverse lookups (a helper: neither discovered nor a runner).

run_all(main, scoring_logic, sia_rig) -> {scenario name: observation}. The same scenarios run against the product of fd431b4 (the distance lookups) and against any
replacement; tests/si_r5_char_pins.json holds the two answers (head / new). Nothing here is a requirement by itself: tests/test_si_r5_characterization.py says which rows
are INVARIANT (head == new, pinned for good) and which are the KNOWN-DEFECT or the identity-missing rows that the replacement changes on purpose.
"""
import si_r5_scene as X

BRAKE = [{"end_idx": 1, "apply": "1段", "release": "1段"}, {"end_idx": -1, "apply": "2段", "release": "2段"}]
PENALTY = [{"apply": "ON1", "release": "ON1"}, {"apply": "OFF", "release": "OFF"}]


def snap(o, extra=None):
    d = {"popups": sorted((p["category"], p["text"]) for p in o.popups), "score": o.score, "finished": bool(o.is_scoring_finished),
         "checkpoints": [c.get("station_index") for c in o.save_data],
         "next_name": getattr(o, "active_next_sta_name", None), "next_timing": getattr(o, "active_next_sta_timing", None),
         "rule": [getattr(o, "active_rule_basic_apply", None), getattr(o, "active_rule_basic_release", None)],
         "scored_stop": bool(getattr(o, "has_scored_stop_this_station", False)), "scored_time": bool(getattr(o, "has_scored_time_this_station", False)),
         "latch_index": (list(o.operational_stop_latch)[0] if getattr(o, "operational_stop_latch", None) else None)}
    if extra:
        d.update(extra)
    return d


def _rules(o):
    o.brake_rules = [dict(r) for r in BRAKE]
    o.penalty_init_rules = [dict(r) for r in PENALTY]
    o.active_rule_basic_apply = o.active_rule_basic_release = "SENTINEL"


def run_all(main, S, R):
    out = {}

    def scenario(name):
        def deco(fn):
            c = X.Scene(main, S, R)
            try:
                out[name] = fn(c)
            except Exception as e:                      # a crash is an observation too
                out[name] = {"EXC": "%s: %s" % (type(e).__name__, e)}
            finally:
                c.close()
            return fn
        return deco

    A = lambda: X.abcd(R)

    # -- P05 + P01: the door rising edge of a normal stop ---------------------------------------------------------------------------------------
    @scenario("P05_normal_stop_identity_bound")
    def _(c):
        o = c.scene(A(), 1000.0); c.door_edge(); return snap(o)

    @scenario("P05_normal_stop_tgt_unavailable")
    def _(c):
        o = c.scene(A(), 1000.0, tgt=-1, arr=1); c.door_edge(); return snap(o)

    @scenario("P05_normal_stop_station_index0")
    def _(c):
        o = c.scene(A(), 0.0); o.save_data = []; c.door_edge(); return snap(o)

    @scenario("P05_normal_stop_last_index_terminal_end")
    def _(c):
        o = c.scene(A(), 3000.0); c.door_edge(); return snap(o)

    @scenario("P05_normal_stop_end_station_tgt_unavailable_not_terminal_flag")
    def _(c):
        o = c.scene(A(), 2000.0, end_idx=2, tgt=-1, arr=2); c.door_edge(); return snap(o)

    @scenario("P05_adjacent_pair_B_1000_C_1000p5_target_is_C")
    def _(c):
        o = c.scene(X.adjacent(R), 1000.5, end_idx=2, tgt=2, arr=2); c.door_edge(); return snap(o)

    @scenario("P05_same_place_B_C_1000_target_is_C")
    def _(c):
        o = c.scene(X.same_place(R), 1000.0, end_idx=2, tgt=2, arr=2); c.door_edge(); return snap(o)

    @scenario("P05_tgt_out_of_range")
    def _(c):
        o = c.scene(A(), 1000.0, tgt=99, arr=1); c.door_edge(); return snap(o)

    # -- P04 + P01 (no position): operational stop arrival --------------------------------------------------------------------------------------
    @scenario("P04_operational_stop_identity_bound")
    def _(c):
        o = c.scene(A(), 1000.0, doordir=0); c.operational_arrival(); return snap(o)

    @scenario("P04_operational_stop_tgt_unavailable")
    def _(c):
        o = c.scene(A(), 1000.0, doordir=0, tgt=-1, arr=1); c.operational_arrival(); return snap(o)

    @scenario("P04_operational_stop_end_station")
    def _(c):
        o = c.scene(A(), 2000.0, doordir=0, end_idx=2); c.operational_arrival(); return snap(o)

    @scenario("P04_operational_stop_end_station_tgt_unavailable")
    def _(c):
        o = c.scene(A(), 2000.0, doordir=0, end_idx=2, tgt=-1, arr=2); c.operational_arrival(); return snap(o)

    @scenario("P04_operational_stop_adjacent_end_station_C")
    def _(c):
        o = c.scene(X.adjacent(R), 1000.5, doordir=0, end_idx=2, tgt=2, arr=2); o.bve_next_time = o.bve_time_ms + 5000; c.operational_arrival(); return snap(o)

    @scenario("P04_transition_tick_prev_differs_from_next_pass_to_opstop")
    def _(c):
        sl = [X.sta(R, "A", 0.0, is_pass=True), X.sta(R, "B", 5.0), X.sta(R, "C", 2000.0), X.sta(R, "D", 3000.0, terminal=True)]
        o = c.scene(sl, 5.0, doordir=0, tgt=1, arr=1, prev_next=0.0, prev_tgt=0); o.prev_is_pass = 1; o.is_approaching = False; c.tick(2); return snap(o)

    @scenario("P04_hold_five_ticks_one_checkpoint")
    def _(c):
        o = c.scene(A(), 1000.0, doordir=0); o.is_approaching = True; c.tick(5); return snap(o)

    # -- P02: the departure ---------------------------------------------------------------------------------------------------------------------
    def dep(c, sl, f, t, prev_tgt, tgt0=None, **kw):
        o = c.scene(sl, f, tgt=tgt0, prev_tgt=prev_tgt); c.departure(f, t, prev_tgt, **kw); return snap(o, {"timing": [p[1] for p in snap(o)["popups"] if p[0] == "運転時分"]})

    @scenario("P02_departure_stop_station_timing")
    def _(c):
        return dep(c, A(), 1000.0, 2000.0, 1, tgt_after=2)

    @scenario("P02_departure_stop_station_prev_missing")
    def _(c):
        return dep(c, A(), 1000.0, 2000.0, -1, tgt_after=2)

    @scenario("P02_departure_pass_station_timing")
    def _(c):
        sl = [X.sta(R, "A", 0.0), X.sta(R, "B", 1000.0, is_pass=True), X.sta(R, "C", 2000.0), X.sta(R, "D", 3000.0, terminal=True)]
        return dep(c, sl, 1000.0, 2000.0, 1, tgt_after=2, prev_is_pass=1)

    @scenario("P02_departure_adjacent_pair_departing_C_1000p5")
    def _(c):
        return dep(c, X.adjacent(R, timing_b=False, timing_c=True), 1000.5, 3000.0, 2, tgt0=2, tgt_after=3)

    @scenario("P02_departure_index0_start_station")
    def _(c):
        return dep(c, A(), 0.0, 1000.0, 0, tgt_after=1)

    @scenario("P02_departure_prev_position_mismatch")
    def _(c):
        return dep(c, A(), 1000.0, 2000.0, 2, tgt_after=2)          # prev_tgt_idx names C but prev_next_loc is B

    # -- P03: HUD next station and the rule section ---------------------------------------------------------------------------------------------
    def hud(c, sl, loc, d, **kw):
        o = c.scene(sl, loc, d=d, speed=10.0, **kw); _rules(o); c.tick(); return snap(o)

    @scenario("P03_hud_next_bound")
    def _(c):
        return hud(c, A(), 2000.0, 500.0)

    @scenario("P03_hud_next_tgt_unavailable")
    def _(c):
        return hud(c, A(), 2000.0, 500.0, tgt=-1, arr=-1)

    @scenario("P03_hud_adjacent_pair_target_C")
    def _(c):
        return hud(c, X.adjacent(R), 1000.5, 300.0, tgt=2, arr=1)

    @scenario("P03_hud_nextloc_none")
    def _(c):
        o = c.scene(A(), 2000.0, d=500.0, speed=10.0); _rules(o); o.bve_next_loc = -1.0; c.tick(); return snap(o)

    @scenario("P03_hud_tgt_index0_and_last")
    def _(c):
        a = hud(c, A(), 0.0, 100.0)
        o = c.o; o.bve_next_loc = 3000.0; o.bve_tgt_idx = 3; o.bve_location = 2900.0; c.tick()
        return {"first": a["next_name"], "last": snap(o)["next_name"]}

    @scenario("P03_hud_tgt_out_of_range")
    def _(c):
        return hud(c, A(), 2000.0, 500.0, tgt=99, arr=1)

    @scenario("P03_hud_not_scoring_mode_not_evaluated")
    def _(c):
        o = c.scene(A(), 2000.0, d=500.0, speed=10.0); o.is_scoring_mode = False; o.active_next_sta_name = "unchanged"; c.tick(); return snap(o)

    return out
