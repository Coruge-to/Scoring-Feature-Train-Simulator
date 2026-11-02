"""The pseudo-turnback chain state machine. PURE (no Qt, no Win32, no socket, no file, no clock, no global state): the host feeds events with the
BVE time and acts on the returned actions. It never writes the Overlay and never sends a Jump itself.

What it decides (PTS-0 Pair contract §11, S22A, Owner OD-PR-1 beta / OD-PR-3 / OD-PR-4, Owner display contract 2026-10-31):
  * the use conditions PU-1..PU-7 are evaluated at EVERY arrival; no 'done'/'not applicable' flag is kept for a pair (the issued key is the only memory: PU-7);
  * A: the arrival scoring of the host comes first; then ONE A operating-time score (only for a pair A that is a timing station); NO A checkpoint, ever;
  * the FIRST Jump is requested ONCE, at the BVE time of the arrival (the tick that ran evaluate_arrival) + 10.0 s (Stage TB-H 5b; after a re-stop: the re-stop + 5.0 s, unchanged), never waiting for or looking at a door, never reading a signal flag;
  * the 10.0 s of the first window are shown the same way with or without an arrival result popup (basic braking achieved / 0 cm stop): 0-5 s the arrival result popups (their normal 5.0 s) or nothing, 5-10 s the guidance.
    The request time does NOT depend on the display;
  * a Jump that cannot be sent (the sender does not announce the Jump group) is never requested: the chain ends in FAILED and the host aborts the scoring (fail-closed, reason JUMP_UNAVAILABLE_REASON);
  * B: after the official Jump completed, and the host reported that B is established (StationIndex, target, start state), ONE B checkpoint for a ContinueScoring pair, none for a final pair;
  * a final pair (CompleteAfterJump): the finish action is returned from the completion event itself, before anything of B is scored (order protection I-12), and NO checkpoint.
Door state and signal flags are not parameters of any function here, on purpose."""

from typing import NamedTuple

PURPOSE_TURNBACK = "turnback"        # the purpose of the Jump (distinct from retry / start); the formal home is jump_transaction.JUMP_TURNBACK (Stage TB-C)

REQUEST_AFTER_MS = 5000              # the Jump request after a RE-STOP: BVE time of the re-stop + 5.0 s (UNCHANGED by Stage TB-H 5b; the FIRST window is FIRST_REQUEST_AFTER_MS)
FIRST_REQUEST_AFTER_MS = 2 * REQUEST_AFTER_MS      # Stage TB-H 5b: the Jump request of the FIRST window: BVE time of the arrival + 10.0 s (5.0 s of the arrival result popups or nothing + 5.0 s of guidance), with or without an arrival result popup
FIRST_GUIDE_FROM_MS = REQUEST_AFTER_MS           # Stage TB-H 5b: the guidance of the first window is shown from the arrival + 5.0 s to the request (0-5 s: the arrival result popups, or nothing)

JUMP_UNAVAILABLE_REASON = "pseudo-turnback-jump-unavailable"
SELF_DRIVE_B_REASON = "pseudo-turnback-self-drive-b"      # Stage TB-H (A re-stop wait): the train was driven from A to B by itself; the planned Jump to B must never be sent
CANCEL_WARNING_MS = 5000                                   # the red cancellation warning is shown for 5.0 s (derived display state only)
B_STATE_FAILED_REASON = "pseudo-turnback-b-state-invariant-failed"
B_WATCH_LIMIT_MS = 1000              # OD-TB-28: the positive BVE-time advance, counted from the first B-side telemetry time after the Jump, within which B has to be established

# the display states of the Owner contract, DERIVED from the chain state and the BVE time (nothing is stored for them)
DISPLAY_ARRIVAL_RESULT = "ARRIVAL_RESULT"        # Stage TB-H 5b: 0-5 s of the first window with an arrival result popup (it keeps its normal 5.0 s)
DISPLAY_GUIDANCE = "TURNBACK_GUIDANCE"
DISPLAY_REQUEST_READY = "JUMP_REQUEST_READY"
DISPLAY_UNAVAILABLE_ABORT = "JUMP_UNAVAILABLE_ABORT"
DISPLAY_REQUESTED = "JUMP_REQUESTED"
DISPLAY_CANCEL_WARNING = "CANCEL_WARNING"
DISPLAY_RESTOP_WAIT = "RESTOP_WAIT"

IDLE = "idle"
RECOGNIZED = "recognized"
ARMED = "armed"
RESTOP_WAIT = "restop-wait"      # Stage TB-H: the planned Jump was cancelled because the train moved; waits for a re-stop inside the author range of the same A (no Jump in this state)
REQUESTED = "requested"
COMPLETED = "completed"
FAILED = "failed"
DISCARDED = "discarded"

WAITING = (RECOGNIZED, ARMED, RESTOP_WAIT)         # the chain exists and the Jump has not been requested yet
LIVE = WAITING + (REQUESTED,)

CONTINUE = 0
COMPLETE_AFTER_JUMP = 1


class Settlement(NamedTuple):
    """How a Jump transaction ended (written by the Overlay's _finish_jump_transaction): the purpose, the end word of jump_transaction, the selected StationIndex and the ACTUAL landing the completion proved,
    the scope of the request, the origin of the retried checkpoint ('turnback' or None), the generation and the PLANNED time of the Jump (OD-TB-33: the time the B checkpoint keeps)."""
    purpose: str
    end: str
    selected: object
    actual: object
    scope: object
    origin: object
    generation: object
    time_ms: object = None


def qualifying_pair(pairset, a_index, list_id, station_count, start_idx, resolved_end_idx, explicit_end_idx):
    """The pair whose A is `a_index` when PU-1..PU-5 hold, else None. PURE, no side effect; the ONE implementation (the machine and the scoring both use it). Nothing is searched by a name,
    a position or a distance: the StationIndex and the PairSet only."""
    if pairset is None:
        return None
    if pairset.list_id != list_id or pairset.station_count != station_count:      # PU-5
        return None
    pair = None
    for p in pairset.pairs:                                                        # PU-4
        if p.arrival == a_index:
            pair = p
    if pair is None:
        return None
    if not (start_idx < pair.arrival):                                             # PU-1
        return None
    if not (pair.arrival < resolved_end_idx):                                      # PU-2 (end == A: the user's terminal wins, no pseudo-turnback)
        return None
    if explicit_end_idx == pair.departure:                                         # PU-3
        return None
    return pair


def start_station_allowed(pairset, station_index):
    """The scoring START station rule (Owner contract, 2026-10-31): the A of a pair can not be a start (a start Jump that lands at A is no arrival: no chain would begin and the scoring could not go on).
    The B of a pair CAN be a start (the scoring then runs from B with the ordinary logic; whether a station follows B is the existing terminal / section contract, not a pseudo-turnback rule: there is
    no special 'final pair B' concept). Judged by the StationIndex and the pair structure only. The candidate list is generated WITHOUT the excluded station (no disabled row, no refusal dialog)."""
    if pairset is None:
        return True
    for p in pairset.pairs:
        if p.arrival == station_index:
            return False
    return True


def end_station_allowed(pairset, station_index):
    """The scoring END station rule (Owner contract, 2026-10-31): the B of a pair can not be an end (the train never arrives at B by driving: it is placed there by the official Jump, so no end-station
    arrival could complete the scoring). The A of a pair CAN be an end (the section ends at A and does not cross A -> B: no Jump). StationIndex and pair structure only; the candidate list is generated
    without the excluded station."""
    if pairset is None:
        return True
    for p in pairset.pairs:
        if p.departure == station_index:
            return False
    return True


class TurnbackMachine:
    def __init__(self):
        self.pairset = None            # decoded PairSet (pseudo_turnback_contract) or None = key absent / invalid -> no feature
        self.state = IDLE
        self.issued = set()            # PU-7: (generation, list_id, A, arr_seq) of every request ever made in this world
        self._clear_chain()
        self._done_keys = set()
        self._clear_session()

    # ------------------------------------------------------------------ world
    def _clear_chain(self):
        self.pair = None
        self.key = None
        self.generation = None
        self.arrival_ms = None
        self.timing_scored = False
        self.has_special = False
        self.awaiting_b = False
        self.failed_reason = None
        self.jump_earliest_ms = None   # Stage TB-H: the BVE time at or after which the Jump may be requested: arrival + 10.0 s (5b), then re-stop + 5.0 s (arrival_ms itself is never overwritten)
        self.window_ms = None          # the start of the CURRENT guidance window: the arrival, then every re-stop
        self.stop_range = None         # (A position, margin_f, margin_b) of the arrival tick: the author-defined stop range of THIS A (never the 330 m scoring range, never the next target's)
        self.cancel_count = 0
        self.restop_count = 0
        self.cancel_ms = None

    def _clear_session(self):
        """Everything that belongs to ONE scoring session (OD-TB-26 / CH-11): the section fixed at the scoring start button, the last settlement of a Jump transaction, the B watch and the landing watch."""
        self.fixed = None              # the pairs the section crosses, fixed at the scoring start button (StationIndex + PairSet only)
        self.fixed_by_a = None         # the same pairs by the StationIndex of their A (a lookup, never a search)
        self.fixed_generation = None
        self.settlement = None         # the end word of the latest Jump transaction (written by the Overlay's _finish_jump_transaction)
        self.landing = None            # the settlement of THIS chain's Jump (ok / ok-plain), kept while B is being established
        self.b_watch = None            # {"last": BVE ms of the previous observation, "acc": positive advance so far}
        self.landing_watch = None      # START / Retry landing convergence (O1 anchor), see scoring_logic.turnback_landing_step

    def discard_all(self):
        """Drop the chain AND the session records (soft-off, abort, finish, a new scoring start, a generation change). The PairSet belongs to the station list and stays."""
        self._clear_chain()
        self._clear_session()
        self.state = IDLE

    def fix_section(self, pairs, generation):
        self.fixed = tuple(pairs)
        self.fixed_by_a = {p.arrival: p for p in self.fixed}
        self.fixed_generation = generation

    def start_b_watch(self):
        self.b_watch = {"last": None, "acc": 0}

    def b_watch_observe(self, now_ms):
        """OD-TB-28: the reference is the first B-side BVE time after the Jump (the A -> B jump difference is never counted); afterwards only POSITIVE differences add up. 0 and negative differences add nothing; no clock."""
        w = self.b_watch
        if w is None:
            return 0
        if w["last"] is not None and now_ms > w["last"]:
            w["acc"] += now_ms - w["last"]
        w["last"] = now_ms
        return w["acc"]

    def b_watch_exceeded(self):
        return self.b_watch is not None and self.b_watch["acc"] >= B_WATCH_LIMIT_MS

    def set_pairset(self, pairset):
        """The PairSet of the CURRENT station list (None: absent / invalid -> the current behaviour, no pseudo-turnback)."""
        self.pairset = pairset

    def reset_world(self):
        """A new scenario instance / F5 / scenario close / telemetry epoch: nothing is carried over (PR-R20, R21, R23)."""
        had = self.state in LIVE or self.awaiting_b
        self.issued = set()
        self._done_keys = set()
        self._clear_chain()
        self._clear_session()
        self.state = IDLE
        return [("discard_pending", "world-reset")] if had else []

    # ------------------------------------------------------------------ arrival
    def on_arrival(self, now_ms, a_index, arr_seq, generation, list_id, station_count, start_idx, resolved_end_idx, explicit_end_idx, scoring_active, stop_range=None):
        """The host judged an arrival at StationIndex `a_index` (its own, existing arrival detection; now_ms is the BVE time of the tick that ran evaluate_arrival). Returns actions (always empty: the chain only starts).
        `stop_range` (Stage TB-H): (position of A, margin_f, margin_b) as the arrival tick saw them - the author-defined stop range that a re-stop is judged against."""
        if self.pairset is None or not scoring_active:
            return []
        if self.state in LIVE or self.awaiting_b:
            return []                                           # a chain is already running: a duplicate / extra arrival never starts a second one
        if self.fixed is not None:                              # the section was fixed at the scoring start button: nothing is derived again here
            pair = self.fixed_by_a.get(a_index)
        else:
            pair = qualifying_pair(self.pairset, a_index, list_id, station_count, start_idx, resolved_end_idx, explicit_end_idx)
        if pair is None:
            return []
        key = (generation, list_id, a_index, arr_seq)
        if key in self.issued:                                  # PU-7
            return []
        self.pair, self.key, self.generation, self.arrival_ms = pair, key, generation, now_ms
        self.jump_earliest_ms = now_ms + FIRST_REQUEST_AFTER_MS      # Stage TB-H 5b: fixed at the arrival: arrival + 10.0 s
        self.window_ms = now_ms
        self.stop_range = stop_range
        self.cancel_count = self.restop_count = 0
        self.cancel_ms = None
        self.timing_scored = False
        self.has_special = False
        self.failed_reason = None
        self.state = RECOGNIZED
        return []

    def a_scoring_complete(self, now_ms, a_is_timing_station, has_special_popup=False):
        """The host finished the arrival scoring of A (stop position, basic braking...). `has_special_popup`: the arrival produced a special popup (basic braking achieved and / or 0 cm stop).
        Returns the ONE A operating-time action when A is a timing station (OD-PR-4)."""
        if self.state != RECOGNIZED:
            return []
        self.state = ARMED
        self.has_special = bool(has_special_popup)
        acts = []
        if a_is_timing_station and not self.timing_scored:
            self.timing_scored = True
            acts.append(("score_a_time", self.pair.arrival))
        return acts

    def first_window_extra_ms(self):
        """Stage TB-H 5b: how much longer the window that starts at the ARRIVAL is than a window that starts at a re-stop (10.0 s against 5.0 s); 0 after a re-stop. Derived, nothing is stored."""
        return (FIRST_REQUEST_AFTER_MS - REQUEST_AFTER_MS) if self.restop_count == 0 else 0

    def display_phase(self, now_ms):
        """The first window (an arrival, 10.0 s): 'special' 0-5 s (only with an arrival result popup: it shows its normal 5.0 s; without one nothing is shown, None), 'guide' 5-10 s. A window that starts at a re-stop (5.0 s): 'guide' the whole window.
        In BVE time since the window start."""
        if self.state not in (RECOGNIZED, ARMED) or self.window_ms is None:
            return None
        dt = now_ms - self.window_ms
        if dt < 0 or dt >= REQUEST_AFTER_MS + self.first_window_extra_ms():
            return None
        guide_from = FIRST_GUIDE_FROM_MS if self.restop_count == 0 else 0
        if dt < guide_from:
            return "special" if self.has_special else None
        return "guide"

    def display_state(self, now_ms):
        """The display state of the Owner contract (derived; nothing is stored). None: no chain / nothing to show."""
        if self.state in (REQUESTED, COMPLETED):
            return DISPLAY_REQUESTED
        if self.state == FAILED and self.failed_reason == JUMP_UNAVAILABLE_REASON:
            return DISPLAY_UNAVAILABLE_ABORT
        if self.state == RESTOP_WAIT:
            if self.cancel_ms is not None and 0 <= now_ms - self.cancel_ms < CANCEL_WARNING_MS:
                return DISPLAY_CANCEL_WARNING
            return DISPLAY_RESTOP_WAIT
        phase = self.display_phase(now_ms)
        if phase == "special":
            return DISPLAY_ARRIVAL_RESULT
        if phase == "guide":
            return DISPLAY_GUIDANCE
        if self.state == ARMED and self.jump_earliest_ms is not None and now_ms >= self.jump_earliest_ms:
            return DISPLAY_REQUEST_READY
        return None

    # ------------------------------------------------------------------ time
    def tick(self, now_ms, generation, scoring_active, paused=False, menu_open=False, jump_available=True, moving=None, in_stop_range=None):
        """The request is made once, at the BVE time jump_earliest_ms (arrival + 5.0 s; after a re-stop: re-stop + 5.0 s), from that time alone (never from the display state). Nothing here looks at a door.
        `moving` / `in_stop_range` (Stage TB-H) are the host's two facts, already judged strictly (the machine knows no speed value and no position): moving True while the Jump is waiting cancels it (the chain enters
        RESTOP_WAIT, no Jump); in RESTOP_WAIT moving False AND in_stop_range True is the re-stop (a new 5.0 s). None = not observed: nothing is cancelled and nothing is re-stopped.
        `jump_available` False at the request moment: nothing is requested, the chain ends in FAILED and the host aborts the scoring (once)."""
        if self.state not in (ARMED, RESTOP_WAIT):
            return []
        if generation != self.generation or not scoring_active:
            return self._discard("generation" if generation != self.generation else "scoring-ended")
        if paused or menu_open:
            return []
        if self.state == RESTOP_WAIT:
            if moving is not False or in_stop_range is not True:
                return []
            self.state = ARMED
            self.restop_count += 1
            self.window_ms = now_ms
            self.jump_earliest_ms = now_ms + REQUEST_AFTER_MS
            self.has_special = False
            self.cancel_ms = None
            return [("restop_established", {"count": self.restop_count, "window_ms": now_ms})]
        if moving is True:
            self.state = RESTOP_WAIT
            self.cancel_count += 1
            self.cancel_ms = now_ms
            return [("cancel_jump", {"count": self.cancel_count, "at_ms": now_ms})]
        if now_ms < self.jump_earliest_ms:
            return []
        self.issued.add(self.key)
        if not jump_available:
            self.state = FAILED
            self.failed_reason = JUMP_UNAVAILABLE_REASON
            return [("abort_scoring_jump_unavailable", JUMP_UNAVAILABLE_REASON)]
        self.state = REQUESTED
        return [("request_jump", {"purpose": PURPOSE_TURNBACK, "target_index": self.pair.departure, "key": self.key})]

    # ------------------------------------------------------------------ completion
    def on_jump_complete(self, ok, selected_idx, generation):
        """The official Jump settled (the host's existing settlement judged it). Only a Jump that this chain requested counts."""
        if self.state != REQUESTED:
            return []                                           # unsolicited / duplicate / stale: nothing changes
        if generation != self.generation:
            return self._discard("generation")
        if not ok or selected_idx != self.pair.departure:
            self.state = FAILED
            return [("failed", "completion-not-proven")]
        self._done_keys.add(self.key)
        if self.pair.mode == COMPLETE_AFTER_JUMP:
            self.state = COMPLETED
            acts = [("finish_scoring_after_jump", self.pair.arrival)]    # decided inside the completion event, before any B scoring; no checkpoint
            self._clear_chain()
            return acts
        self.state = COMPLETED
        self.awaiting_b = True
        return []

    def on_jump_failed(self, reason):
        """The host's existing fail-closed path (timeout, send refused, endpoint gone). The score and the history are not touched here."""
        if self.state == REQUESTED:
            self.state = FAILED
            return [("failed", reason)]
        return self._discard(reason) if self.state in WAITING else []

    def on_other_arrival(self, station_index):
        """Stage TB-H: the host judged a FORMAL arrival (not a Jump landing) at `station_index` while the chain waits. A itself: nothing. B of this pair (the train was driven there): the Jump to B is never sent, the chain
        is closed as a FAILURE and the host aborts the scoring (fail-closed, SELF_DRIVE_B_REASON; B is not scored as an ordinary arrival). Any other station: the wait state is dropped."""
        if self.state not in WAITING or self.pair is None:
            return []
        if station_index == self.pair.arrival:
            return []
        if station_index == self.pair.departure:
            self.state = FAILED
            self.failed_reason = SELF_DRIVE_B_REASON
            return [("abort_scoring_self_drive_b", SELF_DRIVE_B_REASON)]
        return self._drop("other-station-arrival")

    def drop_if_pair_not_in_run(self):
        """Stage TB-H: the pair of a waiting chain must still be one of the pairs the Run fixed AND of the published PairSet; otherwise (RunPairSet changed) the wait state is dropped. A section that was
        never fixed (fixed is None) is judged by the PairSet only."""
        if self.state not in WAITING or self.pair is None:
            return []
        in_set = self.pairset is not None and self.pair in self.pairset.pairs
        in_run = self.fixed is None or self.pair in self.fixed
        return [] if (in_set and in_run) else self._drop("run-pairset-changed")

    def _drop(self, reason):
        """Stage TB-H: a contract drop of the waiting chain (nothing of it stays; the machine is idle again, as after a Retry)."""
        acts = self._discard(reason)
        if self.state == DISCARDED:
            self.state = IDLE
        return acts

    def drop_waiting(self, reason):
        """Stage TB-H: the host drops a chain that waits for a re-stop (a START / Retry Jump is in flight). Public wrapper of the contract drop."""
        return self._drop(reason) if self.state in WAITING else []

    def on_b_established(self, now_ms):
        """The host reports: B StationIndex resynchronised, B target established, B start state established. Only now ONE B checkpoint (ContinueScoring)."""
        if not self.awaiting_b:
            return []
        pair = self.pair
        self.awaiting_b = False
        self._clear_chain()
        self.state = IDLE
        return [("create_b_checkpoint", {"station_index": pair.departure, "stop_error": 0.0, "save_time_correction": False, "source": "turnback"})]

    # ------------------------------------------------------------------ discard
    def _discard(self, reason):
        had = self.state in LIVE or self.awaiting_b
        self._clear_chain()
        self.state = DISCARDED if had else IDLE
        return [("discard_pending", reason)] if had else []

    def on_retry(self):
        """A retry: any pending chain is dropped (it is rebuilt from a later arrival). The issued keys stay (no re-fire of the same arrival)."""
        acts = self._discard("retry")
        if self.state == DISCARDED:
            self.state = IDLE
        return acts

    def on_f5(self):
        return self.reset_world()

    def on_scenario_close(self):
        return self.reset_world()

    def on_input_device_off(self):
        return self.reset_world()
