"""Stage P1: the EFFECTIVE STATION STATE (effective_station_state.py) - the pure read model. No Qt, no Overlay. The fixtures are WIRE-FAITHFUL (tests/ts_eff_fixtures.py: the real TB-G route, the REAL ticks of the live S-02
stop, the sender's COMPLETED A departure / B arrival); every contract is also run on the ORIGINAL values (A departure / B arrival missing) and must give the SAME effective state.

Top-level contract (Owner): free driving = the host's official target (no Jump, no countdown, no A hold); scoring + a Run that crosses a pair = the pseudo_turnback_machine; scoring without the crossing = the
current scoring target. The effective timetable (pair A departure and pair B arrival undefined) is the ONE place where the meaning of a pair's times lives. SI-R2.3 (doors open within 100 m -> departure, else arrival)
is the only arrival / departure selector and the door is used for that choice alone."""
import ast
import dataclasses
import hashlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import effective_station_state as ess  # noqa: E402
import hud_target_contract as H  # noqa: E402
import ts_eff_fixtures as F  # noqa: E402

NORMAL, HIDDEN = ess.RemainingMode.NORMAL_TIMETABLE, ess.RemainingMode.FREE_TURNBACK_HIDDEN
ARR, DEP = ess.TimeKind.ARRIVAL, ess.TimeKind.DEPARTURE
TL = ess.TimeSource


def source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def code_of(rel):
    tree = ast.parse(source(rel))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            body[0] = ast.Pass()
    return tree


def one(values, cursor, loc, ms, door=0, speed=0.0, **kw):
    return ess.derive(F.build_inputs(F.Tick(ms, loc, speed, cursor, door), values, **kw))


class A_EffectiveTimetable(unittest.TestCase):
    def test_ET_01_pair_A_arrival_is_valid_and_departure_is_undefined_whatever_the_sender_completed(self):
        for v in F.VALUES:
            s = one(v, F.A, 200.0, 28900000)
            self.assertEqual((s.station_role, s.effective_arrival_time, s.arrival_time_source), (ess.Role.PAIR_A, 28910000, TL.SENDER_FINAL), v)
            self.assertEqual((s.effective_departure_time, s.departure_time_source), (None, TL.SUPPRESSED_FOR_TURNBACK), v)

    def test_ET_02_pair_B_arrival_is_undefined_and_departure_is_valid_whatever_the_sender_completed(self):
        for v in F.VALUES:
            s = one(v, F.B, 250.0, 28903000)
            self.assertEqual((s.station_role, s.effective_arrival_time, s.arrival_time_source), (ess.Role.PAIR_B, None, TL.SUPPRESSED_FOR_TURNBACK), v)
            self.assertEqual((s.effective_departure_time, s.departure_time_source), (29090000, TL.SENDER_FINAL), v)

    def test_ET_03_the_completed_STALIST_gives_the_same_effective_values_as_the_original(self):
        for cursor, loc in ((F.A, 200.0), (F.B, 250.0), (F.A2, 300.0), (F.B2, 350.0)):
            o, c = one("orig", cursor, loc, 28903000), one("cmpl", cursor, loc, 28903000)
            for f in ("station_role", "effective_arrival_time", "effective_departure_time", "arrival_time_source", "departure_time_source", "remaining_time_mode", "selected_time_ms", "selected_time_kind"):
                self.assertEqual(getattr(o, f), getattr(c, f), "%s at the cursor %d" % (f, cursor))
        self.assertEqual(one("cmpl", F.B, 250.0, 28903000).raw_arrival_time, 29060000, "the RAW value stays as received (the completed arrival of B)")
        self.assertIsNone(one("orig", F.B, 250.0, 28903000).raw_arrival_time)
        self.assertEqual(one("cmpl", F.A, 200.0, 28903000).raw_departure_time, 28940000)

    def test_ET_04_ordinary_stations_are_unchanged(self):
        for v in F.VALUES:
            s = one(v, F.X, 100.0, 28840000)
            self.assertEqual((s.station_role, s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode), (ess.Role.NORMAL, ARR, 28850000, NORMAL), v)
            self.assertEqual((s.arrival_time_source, s.departure_time_source), (TL.SENDER_FINAL, TL.SENDER_FINAL))
            s = one(v, F.X, 120.0, 28860000, door=1)
            self.assertEqual((s.selected_time_kind, s.selected_time_ms), (DEP, 28870000), "doors open within 100 m: the departure")
            s = one(v, F.Y, 1300.0, 29960000)
            self.assertEqual((s.station_role, s.selected_time_ms), (ess.Role.NORMAL, 29970000), v)

    def test_ET_05_the_terminal_contract_is_unchanged(self):
        for v in F.VALUES:
            s = one(v, F.Z, 1400.0, 30030000)
            self.assertEqual((s.station_role, s.selected_time_kind, s.selected_time_ms, s.effective_departure_time), (ess.Role.TERMINAL, ARR, 30040000, None), v)
            self.assertEqual(s.departure_time_source, TL.NONE, "the terminal sentinel is never a time")
            s = one(v, F.Z, 1415.0, 30030000, door=1)                      # doors open: the terminal freeze of the display target (hud_target_contract) is the value the state hands on
            self.assertEqual((s.station_role, s.selected_time_kind, s.remaining_time_mode), (ess.Role.TERMINAL, ARR, NORMAL), v)
            self.assertEqual(s.selected_time_ms, F.display_time(v, F.Tick(30030000, 1415.0, 0.0, F.Z, 1)))

    def test_ET_06_a_pair_set_that_is_not_ready_suppresses_nothing(self):
        """No pair knowledge -> no suppression (the same premise as TB-J). With the completed values the completed B arrival is shown: the documented limit; the original values show none."""
        for v, expect in (("cmpl", 29060000), ("orig", None)):
            s = one(v, F.B, 250.0, 28903000, pairset_ready=False)
            self.assertEqual((s.station_role, s.selected_time_ms, s.remaining_time_mode), (ess.Role.NORMAL, expect, NORMAL), v)
        for cursor, loc in ((F.A, 200.0), (F.B, 250.0)):
            inp = F.build_inputs(F.Tick(28903000, loc, 0.0, cursor), "cmpl")
            stale = dataclasses.replace(inp, pairset_ready=False)
            self.assertTrue(stale.pairs)
            s = ess.derive(stale)
            self.assertNotIn(TL.SUPPRESSED_FOR_TURNBACK, (s.arrival_time_source, s.departure_time_source), "the pairs are there but not trusted: cursor %d" % cursor)


class B_FreeDrivingFollowsTheOfficialTarget(unittest.TestCase):
    def test_FD_01_pair_A_arrival_shows_the_normal_arrival(self):
        for v in F.VALUES:
            s = one(v, F.A, 200.0, 28900000)
            self.assertEqual((s.effective_target_index, s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode), (F.A, ARR, 28910000, NORMAL), v)

    def test_FD_02_pair_A_departure_is_dashes_A_open_or_closed(self):
        for v in F.VALUES:
            for loc, speed in ((218.0, 0.0), (210.0, 3.0), (190.0, 0.0)):
                s = one(v, F.A, loc, 28920000, door=1, speed=speed)
                self.assertEqual((s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode, s.effective_departure_time), (DEP, None, HIDDEN, None), "%s loc=%s" % (v, loc))

    def test_FD_03_pair_B_arrival_is_dashes(self):
        for v in F.VALUES:
            for loc in (219.5764, 250.0, 268.0):
                s = one(v, F.B, loc, 28903264)
                self.assertEqual((s.effective_target_index, s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode), (F.B, ARR, None, HIDDEN), "%s loc=%s" % (v, loc))

    def test_FD_04_pair_B_departure_shows_the_departure_of_B(self):
        for v in F.VALUES:
            s = one(v, F.B, 268.0, 29080000, door=1)
            self.assertEqual((s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode, s.contract_violation), (DEP, 29090000, NORMAL, None), v)

    def test_FD_05_a_B_with_the_doors_open_far_away_is_still_the_arrival(self):
        for v in F.VALUES:
            s = one(v, F.B, 100.0, 28900000, door=1)
            self.assertEqual((s.selected_time_kind, s.remaining_time_mode), (ARR, HIDDEN), "SI-R2.3: doors open only count within 100 m of the target: " + v)

    def test_FD_06_after_B_the_next_ordinary_station_returns_to_the_normal_display(self):
        for v in F.VALUES:
            s = one(v, F.A2, 290.0, 28960000)
            self.assertEqual((s.effective_target_index, s.remaining_time_mode, s.selected_time_kind), (F.A2, NORMAL, ARR), v)
            self.assertEqual(s.selected_time_ms, 29130000, "the arrival of the next pair A")
            res = F.derive_ticks(F.pass_b_to_normal(), v)
            self.assertEqual((res[-1][1].effective_target_index, res[-1][1].remaining_time_mode), (F.A2, NORMAL), v)

    def test_FD_07_a_stop_at_A_and_a_pass_of_A_give_the_same_dashes_and_the_same_state(self):
        for v in F.VALUES:
            stopped = {s for t, s in F.derive_ticks(F.approach_and_stop("same"), v) if t.cursor == F.B}
            for adv in F.PASS_ADVANCE:
                passed = {s for t, s in F.derive_ticks(F.pass_a_no_stop(adv), v) if t.cursor == F.B}
                self.assertEqual(len(stopped), 1, "the state of a B arrival target does not depend on the vehicle: %s" % v)
                self.assertEqual(stopped, passed, "A stopped / A passed: the same effective state (%s, %s)" % (v, adv))
            self.assertEqual(next(iter(stopped)).remaining_time_mode, HIDDEN)

    def test_FD_08_the_state_has_no_arrival_and_no_stop_judgement(self):
        names = {f.name for f in dataclasses.fields(ess.EffectiveStationState)}
        self.assertFalse({n for n in names if any(w in n for w in ("arrived", "arrival_observed", "stop_", "speed", "range", "snapshot", "latch", "memo"))}, sorted(names))
        for v in F.VALUES:
            for order in F.ORDERS:
                for t, s in F.derive_ticks(F.approach_and_stop(order), v):
                    self.assertEqual(s.remaining_time_mode, HIDDEN if t.cursor == F.B else NORMAL, "%s %s: the display follows the official target of THIS tick" % (v, order))

    def test_FD_09_free_driving_never_has_a_jump_countdown_a_hold_or_a_turnback_state(self):
        for v in F.VALUES:
            for name, ticks in (("O0", F.approach_and_stop("stays")), ("O1", F.approach_and_stop("same")), ("O2", F.approach_and_stop("lead1")), ("lag1", F.approach_and_stop("lag1")),
                                ("pass", F.pass_a_no_stop("marker")), ("restart", F.restart_after_arrival())):
                for t, s in F.derive_ticks(ticks, v):
                    self.assertIn(s.remaining_time_mode, (NORMAL, HIDDEN), (v, name))
                    self.assertEqual((s.countdown_ms, s.jump_deadline, s.turnback_state, s.scoring_target_index), (None, None, ess.TurnbackState.NONE, None), (v, name))
                    self.assertEqual(s.effective_target_index, s.raw_target_index, "no TScoring hold of A: the effective target IS the official target")

    def test_FD_10_the_lag_of_the_official_target_is_followed_not_compensated(self):
        """One tick where the official target is still A while the train stands: the display follows A (the arrival of A); the next tick follows B (dashes). No one-tick wait, no memory of the previous target."""
        for v in F.VALUES:
            res = F.derive_ticks(F.approach_and_stop("lag1"), v)
            z = F.real_profile()[1]
            self.assertEqual([s.remaining_time_mode for t, s in res[z - 1:z + 2]], [NORMAL, NORMAL, HIDDEN], v)
            self.assertEqual(res[z][1].selected_time_ms, 28910000, "still the official target A in this tick: the arrival of A")
            self.assertEqual(res[z][1], one(v, F.A, 219.5764, F.real_profile()[0][z][0]), "the state of a tick depends on the inputs of that tick only")

    def test_FD_11_no_official_target_means_no_effective_target(self):
        for v in F.VALUES:
            s = ess.derive(F.build_inputs(F.Tick(28903264, 219.5, 0.0, None), v))
            self.assertEqual((s.raw_target_index, s.effective_target_index, s.station_role, s.remaining_time_mode, s.selected_time_ms), (None, None, None, NORMAL, None))


class C_ScoringRunThatCrossesThePair(unittest.TestCase):
    def modes(self, v):
        out = {}
        for label, tick, view in F.tbj_chain():
            out[label] = ess.derive(F.build_inputs(tick, v, scoring=view))
        return out

    def test_SC_01_the_machine_has_priority_and_the_modes_are_the_TBJ_ones(self):
        expect = {"first_0s": (ess.RemainingMode.TURNBACK_INITIAL_COUNTDOWN, 10000, ess.TurnbackState.WAITING), "first_3s": (ess.RemainingMode.TURNBACK_INITIAL_COUNTDOWN, 7000, ess.TurnbackState.WAITING),
                  "cancelled_3.2s": (ess.RemainingMode.TURNBACK_CANCELLED, None, ess.TurnbackState.CANCELLED),
                  "restop1_at_6s": (ess.RemainingMode.TURNBACK_RESTOP_COUNTDOWN, 5000, ess.TurnbackState.WAITING), "restop1_at_7s": (ess.RemainingMode.TURNBACK_RESTOP_COUNTDOWN, 4000, ess.TurnbackState.WAITING),
                  "recancelled_8s": (ess.RemainingMode.TURNBACK_CANCELLED, None, ess.TurnbackState.CANCELLED),
                  "restop2_at_9s": (ess.RemainingMode.TURNBACK_RESTOP_COUNTDOWN, 5000, ess.TurnbackState.WAITING),
                  "requested_14s": (ess.RemainingMode.TURNBACK_REQUESTED, 0, ess.TurnbackState.REQUESTED), "awaiting_b_14.1s": (ess.RemainingMode.TURNBACK_REQUESTED, 0, ess.TurnbackState.AWAITING_B)}
        for v in F.VALUES:
            res = self.modes(v)
            for label, (mode, countdown, ts) in expect.items():
                s = res[label]
                self.assertEqual((s.remaining_time_mode, s.countdown_ms, s.turnback_state), (mode, countdown, ts), "%s %s" % (v, label))
                self.assertEqual(s.effective_target_index, F.A, "%s %s: the effective target is A until B is established" % (v, label))
                self.assertIsNone(s.selected_time_ms)
            self.assertEqual({l for l, s in res.items() if s.jump_deadline is not None}, {"first_0s", "first_3s", "restop1_at_6s", "restop1_at_7s", "restop2_at_9s"})

    def test_SC_02_the_raw_target_may_be_B_while_the_effective_target_is_A(self):
        for v in F.VALUES:
            s = self.modes(v)["cancelled_3.2s"]
            self.assertEqual((s.raw_target_index, s.scoring_target_index, s.effective_target_index, s.station_role), (F.B, F.B, F.A, ess.Role.PAIR_A))

    def test_SC_03_after_the_jump_and_the_landing_the_departure_of_B_is_shown_not_dashes(self):
        for v in F.VALUES:
            s = self.modes(v)["b_established_14.5s"]
            self.assertEqual((s.effective_target_index, s.station_role, s.turnback_state, s.remaining_time_mode, s.selected_time_kind), (F.B, ess.Role.PAIR_B, ess.TurnbackState.NONE, NORMAL, DEP), v)
            self.assertEqual((s.selected_time_ms, s.contract_violation), (29090000, None), "the departure of B (author value), never B's completed arrival 29060000")
            self.assertIsNone(s.effective_arrival_time)

    def test_SC_04_a_pair_B_without_a_departure_is_a_contract_violation_never_an_ordinary_dashes(self):
        label, tick, view = [x for x in F.tbj_chain() if x[0] == "b_established_14.5s"][0]
        inp = F.build_inputs(tick, "cmpl", scoring=view)
        broken = dataclasses.replace(inp, stations=tuple(dataclasses.replace(r, sender_departure_ms=-1) if r.index == F.B else r for r in inp.stations))
        s = ess.derive(broken)
        self.assertEqual((s.contract_violation, s.selected_time_ms), (ess.CONTRACT_PAIR_B_DEPARTURE, None))
        self.assertEqual(ess.pair_time_violation(F.PAIRS, broken.stations), ess.CONTRACT_PAIR_B_DEPARTURE)
        self.assertIsNone(ess.pair_time_violation(F.PAIRS, inp.stations))
        free = dataclasses.replace(F.build_inputs(F.Tick(29085000, 268.0, 0.0, F.B, 1), "cmpl"), stations=broken.stations)
        self.assertEqual(ess.derive(free).contract_violation, ess.CONTRACT_PAIR_B_DEPARTURE, "free driving flags it too (B departure selected, departure missing)")

    def test_SC_05_pair_A_arrival_is_required_too(self):
        stations = tuple(dataclasses.replace(r, sender_arrival_ms=-1) if r.index == F.A else r for r in F.rows("cmpl"))
        self.assertEqual(ess.pair_time_violation(F.PAIRS, stations), ess.CONTRACT_PAIR_A_ARRIVAL)
        self.assertIsNone(ess.pair_time_violation((), stations), "no pair, nothing required")

    def test_SC_06_the_free_driving_mode_is_never_preferred_while_scoring(self):
        """A scoring Run with the official target on a pair B (free driving would show dashes) keeps the scoring display."""
        for v in F.VALUES:
            view = ess.ScoringView(True, False, frozenset(), F.X, None)
            inp = F.build_inputs(F.Tick(28903264, 219.57, 0.0, F.B), v, scoring=view)
            s = ess.derive(dataclasses.replace(inp, display_time_ms=28850000))
            self.assertEqual((s.remaining_time_mode, s.selected_time_kind, s.selected_time_ms, s.effective_target_index, s.raw_target_index), (NORMAL, ess.TimeKind.SCORING_NEXTTIME, 28850000, F.X, F.B), v)

    def test_SC_07_a_scoring_Run_that_does_not_cross_a_pair_keeps_the_current_scoring_target_contract(self):
        for v in F.VALUES:
            for target in (F.X, F.A, F.B, F.Z):
                view = ess.ScoringView(True, False, frozenset(), target, None)
                inp = dataclasses.replace(F.build_inputs(F.Tick(28903264, 100.0, 5.0, F.B), v, scoring=view), display_time_ms=12345678)
                s = ess.derive(inp)
                self.assertEqual((s.effective_target_index, s.selected_time_kind, s.selected_time_ms, s.remaining_time_mode, s.turnback_state), (target, ess.TimeKind.SCORING_NEXTTIME, 12345678, NORMAL, ess.TurnbackState.NONE), (v, target))

    def test_SC_08_a_crossing_Run_shows_the_scoring_display_for_an_ordinary_target_between_the_pairs(self):
        for v in F.VALUES:
            view = ess.ScoringView(True, True, frozenset({F.B}), F.X, ess.MachineView("idle", 0, None, False, False, None))
            s = ess.derive(dataclasses.replace(F.build_inputs(F.Tick(28903264, 100.0, 5.0, F.X), v, scoring=view), display_time_ms=28850000))
            self.assertEqual((s.selected_time_kind, s.selected_time_ms, s.effective_target_index), (ess.TimeKind.SCORING_NEXTTIME, 28850000, F.X), v)

    def test_SC_09_the_state_after_the_chain_ended_is_the_scoring_target_again(self):
        """Retry / abort / F5: the machine is idle and the chain is not alive: nothing of the chain is left in the state."""
        for v in F.VALUES:
            view = ess.ScoringView(True, True, frozenset({F.B}), F.A, ess.MachineView("idle", 0, None, False, False, None))
            s = ess.derive(dataclasses.replace(F.build_inputs(F.Tick(28920000, 219.57, 0.0, F.B), v, scoring=view), display_time_ms=28910000))
            self.assertEqual((s.effective_target_index, s.turnback_state, s.jump_deadline, s.countdown_ms, s.remaining_time_mode), (F.A, ess.TurnbackState.NONE, None, None, NORMAL), v)


class D_PureAndStructure(unittest.TestCase):
    def test_PS_01_derive_is_pure_and_the_state_is_frozen(self):
        inp = F.build_inputs(F.Tick(28903264, 219.57, 0.0, F.B), "cmpl")
        before = repr(inp)
        s1, s2 = ess.derive(inp), ess.derive(inp)
        self.assertEqual((s1, repr(inp)), (s2, before))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            s1.remaining_time_mode = NORMAL
        res = F.derive_ticks(F.approach_and_stop("same"), "cmpl")
        for (t, s), (t2, s2) in zip(res, reversed(list(reversed(res)))):
            self.assertEqual(s, ess.derive(F.build_inputs(t, "cmpl")), "a state depends on its own inputs only")

    def test_PS_02_the_module_imports_nothing_of_the_application_and_names_no_judgement(self):
        tree = code_of("effective_station_state.py")
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(imported <= {"dataclasses", "enum", "typing"}, imported)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {a.arg for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in n.args}
        for word in ("door", "speed", "location", "margin", "latch", "memo", "snapshot", "range", "StopObserved", "ArrivalObserved", "arrival_observed", "bve_door", "bve_speed", "is_scoring_mode", "turnback_machine"):
            self.assertFalse({n for n in names if word.lower() in n.lower()}, word)
        assigned_self = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)}
        self.assertEqual(assigned_self, set(), "no attribute is ever stored: no state")
        for node in tree.body:
            if isinstance(node, ast.Assign):
                self.assertIsInstance(node.value, (ast.Constant, ast.Tuple), "a module-level value is a constant, never a mutable store: " + ast.unparse(node)[:60])
        stmts = [n for n in ast.walk(tree) if isinstance(n, (ast.Global, ast.Nonlocal))]
        self.assertEqual(stmts, [], "no global / nonlocal: nothing outlives a call")
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            calls = {c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
            self.assertFalse(calls & {"append", "extend", "update", "add", "pop", "setdefault", "__setattr__"}, "%s mutates something: %s" % (fn.name, calls))
            self.assertNotIn("__setattr__", ast.unparse(fn))

    def test_PS_03_the_door_is_used_for_the_SI_R23_selection_and_nothing_else(self):
        main_tree = ast.parse(source("main.py"))
        overlay = next(n for n in main_tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        method = next(n for n in overlay.body if isinstance(n, ast.FunctionDef) and n.name == "_effective_inputs")
        doors = [n for n in ast.walk(method) if isinstance(n, ast.Attribute) and n.attr == "bve_door"]
        self.assertEqual(len(doors), 1)
        selectors = [c for c in ast.walk(method) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "select_time_kind"]
        self.assertEqual(len(selectors), 1)
        self.assertIn(doors[0], list(ast.walk(selectors[0])), "bve_door is read only as an argument of the SI-R2.3 selector")
        for rel in ("effective_station_state.py", "route_pairset.py"):
            self.assertNotIn("bve_door", source(rel), rel)

    def test_PS_04_the_SI_R23_selector_is_the_one_rule(self):
        S = H.select_time_kind
        self.assertEqual(S(0, 1000.0, 1000.0), H.KIND_ARRIVAL)
        self.assertEqual(S(1, 1000.0, 1000.0), H.KIND_DEPARTURE)
        self.assertEqual(S(1, 1000.0, 901.0), H.KIND_DEPARTURE)
        self.assertEqual(S(1, 1000.0, 900.0), H.KIND_ARRIVAL, "within NEAR_M means < 100 m")
        self.assertEqual(S(1, 1000.0, 1099.9), H.KIND_DEPARTURE)
        self.assertEqual(S(2, 1000.0, 1000.0), H.KIND_DEPARTURE, "any door state but 0")
        tree = code_of("hud_target_contract.py")
        official = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "official_time")
        calls = [c for c in ast.walk(official) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "select_time_kind"]
        self.assertEqual(len(calls), 1, "official_time uses the selector instead of its own door expression")
        self.assertNotIn("NEAR_M", ast.unparse(official))

    def test_PS_05_the_old_free_driving_latch_is_gone(self):
        for rel in ("main.py", "hud_ui.py", "scoring_logic.py", "pseudo_turnback_machine.py", "hud_target_contract.py", "managed_input.py", "effective_station_state.py"):
            text = source(rel)
            for word in ("_free_turnback_a_latch", "free_turnback_a_time_suppressed", "_free_turnback_a_latch_update", "_free_turnback_a_latch_sync"):
                self.assertNotIn(word, text, "%s: %s" % (rel, word))

    def test_PS_06_the_scoring_logic_and_the_machine_are_untouched_by_this_stage(self):
        def blob(rel):
            with open(os.path.join(ROOT, rel), "rb") as fh:
                data = fh.read().replace(b"\r\n", b"\n")
            return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        # INITIAL-DEFAULTS Stage F2 (on purpose; Owner 2026-11-11): the label of the safety intervention row in the Desktop log breakdown is 保安装置介入 (was ATS信号無視); the pin was 93130b87...
        self.assertEqual(blob("scoring_logic.py"), "7bbebe8ff10c5ca618f33cb62f11d01ab13ddbc3")       # INITIAL-DEFAULTS Commit 3 (on purpose; INITIAL-DEFAULTS Commit 3): the scoring settings are read through scoring_settings (the running snapshot); 2026-11-08 (the pin moved, an intended change: formal LastStop BveG, CalcG / sway retired; was 1187e257...)
        self.assertEqual(blob("pseudo_turnback_machine.py"), PINNED_MACHINE_BLOB)

    def test_PS_07_hud_ui_reads_the_effective_state_for_the_time_row(self):
        text = source("hud_ui.py")
        self.assertIn("self.effective_station_state", text)
        self.assertNotIn("turnback_remaining_view", text)
        self.assertNotIn("hud_target_next_time", text)

    def test_PS_08_main_wires_the_state_without_storing_it(self):
        main_tree = ast.parse(source("main.py"))
        overlay = next(n for n in main_tree.body if isinstance(n, ast.ClassDef) and n.name == "Overlay")
        methods = {n.name: n for n in overlay.body if isinstance(n, ast.FunctionDef)}
        for name in ("_effective_inputs", "_effective_rows", "_pair_time_check", "effective_station_state", "turnback_remaining_view"):
            stores = {n.attr for n in ast.walk(methods[name]) if isinstance(n, ast.Attribute) and isinstance(n.ctx, (ast.Store, ast.Del)) and isinstance(n.value, ast.Name) and n.value.id == "self"}
            self.assertEqual(stores, set(), name + " writes no attribute")
        self.assertEqual(source("main.py").count("ess.derive("), 1, "one place derives the state")


PINNED_MACHINE_BLOB = "9e505e1f310100d6cd3a3a93d201c62de357930d"


if __name__ == "__main__":
    unittest.main()
