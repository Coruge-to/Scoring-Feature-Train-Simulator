"""Phase SI-R5.1 - the shared scene of the SI-R5 RED / Characterization / Guard files (a helper: neither discovered nor a runner).

The scenes follow tests/sia_rig.py (the REAL Overlay offscreen, every outside effect a recorder). Nothing here reads the Night A worktree.
`bind_identity` of the rig is the TEST DOUBLE of a READY sender (it names the station by a position): it is a test seam, not a product path (see global-close-guard-contract.md).

THE CONTRACT THE SCENES ARE WRITTEN AGAINST (SI-R5.1, Owner decision of 2026-10-29):
    P01 evaluate_arrival                       station identity = bve_tgt_idx
    P03 HUD next station / rule section        station identity = bve_tgt_idx
    P04 operational-stop pre-arrival timing    station identity = bve_tgt_idx
    P05 normal-stop door-open arrival          station identity = bve_tgt_idx
    P02 evaluate_departure                     station identity = prev_tgt_idx (NEW state, -1 = none), valid only when it is inside the list AND the position of that
                                               station agrees with prev_next_loc within 0.01 m; otherwise the departure station is -1 = no time score
    a missing identity is never replaced (no tgt-1, no nearest, no 1 m lookup, no older index, no station 0); the identity-dependent step of THAT tick is skipped, and
    the skip is reported as the event `stidx-missing-index` classified expected_unavailable | contractual_none | unexpected_missing | position_mismatch
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

T0 = 36000000
EVENT = "stidx-missing-index"
EVENT_END = "stidx-missing-end"
CLASSES = ("expected_unavailable", "contractual_none", "unexpected_missing", "position_mismatch")
REQUIRED_FIELDS = ("site", "cls", "why", "t", "scn", "list", "scoring", "session", "tgt", "prev_tgt", "nextloc", "prev_nextloc", "avail", "action")


def sta(R, name, loc, **kw):
    d = R.station(name, loc, terminal=kw.pop("terminal", False), is_pass=kw.pop("is_pass", False))
    d.update(def_time=-1, raw_dep=-1, stop_time=15000)
    d.update(kw)
    return d


def abcd(R):
    return [sta(R, "A", 0.0), sta(R, "B", 1000.0), sta(R, "C", 2000.0), sta(R, "D", 3000.0, terminal=True)]


def adjacent(R, timing_b=True, timing_c=True):
    """B@1000 and C@1000.5 are 0.5 m apart: the 1 m lookup of the lowest index names B for the target C."""
    return [sta(R, "A", 0.0), sta(R, "B", 1000.0, is_timing=timing_b), sta(R, "C", 1000.5, is_timing=timing_c), sta(R, "D", 3000.0, terminal=True)]


def same_place(R):
    return [sta(R, "A", 0.0), sta(R, "B", 1000.0), sta(R, "C", 1000.0), sta(R, "D", 3000.0, terminal=True)]


# The declared nominal table of the abcd()-shaped lists (a literal of the FIXTURE: not a search of any station list). A scene on any other list names its target index itself.
FIXTURE_TARGET = {0.0: 0, 1000.0: 1, 2000.0: 2, 3000.0: 3}


class Scene(object):
    """One Overlay of `main` with a scoring scene; `events` records the diagnostic events (what the managed controller's sink would receive)."""

    def __init__(self, main, S, R):
        self.main, self.S, self.R = main, S, R
        self.rig = R.Rig(main)
        self.o = self.rig.o
        self.t = 100.0
        self.events = []
        self.o.input_event_sink = lambda event, **fields: self.events.append((event, dict(fields)))

    def close(self):
        self.rig.close()

    def scene(self, stations, next_loc, d=0.0, doordir=1, is_pass=0, speed=0.0, end_idx=3, tgt=None, arr=None, prev_tgt=None, prev_next=None):
        o, R = self.o, self.R
        o.is_scoring_mode = True
        o.is_scoring_finished = False
        import station_identity
        o.station_list = station_identity.StationList(stations, R.SCOPE_LIST_ID)         # the adopted list carries its identity, as in the product
        o.setting_end_idx = end_idx
        o.save_data = [{"loc": 0.0, "time_ms": T0, "score": 0, "target_loc": 0.0, "station_name": "A", "stop_error": 0.0, "score_details": {},
                        "station_index": 0, "scope": (R.SCOPE_SID, R.SCOPE_LIST_ID, len(stations)), "station_location": 0.0, "role": "scoring_start"}]
        o.bve_next_loc = next_loc
        o.prev_next_loc = next_loc if prev_next is None else prev_next
        o.bve_location = next_loc - d
        o.bve_speed = speed
        o.bve_is_pass = is_pass
        o.bve_doordir = doordir
        o.bve_door = o.prev_door = 0
        o.bve_margin_b = o.bve_margin_f = 5.0
        o.has_departed = True
        o.is_first_station = False
        o.is_first_udp = False
        o.bve_time_ms = T0 + 60000
        o.bve_current_station_name = "B"
        o.jump_lock = False
        o.is_official_jumping = False
        self.bind(o, tgt, arr)
        o.prev_tgt_idx = o.bve_tgt_idx if prev_tgt is None else prev_tgt         # (an attribute the product does not have yet: harmless there)
        return o

    def bind(self, o, tgt, arr):
        """What a READY sender publishes, written as the explicit indexes the scene is given (the roles allowed here: binding and keeping an index the caller names; NO search by a location,
        NO scan of the station list, NO nearest / 1 m / lowest-index choice). A scene on an abcd()-shaped list may omit the target: the FIXTURE_TARGET literal then names it."""
        if tgt is None:
            tgt = FIXTURE_TARGET[o.bve_next_loc]               # KeyError = this scene must name its target index
        if arr is None:
            arr = tgt
        o.current_scenario_id = self.R.SCOPE_SID
        o.bve_list_id = self.R.SCOPE_LIST_ID
        o.bve_arr_idx = arr
        o.bve_tgt_idx = tgt

    def tick(self, n=1):
        for _ in range(n):
            self.t += 0.016
            self.S.update_physics_and_scoring(self.o, self.t, 0.016)

    def door_edge(self):
        self.tick()
        self.o.bve_door = 1
        self.tick()

    def operational_arrival(self, ticks=2):
        self.o.is_approaching = True
        self.tick(ticks)

    def departure(self, from_loc, to_loc, prev_tgt, tgt_after=None, prev_is_pass=0, prev_doordir=1):
        """The target switches FORWARD from `from_loc` to `to_loc` on this tick (the vehicle just left): evaluate_departure runs on it."""
        o = self.o
        o.prev_is_pass = prev_is_pass
        o.prev_doordir = prev_doordir
        o.bve_is_timing = 1
        o.has_scored_stop_this_station = True
        o.prev_diff_s = 0
        o.bve_next_loc = to_loc
        o.bve_speed = 5.0
        o.bve_location = from_loc + 3.0
        o.prev_tgt_idx = prev_tgt
        if tgt_after is not None:
            o.bve_tgt_idx = tgt_after
        self.tick()

    # -- observations ---------------------------------------------------------------------------------------------------------------------------
    def popups(self, category=None):
        return sorted(p["text"] for p in self.o.popups if category is None or p["category"] == category)

    def checkpoints(self):
        return [c.get("station_index") for c in self.o.save_data]

    def missing(self, site=None):
        return [f for (e, f) in self.events if e == EVENT and (site is None or f.get("site") == site)]

    def missing_end(self, site=None):
        return [f for (e, f) in self.events if e == EVENT_END and (site is None or f.get("site") == site)]


def decision_unavailable(o, reason):
    """The sender's indexes can not be used (the decision the sync publishes: every published index is -1)."""
    import station_identity
    o._station_identity_apply(station_identity.unavailable(reason))


def decision_target_none(o):
    """A READY identity whose TARGET index is -1 (the sender says 'no target'): usable, arrival index kept, target invalid (reason index-negative)."""
    import station_identity
    observed = {"ready": True, "scenario_id": o.current_scenario_id, "list_id": o.station_list.list_id, "count": len(o.station_list), "tgt_idx": -1, "arr_idx": o.bve_arr_idx, "arr_seq": 1}
    o._station_identity_apply(station_identity.decide(observed, o.current_scenario_id, o.station_list, o.bve_next_loc))
