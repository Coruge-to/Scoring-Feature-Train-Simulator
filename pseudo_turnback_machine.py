"""The pseudo-turnback chain state machine. PURE (no Qt, no Win32, no socket, no file, no clock, no global state): the host feeds events with the
BVE time and acts on the returned actions. It never writes the Overlay and never sends a Jump itself.

What it decides (PTS-0 Pair contract §11, S22A, Owner OD-PR-1 beta / OD-PR-3 / OD-PR-4, Owner display contract 2026-10-31):
  * the use conditions PU-1..PU-7 are evaluated at EVERY arrival; no 'done'/'not applicable' flag is kept for a pair (the issued key is the only memory: PU-7);
  * A: the arrival scoring of the host comes first; then ONE A operating-time score (only for a pair A that is a timing station); NO A checkpoint, ever;
  * the Jump is requested ONCE, at the BVE time of the arrival (the tick that ran evaluate_arrival) + 5.0 s, never waiting for or looking at a door, never reading a signal flag;
  * the 5.0 s are shown as ONE of two timelines (never 3 s + 2 s as a rule): without a special arrival popup (basic braking achieved / 0 cm stop) the guidance is shown for the whole 5.0 s;
    with one the special popup is shown for 3.0 s (however many special popups there are), then the guidance for 2.0 s. The request time does NOT depend on the display;
  * a Jump that cannot be sent (the sender does not announce the Jump group) is never requested: the chain ends in FAILED and the host aborts the scoring (fail-closed, reason JUMP_UNAVAILABLE_REASON);
  * B: after the official Jump completed, and the host reported that B is established (StationIndex, target, start state), ONE B checkpoint for a ContinueScoring pair, none for a final pair;
  * a final pair (CompleteAfterJump): the finish action is returned from the completion event itself, before anything of B is scored (order protection I-12), and NO checkpoint.
Door state and signal flags are not parameters of any function here, on purpose."""

PURPOSE_TURNBACK = "turnback"        # the purpose of the Jump (distinct from retry / start); the formal home is jump_transaction.JUMP_TURNBACK (Stage TB-C)

REQUEST_AFTER_MS = 5000              # the Jump request: BVE time of the arrival + 5.0 s
SPECIAL_DISPLAY_MS = 3000            # the special arrival popup (basic braking achieved / 0 cm stop), when there is one
GUIDE_TOTAL_MS = REQUEST_AFTER_MS    # the guidance ends where the request is made

JUMP_UNAVAILABLE_REASON = "pseudo-turnback-jump-unavailable"

# the display states of the Owner contract, DERIVED from the chain state and the BVE time (nothing is stored for them)
DISPLAY_SPECIAL_3S = "ARRIVAL_SPECIAL_3S"
DISPLAY_GUIDANCE = "TURNBACK_GUIDANCE"
DISPLAY_REQUEST_READY = "JUMP_REQUEST_READY"
DISPLAY_UNAVAILABLE_ABORT = "JUMP_UNAVAILABLE_ABORT"
DISPLAY_REQUESTED = "JUMP_REQUESTED"

IDLE = "idle"
RECOGNIZED = "recognized"
ARMED = "armed"
REQUESTED = "requested"
COMPLETED = "completed"
FAILED = "failed"
DISCARDED = "discarded"

CONTINUE = 0
COMPLETE_AFTER_JUMP = 1


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

    def set_pairset(self, pairset):
        """The PairSet of the CURRENT station list (None: absent / invalid -> the current behaviour, no pseudo-turnback)."""
        self.pairset = pairset

    def reset_world(self):
        """A new scenario instance / F5 / scenario close / telemetry epoch: nothing is carried over (PR-R20, R21, R23)."""
        had = self.state in (RECOGNIZED, ARMED, REQUESTED) or self.awaiting_b
        self.issued = set()
        self._done_keys = set()
        self._clear_chain()
        self.state = IDLE
        return [("discard_pending", "world-reset")] if had else []

    # ------------------------------------------------------------------ arrival
    def on_arrival(self, now_ms, a_index, arr_seq, generation, list_id, station_count, start_idx, resolved_end_idx, explicit_end_idx, scoring_active):
        """The host judged an arrival at StationIndex `a_index` (its own, existing arrival detection; now_ms is the BVE time of the tick that ran evaluate_arrival). Returns actions (always empty: the chain only starts)."""
        if self.pairset is None or not scoring_active:
            return []
        if self.state in (RECOGNIZED, ARMED, REQUESTED) or self.awaiting_b:
            return []                                           # a chain is already running: a duplicate / extra arrival never starts a second one
        pair = qualifying_pair(self.pairset, a_index, list_id, station_count, start_idx, resolved_end_idx, explicit_end_idx)
        if pair is None:
            return []
        key = (generation, list_id, a_index, arr_seq)
        if key in self.issued:                                  # PU-7
            return []
        self.pair, self.key, self.generation, self.arrival_ms = pair, key, generation, now_ms
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

    def display_phase(self, now_ms):
        """'special' (0-3 s, only with a special popup), 'guide' (3-5 s with a special popup, 0-5 s without) or None, in BVE time since the arrival."""
        if self.state not in (RECOGNIZED, ARMED) or self.arrival_ms is None:
            return None
        dt = now_ms - self.arrival_ms
        if dt < 0 or dt >= GUIDE_TOTAL_MS:
            return None
        if self.has_special and dt < SPECIAL_DISPLAY_MS:
            return "special"
        return "guide"

    def display_state(self, now_ms):
        """The display state of the Owner contract (derived; nothing is stored). None: no chain / nothing to show."""
        if self.state in (REQUESTED, COMPLETED):
            return DISPLAY_REQUESTED
        if self.state == FAILED and self.failed_reason == JUMP_UNAVAILABLE_REASON:
            return DISPLAY_UNAVAILABLE_ABORT
        phase = self.display_phase(now_ms)
        if phase == "special":
            return DISPLAY_SPECIAL_3S
        if phase == "guide":
            return DISPLAY_GUIDANCE
        if self.state == ARMED and self.arrival_ms is not None and now_ms - self.arrival_ms >= REQUEST_AFTER_MS:
            return DISPLAY_REQUEST_READY
        return None

    # ------------------------------------------------------------------ time
    def tick(self, now_ms, generation, scoring_active, paused=False, menu_open=False, jump_available=True):
        """The request is made once, at BVE-time arrival + 5.0 s, from the arrival time alone (never from the display state). Nothing here looks at a door.
        `jump_available` False at that moment: nothing is requested, the chain ends in FAILED and the host aborts the scoring (once)."""
        if self.state != ARMED:
            return []
        if generation != self.generation or not scoring_active:
            return self._discard("generation" if generation != self.generation else "scoring-ended")
        if paused or menu_open:
            return []
        if now_ms - self.arrival_ms < REQUEST_AFTER_MS:
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
        return self._discard(reason) if self.state in (RECOGNIZED, ARMED) else []

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
        had = self.state in (RECOGNIZED, ARMED, REQUESTED) or self.awaiting_b
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
