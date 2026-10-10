"""Phase SI-A6 - the automatic P-to-P of the managed application: recovering the BVE data that a Pause hides, one concrete operation at a time.

Why this exists. BVE (and so BveEX and the sender) only runs a Tick while the simulation runs. Some operations done WHILE PAUSED change what BVE holds but do
not produce a Tick, so the application never receives the new data. Pressing P once (the Pause ends, a Tick runs, the telemetry flows) and once more (the
Pause comes back) is the recovery - but ONLY when a concrete operation made it necessary. "Session ON / Driving OFF / PAUSED / no data" alone is NOT such a
reason: a normal scenario load shows exactly that for a few hundred milliseconds (the phase SI-A4 fired P-to-P there, in three loads out of three).

Control plane and data plane.
    control plane   needs no Tick: the application SEES the operation (a physical key, the Caller's state block) and holds a PENDING TOKEN for it;
                    the token is closed by the operation's own completion, never by a guess of how long a load takes.
    data plane      first P (the Pause ends, a Tick runs) -> the new data is there (telemetry of the generation, station list, a BVE time that advances)
                    -> second P (the Pause comes back).  Each token allows ONE first P and ONE second P.

The three operations that need a recovery (physically confirmed in the SR session, 2026-10-10) and what this build can do about them:
    f5                F5 (reload of the SAME scenario) while PAUSED: BVE inherits the Pause, no Tick, so no data of the new generation.     IMPLEMENTED
    timetable-jump    BVE's own timetable jump while PAUSED: the BVE time changes, no Tick, the HUD keeps the old time.                     NOT POSSIBLE YET
    scoring-on        TS Scoring switched ON while PAUSED: no Tick, so the Bridge never sees the Caller, no Session, no data.             NOT POSSIBLE YET
For the last two there is no signal that arrives without a Tick (no BveEX event for a timetable jump; the Bridge notices the Caller's Enabled only from its
own Tick, and the managed Python does not outlive "TS Scoring OFF"), so no token of those kinds is ever created: they send NO P. See the SI-A6 report.
BVE's own scenario-list loads, the first load, F5 while RUNNING, a RUNNING timetable jump and the official TS Scoring jump never create a token either.

The F5 token.
    created   only at the physical F5 edge, with the BVE window of THIS BVE process in front, while the Caller says Session ON (a scenario is running: the Caller's
              own Tick goes on in a Pause, so Driving stays ON - phase D1 - and the mode is `active`; `waiting` is accepted too) and the newest STATUS of the sender is
              PAUSED, and only when the Bridge provides the load marker (older Bridge / Caller: nothing happens). F5 is NOT suppressed and NOT re-sent: the application
              only watches the key.
              (Phase SI-A6.1: NO "PAUSED for N seconds" is asked of the user. The real machine showed that F5 pressed at an ordinary speed after P arrived inside such a
              wait and made no token at all. The F5 edge itself separates this from a normal load: a normal load has no F5 edge, so it never makes a token; and what
              follows the edge - generation exactly +1, ScenarioCreated of the new generation, no Tick / Session / data of it for FIRST_QUIET_S - is what a Pause that was
              inherited looks like. An F5 pressed in the short PAUSED window of a load makes a token that closes itself: a running reload ticks by itself, no P is sent.
              The sender reports STATUS every 50 ms and PAUSED after 100 ms without a Tick, so the newest STATUS is at most about 150 ms behind a P.)
              (Phase SI-A6.2: ... and that is exactly the case the real machine hit next. P then F5 FASTER than that: the newest STATUS was still RUNNING at the F5 edge, no token
              was made, the HUD did not come back. The application now also watches the physical P - the same way as F5, GetAsyncKeyState only, nothing suppressed or re-sent.)
    PauseIntent (SI-A6.2). A physical P edge with NO token pending, the newest STATUS RUNNING (a P at PAUSED ends a Pause), the window of THIS BVE process in front, a scenario
              (Session ON), and a P that really reaches BVE (not while a menu is open or a scoring run holds P back) records "the user has just tried to make a Pause": the process
              id, the generation, the state-change count, the time. It is NOT a reason to press P and never presses anything: its only use is to stand in for STATUS=PAUSED at the F5
              edge (the token is then made `via=pause-intent` and everything after is unchanged). It ends silently by: use at the F5 edge (every F5 edge uses it up), Session OFF /
              closed / state lost / Stop / process end, another process or window in front, a generation change, a second P (the user takes the Pause back), the STATUS saying
              PAUSED (the STATUS is the evidence from then on) and PAUSE_INTENT_TTL_S. A RUNNING BVE (the P did not pause, or a normal progress) is the TTL: its life is shorter than
              anything a running BVE shows.
    loading   the generation goes +1 (the reload closed and opened the scenario).  Expires if it does not within F5_TO_GENERATION_MAX_S: then F5 did not reload.
    first P   the Bridge says ScenarioCreated of the new generation was received (a BVE event, published without a Tick) and the generation has NOT ticked,
              has no Session, no telemetry and no station list - and that stayed so for FIRST_QUIET_S (a running reload ticks 12-63 ms after ScenarioCreated;
              a guard against a P into a reload that was not paused, not the trigger). One P, to the BVE window of this process.
    second P  telemetry of the generation is there, the station list is there, the sender says RUNNING and the BVE time advanced. One P.
    closed by (no P is sent from then on) Session OFF / state block closed or lost / Stop / process end, a window of another process in front is NOT a reason (the
              P goes to the window found by PID), the user's own P or F5 (a second F5 starts a new token), a new generation other than +1, data that arrived without
              our P (the user continued or BVE ticked by itself), the second P not reached within SECOND_MAX_S.
"""
import ctypes
import time

import managed_state

KIND_F5_RELOAD = "f5"
KIND_TIMETABLE_JUMP = "timetable-jump"
KIND_SCORING_ON = "scoring-on"
ALL_KINDS = (KIND_F5_RELOAD, KIND_TIMETABLE_JUMP, KIND_SCORING_ON)
# the kinds a token can be created for. The other two have no signal that arrives without a Tick (see the module text); asking for them is refused.
IMPLEMENTED_KINDS = frozenset((KIND_F5_RELOAD,))

VK_P = 0x50
VK_F5 = 0x74

# The ONLY time constants (three). Every other closing of a token is an event. (SI-A6.1: the fourth, PAUSE_SETTLED_S = 1.0, was removed - see the module text.)
F5_TO_GENERATION_MAX_S = 2.0     # F5 -> the generation +1. BVE closes and opens the scenario inside the key handler (SR: Close/Open 1 ms apart, the application saw the
                                 # new generation 28 ms later); a person's next move (a list selection) takes seconds. The measured value is logged (f5_to_gen_ms).
FIRST_QUIET_S = 0.3              # ScenarioCreated seen and still no Tick/Session/data for this long before the first P (a running reload ticks 12-63 ms after it)
SECOND_MAX_S = 10.0              # first P -> second P (SR: telemetry 0.3-0.5 s after the first P, the second P 0.1 s later)
# Phase SI-A6.2: the life of a PauseIntent (the physical P that the user pressed to make a Pause). It only has to cover the lag of the sender's STATUS: STATUS is sent every 50 ms
# and says PAUSED after 100 ms without a Tick (Class1.cs), so the newest STATUS is at most ~150 ms behind a P; plus the timer slot (16 ms), the UDP hop and the event-loop
# latency of the application (measured by SR/SF logs in tens of ms) -> 300 ms. After that the STATUS has said PAUSED (the intent is then dropped: the STATUS is the evidence) or
# BVE did not pause at all (the intent dies; a RUNNING BVE is also what a "normal progress" looks like, so no separate check of the BVE time is made).
PAUSE_INTENT_TTL_S = 0.3

PHASE_ARMED = "armed"            # F5 seen, waiting for the generation to move
PHASE_LOADING = "loading"        # the new generation exists, waiting for ScenarioCreated and the quiet time
PHASE_FIRST_SENT = "first-sent"  # the first P is out, waiting for the data

# fixed words for the diagnostics
R_NO_RELOAD = "no-reload"
R_GENERATION_SKIPPED = "generation-skipped"
R_GENERATION_CHANGED = "generation-changed"
R_SELF_RECOVERED = "self-recovered"
R_MANUAL_P = "manual-p"
R_REPEATED_F5 = "repeated-f5"
R_STATE_CLOSED = "state-closed"
R_STATE_LOST = "state-lost"
R_SESSION_OFF = "session-off"
R_SECOND_TIMEOUT = "second-timeout"
R_WINDOW_LOST = "window-lost"
R_SHUTDOWN = "shutdown"
# the ways a token came to be (the `via` field of recovery-token state=armed) and the words for the (silent) end of a PauseIntent
VIA_STATUS = "status"               # the newest STATUS already said PAUSED
VIA_PAUSE_INTENT = "pause-intent"   # the STATUS was still RUNNING, but a physical P of this BVE had made a Pause a moment ago (Phase SI-A6.2)
I_CONSUMED = "consumed"
I_PAUSED = "paused"
I_TTL = "ttl"
I_REPEATED_P = "repeated-p"
I_STATE = "state"
I_PID = "pid"
I_GENERATION = "generation"
I_FOREGROUND = "foreground"


class Win32KeyApi(object):
    """Physical key state and the foreground window's process (user32, no hook, no suppression). Replaced by a fake in the tests."""

    def __init__(self):
        self._user32 = ctypes.windll.user32
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.GetForegroundWindow.restype = ctypes.c_void_p
        self._user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]

    def is_down(self, vk):
        return bool(self._user32.GetAsyncKeyState(vk) & 0x8000)

    def foreground_pid(self):
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = ctypes.c_ulong(0)
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)


def next_generation(generation):
    """The ScenarioGeneration rule of the Bridge: +1, int32 overflow wraps to 1 (never 0)."""
    return 1 if generation < 0 or generation == 0x7FFFFFFF else generation + 1


class RecoveryToken(object):
    """One pending recovery. Memory only: it dies with the process, and a restarted process starts without one."""
    __slots__ = ("kind", "pid", "gen0", "count0", "status0", "time0", "station_list0", "created_at", "phase", "target_gen", "target_at", "created_seen_at",
                 "first_sent", "first_at", "second_sent", "session_seen", "reference_time")

    def __init__(self, kind, pid, gen0, count0, status0, time0, station_list0, created_at):
        self.kind = kind
        self.pid = pid
        self.gen0 = gen0
        self.count0 = count0
        self.status0 = status0
        self.time0 = time0
        self.station_list0 = station_list0
        self.created_at = created_at
        self.phase = PHASE_ARMED
        self.target_gen = None
        self.target_at = None
        self.created_seen_at = None
        self.first_sent = False
        self.first_at = None
        self.second_sent = False
        self.session_seen = False
        self.reference_time = None


class PauseIntent(object):
    """Phase SI-A6.2: 'the user has just tried to make a Pause in THIS BVE'. Memory only, short-lived, and NEVER a reason to press P: its only use is to stand in for the newest
    STATUS=PAUSED at the F5 edge while that STATUS is still on its way (up to ~150 ms behind the physical P)."""
    __slots__ = ("pid", "generation", "change_count", "created_at", "status0", "consumed")

    def __init__(self, pid, generation, change_count, created_at, status0):
        self.pid = pid
        self.generation = generation
        self.change_count = change_count
        self.created_at = created_at
        self.status0 = status0
        self.consumed = False


class PauseDataRecovery(object):
    """The token machine. One per managed application process. tick() is called by ManagedHudController on every timer slot.

    host      needs find_bve_window() -> hwnd or None, telemetry_ready, emit_event(event, **fields), failsafe, clock (the controller's monotonic clock)
    overlay   needs bve_actual_state, is_bve_loaded, station_list, bve_time_ms, press_p_for_recovery(hwnd)
    keys      needs is_down(vk), foreground_pid()
    """

    def __init__(self, host, overlay, keys, args, clock=None):
        self._host = host
        self._o = overlay
        self._keys = keys
        self._pid = args.bve_pid
        self._clock = clock if clock is not None else getattr(host, "clock", time.monotonic)
        self.token = None
        self.intent = None              # Phase SI-A6.2: the PauseIntent, or None
        self._f5_prev = None            # None = the key was not looked at on the previous slot (a key held since then is not an edge)
        self._p_prev = None
        self._unsupported_noted = False
        # counters (tests and the summary)
        self.created = 0
        self.completed = 0
        self.expired = 0
        self.first_presses = 0
        self.second_presses = 0
        self.refused = 0
        self.intents_created = 0
        self.intents_consumed = 0
        self.last_intent_end = None     # the word of the last end of an intent (tests)

    # -- the public surface -------------------------------------------------------------------------------------------------------------------
    @property
    def active(self):
        return self.token is not None

    def begin(self, kind, snapshot, via=VIA_STATUS):
        """Creates the token of `kind`, or refuses. Only the kinds in IMPLEMENTED_KINDS can ever be created; no token while another one is pending."""
        if kind not in IMPLEMENTED_KINDS or self.token is not None or snapshot is None:
            self.refused += 1
            return False
        self.token = RecoveryToken(kind, self._pid, snapshot.generation, snapshot.change_count, str(getattr(self._o, "bve_actual_state", "")),
                                   getattr(self._o, "bve_time_ms", 0), bool(getattr(self._o, "station_list", None)), self._clock())
        self.created += 1
        self._host.emit_event("recovery-token", state="armed", kind=kind, gen=snapshot.generation, status=self.token.status0 or "none", via=via)
        return True

    def close(self, reason):
        """Closes the pending token (and the PauseIntent) without any P (the operation ended, the state went away, the process is ending)."""
        self._end_intent(I_STATE)
        if self.token is not None:
            self._expire(reason)

    def tick(self, snapshot, mode):
        """snapshot: the newest StateSnapshot or None; mode: the HudGate mode ("active" / "waiting" / "hidden")."""
        if self._host.failsafe is not None:
            self.close(R_STATE_LOST)
            return
        now = self._clock()
        had_token = self.token is not None
        self._check_intent(snapshot, mode, now)
        watching = mode in (managed_state.MODE_WAITING, managed_state.MODE_ACTIVE)
        f5_edge = self._edge(VK_F5, "_f5_prev", self.token is not None or watching)
        p_edge = self._edge(VK_P, "_p_prev", self.token is not None or self.intent is not None or watching)
        if self.token is not None:
            if p_edge:
                self._expire(R_MANUAL_P)
            elif f5_edge:
                self._expire(R_REPEATED_F5)
            else:
                self._advance(snapshot, mode, now)
        if p_edge and not had_token:
            self._on_p_edge(snapshot, mode, now)        # BEFORE the F5 of the same slot: a P and an F5 seen in one slot are taken in this order
        if f5_edge and self.token is None:
            intent = self._take_intent()                # an F5 edge uses the intent up, whether or not it makes a token
            self._maybe_arm(snapshot, mode, now, intent)

    # -- the key edges ----------------------------------------------------------------------------------------------------------------------
    def _edge(self, vk, attr, watching):
        if not watching:
            setattr(self, attr, None)
            return False
        down = bool(self._keys.is_down(vk))
        prev = getattr(self, attr)
        setattr(self, attr, down)
        return down and prev is False

    # -- the PauseIntent (Phase SI-A6.2) ---------------------------------------------------------------------------------------------------
    def _p_reaches_bve(self):
        """Does a physical P reach BVE? Not while TS Scoring holds it back (a menu is open or a scoring run is on: main._sync_system_key_suppression hooks F7 and P)."""
        o = self._o
        scoring = bool(getattr(o, "is_scoring_mode", False)) and not bool(getattr(o, "is_scoring_finished", False))
        return not (bool(getattr(o, "sys_keys_blocked", False)) or getattr(o, "menu_state", 0) != 0 or scoring)

    def _on_p_edge(self, snapshot, mode, now):
        """A physical P with no token pending. It is the evidence that the user is MAKING a Pause - only when the newest STATUS is RUNNING (a P at PAUSED ends the Pause), the window of
        this BVE process is in front, a scenario is on, and the P really reaches BVE. A second P while an intent lives is the user taking the Pause back: the intent just ends."""
        if self.intent is not None:
            self._end_intent(I_REPEATED_P)
            return
        if snapshot is None or snapshot.closed or not snapshot.session or mode not in (managed_state.MODE_ACTIVE, managed_state.MODE_WAITING):
            return
        status = str(getattr(self._o, "bve_actual_state", ""))
        if status != "RUNNING" or not getattr(self._o, "is_bve_loaded", False):
            return
        if self._keys.foreground_pid() != self._pid or not self._p_reaches_bve():
            return
        self.intent = PauseIntent(self._pid, snapshot.generation, snapshot.change_count, now, status)
        self.intents_created += 1

    def _check_intent(self, snapshot, mode, now):
        """The reasons a PauseIntent dies without being used. Nothing is reported: it is not an operation, only a stand-in for a late STATUS."""
        it = self.intent
        if it is None:
            return
        if snapshot is None or snapshot.closed or not snapshot.session or mode not in (managed_state.MODE_ACTIVE, managed_state.MODE_WAITING):
            self._end_intent(I_STATE)
        elif it.pid != self._pid:
            self._end_intent(I_PID)
        elif snapshot.generation != it.generation:
            self._end_intent(I_GENERATION)
        elif str(getattr(self._o, "bve_actual_state", "")) == "PAUSED":
            self._end_intent(I_PAUSED)          # the STATUS arrived: from here on the STATUS itself is the evidence
        elif now - it.created_at > PAUSE_INTENT_TTL_S:
            self._end_intent(I_TTL)
        elif self._keys.foreground_pid() != self._pid:
            self._end_intent(I_FOREGROUND)      # the window of this BVE is not in front (any more): another operation, or the window is gone

    def _take_intent(self):
        it, self.intent = self.intent, None
        if it is not None:
            it.consumed = True
        return it

    def _end_intent(self, why):
        if self.intent is not None:
            self.intent = None
            self.last_intent_end = why

    # -- creation ---------------------------------------------------------------------------------------------------------------------------
    def _maybe_arm(self, snapshot, mode, now, intent=None):
        if snapshot is None or snapshot.closed or not snapshot.session or mode not in (managed_state.MODE_ACTIVE, managed_state.MODE_WAITING):
            return                      # no scenario (title screen, a load in progress): no token
        if not snapshot.load_supported:
            if not self._unsupported_noted:
                self._unsupported_noted = True
                self._host.emit_event("recovery-token", state="unavailable", kind=KIND_F5_RELOAD, reason="no-load-marker")
            return                      # an older Bridge / Caller: the completion of the reload cannot be known, so no P is ever sent
        if not getattr(self._o, "is_bve_loaded", False):
            return                      # no STATUS at all
        if str(getattr(self._o, "bve_actual_state", "")) == "PAUSED":
            via = VIA_STATUS
        elif intent is not None:        # (taken at this very slot, after _check_intent ended it for every reason: process, generation, state, window, time)
            via = VIA_PAUSE_INTENT      # Phase SI-A6.2: P then F5 faster than the STATUS (<= ~150 ms behind a P): the P is the evidence of the Pause
        else:
            return                      # F5 while RUNNING: no token. How long the Pause has lasted is NOT asked (phase SI-A6.1)
        if self._keys.foreground_pid() != self._pid:
            return                      # F5 pressed in another program (or another BVE process): not ours
        if self.begin(KIND_F5_RELOAD, snapshot, via) and via == VIA_PAUSE_INTENT:
            self.intents_consumed += 1

    # -- the life of the token ------------------------------------------------------------------------------------------------------------
    def _advance(self, snapshot, mode, now):
        t = self.token
        if snapshot is None:
            self._expire(R_STATE_LOST)
            return
        if snapshot.closed:
            self._expire(R_STATE_CLOSED)
            return
        if t.phase == PHASE_ARMED:
            self._advance_armed(t, snapshot, now)
        elif t.phase == PHASE_LOADING:
            self._advance_loading(t, snapshot, now)
        else:
            self._advance_first_sent(t, snapshot, now)

    def _advance_armed(self, t, snapshot, now):
        if snapshot.generation == t.gen0:
            if now - t.created_at > F5_TO_GENERATION_MAX_S:
                self._expire(R_NO_RELOAD)       # F5 did not reload anything (a dialog, another window): the Pause is simply still there
            return
        if snapshot.generation != next_generation(t.gen0):
            self._expire(R_GENERATION_SKIPPED)  # more than one scenario instance since F5: not the reload we watched
            return
        t.phase = PHASE_LOADING
        t.target_gen = snapshot.generation
        t.target_at = now
        self._host.emit_event("recovery-token", state="loading", kind=t.kind, gen=t.target_gen, f5_to_gen_ms=int(round((now - t.created_at) * 1000)))

    def _advance_loading(self, t, snapshot, now):
        if snapshot.generation != t.target_gen:
            self._expire(R_GENERATION_CHANGED)
            return
        if self._data_arrived(snapshot):
            self._expire(R_SELF_RECOVERED)      # the data came without our P (the user pressed P, or BVE ticked by itself)
            return
        if not snapshot.created_seen:
            return                              # the load is not finished (it takes seconds): wait for the Bridge's ScenarioCreated, no timer
        if t.created_seen_at is None:
            t.created_seen_at = now
        if now - t.created_seen_at < FIRST_QUIET_S:
            return
        hwnd = self._host.find_bve_window()
        if hwnd is None:
            self._expire(R_WINDOW_LOST)         # the BVE window of THIS process is not there (no P to anything else)
            return
        if self._keys.is_down(VK_P):
            return                              # the user is pressing P right now: look again on the next slot (the edge then closes the token)
        self._o.press_p_for_recovery(hwnd)
        t.first_sent = True
        t.first_at = now
        t.phase = PHASE_FIRST_SENT
        self.first_presses += 1
        self._host.emit_event("kickstart", step="first", token=t.kind, gen=t.target_gen, quiet_ms=int(round((now - t.created_seen_at) * 1000)))

    def _advance_first_sent(self, t, snapshot, now):
        if snapshot.generation != t.target_gen:
            self._expire(R_GENERATION_CHANGED)
            return
        if snapshot.session:
            t.session_seen = True
        elif t.session_seen:
            self._expire(R_SESSION_OFF)         # the scenario was closed again after it had come up
            return
        if now - t.first_at > SECOND_MAX_S:
            self._expire(R_SECOND_TIMEOUT)
            return
        if not self._host.telemetry_ready or not getattr(self._o, "station_list", None):
            return
        if t.reference_time is None:
            t.reference_time = self._o.bve_time_ms   # the BVE time at which the data arrived: the second P needs the time to MOVE on from it
            return
        if "RUNNING" not in str(getattr(self._o, "bve_actual_state", "")) or self._o.bve_time_ms <= t.reference_time:
            return
        hwnd = self._host.find_bve_window()
        if hwnd is None:
            self._expire(R_WINDOW_LOST)
            return
        self._o.press_p_for_recovery(hwnd)
        t.second_sent = True
        self.second_presses += 1
        self._host.emit_event("kickstart", step="second", token=t.kind, gen=t.target_gen)
        self._finish(now)

    def _data_arrived(self, snapshot):
        return bool(snapshot.session or snapshot.tick_seen or self._host.telemetry_ready or getattr(self._o, "station_list", None))

    # -- the end of a token -----------------------------------------------------------------------------------------------------------------
    def _finish(self, now):
        t = self.token
        self.token = None
        self.completed += 1
        self._host.emit_event("recovery-token", state="done", kind=t.kind, gen=t.target_gen, total_ms=int(round((now - t.created_at) * 1000)))

    def _expire(self, reason):
        t = self.token
        self.token = None
        self.expired += 1
        self._host.emit_event("recovery-token", state="expired", kind=t.kind, reason=reason, phase=t.phase, first=int(t.first_sent), second=int(t.second_sent))

    def summary_fields(self):
        return dict(rec_created=self.created, rec_done=self.completed, rec_expired=self.expired, rec_first=self.first_presses, rec_second=self.second_presses,
                    rec_intent=self.intents_created, rec_intent_used=self.intents_consumed)
