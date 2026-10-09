"""Phase E4 - the HUD of the managed application: shown, updated, hidden and resumed from the Caller's Session / Driving state.

What this module is: the managed-mode replacement of the PRESENTATION part of Overlay.update_logic, nothing more. It owns no window and no timer
of its own: it drives the ONE Overlay and the ONE QTimer that main.run_managed hands over, so the HUD is the same object for the whole life of
the process (never rebuilt per ScenarioGeneration, per Pause or per soft OFF).

    mode ACTIVE   (Session ON and Driving ON)   the Overlay is linked to THIS BVE process's window, shown, kept on its client area and updated -
                                                (Phase L3: only once real telemetry of the current ScenarioGeneration has been received; until then it stays hidden)
    mode WAITING  (Session ON, Driving OFF)     soft OFF: the Overlay is hidden, nothing is updated, nothing is destroyed; resumes by itself
    mode HIDDEN   (Session OFF / Closed / no block)  hard OFF: the same, until the next Session ON

What it deliberately does NOT do (later phases): scoring start / finish / discard, key hooks and input suppression, Esc quit, Kickstart, jump
or F8 key injection, update notices, quitting when the BVE window disappears (the lifetime of the process belongs to the Stop event).
The HUD data itself keeps coming from the existing UDP telemetry of the Overlay; the physics bookkeeping the HUD depends on
(update_physics_and_scoring) is run exactly as in normal mode and stays inert for scoring because is_scoring_mode is never switched on here.

Diagnostics: one `[MANAGED] ...` line per STATE CHANGE (fixed words and numbers; no path, no HUD text); identical readings are only counted.
"""
import time

import managed_state
import telemetry_contract
import telemetry_gate
from managed_mode import describe_exception

ACTIVE_INTERVAL_MS = 16          # the interval the Overlay's own timer has always used
IDLE_INTERVAL_MS = 100           # while nothing is shown: only the state block is looked at
WINDOW_SEARCH_INTERVAL_S = 0.5   # EnumWindows is not run more often than this while no BVE window is linked
MAX_HUD_ERROR_LINES = 5
MAX_ZORDER_LINES = 5             # hud-zorder-set / hud-zorder-error lines; further ones are only counted


class Win32WindowApi(object):
    """The few window operations of the HUD (pywin32). Imported lazily so that the pure parts can be tested without a desktop."""

    def __init__(self):
        import win32con
        import win32gui
        import win32process
        self._con = win32con
        self._gui = win32gui
        self._proc = win32process

    def find_bve_window(self, bve_pid):
        """The visible top-level window of THIS BVE process whose title is the one the normal mode looks for ("bve trainsim"). None if none."""
        found = []
        gui, proc = self._gui, self._proc

        def callback(hwnd, _):
            try:
                if gui.IsWindowVisible(hwnd) and "bve trainsim" in gui.GetWindowText(hwnd).lower():
                    if proc.GetWindowThreadProcessId(hwnd)[1] == bve_pid:
                        found.append(hwnd)
            except Exception:
                pass
            return True

        gui.EnumWindows(callback, None)
        return found[-1] if found else None

    def is_window(self, hwnd):
        return bool(self._gui.IsWindow(hwnd))

    def is_iconic(self, hwnd):
        return bool(self._gui.IsIconic(hwnd))

    def client_rect_on_screen(self, hwnd):
        """(x, y, w, h) of the client area in screen coordinates, or None when it has no size."""
        rect = self._gui.GetClientRect(hwnd)
        if rect[2] <= 0 or rect[3] <= 0:
            return None
        x, y = self._gui.ClientToScreen(hwnd, (0, 0))
        return x, y, rect[2], rect[3]

    def owner_of(self, overlay_hwnd):
        return self._gui.GetWindow(int(overlay_hwnd), self._con.GW_OWNER)

    def set_owner(self, overlay_hwnd, bve_hwnd):
        """Makes the BVE window the OWNER of the Overlay (the way normal mode links it), so the HUD stays above BVE and follows it."""
        self._gui.SetWindowLong(int(overlay_hwnd), self._con.GWL_HWNDPARENT, bve_hwnd)

    def z_above(self, hwnd):
        """The window directly above `hwnd` in the Z order (visible or not, any process); 0 when `hwnd` is the top of its band."""
        try:
            return int(self._gui.GetWindow(int(hwnd), self._con.GW_HWNDPREV) or 0)
        except Exception:
            return 0                     # pywin32 raises when there is no previous window

    def is_topmost(self, hwnd):
        return bool(self._gui.GetWindowLong(int(hwnd), self._con.GWL_EXSTYLE) & self._con.WS_EX_TOPMOST)

    def place_below(self, overlay_hwnd, above_hwnd):
        """Puts the Overlay directly BELOW `above_hwnd` in the Z order (0: at the top of the normal, non-topmost band). Never TOPMOST, never activates,
        never moves or resizes: a pure Z-order operation."""
        flags = self._con.SWP_NOMOVE | self._con.SWP_NOSIZE | self._con.SWP_NOACTIVATE
        self._gui.SetWindowPos(int(overlay_hwnd), above_hwnd if above_hwnd else self._con.HWND_TOP, 0, 0, 0, 0, flags)


def hud_update_step(overlay):
    """The data part of Overlay.update_logic that the HUD content depends on, in the same order and with the same rules: the clock of the
    scoring bookkeeping, update_physics_and_scoring, repaint. No window search, no key hook, no key injection, no fast-forward release."""
    from scoring_logic import reset_transient_scoring_state, update_physics_and_scoring
    current_time = overlay.bve_time_ms / 1000.0
    if overlay.last_update_time == 0.0 or current_time < overlay.last_update_time:
        dt = 0.0
        reset_transient_scoring_state(overlay)
        overlay.jump_lock = False
        overlay.ignore_next_pass_score = False
        overlay.last_update_time = current_time
    else:
        dt = current_time - overlay.last_update_time
        overlay.last_update_time = current_time
    overlay.last_bve_time_ms = overlay.bve_time_ms
    update_physics_and_scoring(overlay, current_time, dt)
    overlay.update()


class ManagedHudController(object):
    """Drives one Overlay from the state block. tick() is the slot of the Overlay's single timer; shutdown() ends it.

    overlay     needs show / hide / isVisible / setGeometry / geometry / winId / update (the real Overlay; a fake in tests)
    timer       the Overlay's one QTimer (setInterval only; the controller never creates a timer)
    window_api  find_bve_window / is_window / is_iconic / client_rect_on_screen / owner_of / set_owner / z_above / is_topmost / place_below
    update_step called once per tick while ACTIVE
    telemetry   Phase L3: the strict TelemetryGate (telemetry_gate.py) or None. With it the HUD is only shown while real telemetry of the CURRENT
                ScenarioGeneration has been received (and the sender has not moved on to the next scenario); without it (None) nothing is waited for.
    """

    def __init__(self, overlay, reader, window_api, args, log, update_step=hud_update_step, timer=None, clock=time.monotonic, telemetry=None):
        self._overlay = overlay
        self._telemetry = telemetry
        self._reader = reader
        self._api = window_api
        self._args = args
        self._log = log
        self._update_step = update_step
        self._timer = timer
        self._clock = clock
        self.gate = managed_state.HudGate()
        self._interval = None
        self._shown = False
        self._hwnd = None               # the BVE window the Overlay is linked to
        self._geom = None
        self._next_search = 0.0
        self._wait_logged = False
        self._shutdown = False
        self._error_lines = 0
        self._items_reported = None     # the HUD items the sender cannot provide, as last reported (None = not yet)
        self._failsafe = None           # the reason the state block was lost after AppReady (latched until the process ends)
        self._closed_seen = False       # the Caller withdrew the state (Closed flag): the NORMAL end
        self.startup_failure = None     # why start() failed (the managed contract is not met)
        self.failsafes = 0
        # counters (tests and the summary line)
        self.shows = 0
        self.hides = 0
        self.update_starts = 0
        self.update_waits = 0
        self.updates = 0
        self.ticks = 0
        self.link_count = 0
        self.owner_sets = 0
        self.z_sets = 0
        self.z_errors = 0
        self.owner_releases = 0
        self.errors = 0

    # -- diagnostics --------------------------------------------------------------------------------------------------------------------
    def _emit(self, event, **fields):
        text = "[MANAGED] event=%s inst=%s owner=%s pid=%d" % (event, self._args.instance, self._args.owner, self._args.bve_pid)
        for key in sorted(fields):
            text += " %s=%s" % (key, fields[key])
        try:
            self._log(text)
        except Exception:
            pass

    def emit_event(self, event, **fields):
        """The diagnostic line writer for the telemetry gate and the HUD item report: one `[MANAGED] event=...` line per state change, in a COMPACT
        form (no instance id, no owner): the Caller transcribes at most 160 characters of an application line, and these lines carry lists."""
        text = "[MANAGED] event=%s pid=%d" % (event, self._args.bve_pid)
        for key in sorted(fields):
            text += " %s=%s" % (key, fields[key])
        try:
            self._log(text)
        except Exception:
            pass

    @property
    def shown(self):
        return self._shown

    @property
    def mode(self):
        return self.gate.mode

    @property
    def failsafe(self):
        """The reason of the fail-safe (the state block was lost after AppReady), or None."""
        return self._failsafe

    @property
    def input_allowed(self):
        """The gate every input operation of a later phase must pass. Never open without a live ACTIVE state; in the fail-safe it is shut for good.
        (Phase E4 itself has no input operation: managed mode installs no key hook.)"""
        return self._failsafe is None and not self._shutdown and self.gate.mode == managed_state.MODE_ACTIVE

    # -- the timer slot -----------------------------------------------------------------------------------------------------------------
    def tick(self):
        if self._shutdown:
            return
        self.ticks += 1
        if self._failsafe is not None:
            return                       # fail-safe: no reading, no update, no window work; only the Stop request ends this process
        try:
            snapshot = self._reader.poll()
            if self._reader.lost is not None:
                self._enter_failsafe(self._reader.lost)
                return
            change = self.gate.apply(snapshot)
            if change is not None:
                self._on_change(change)
            if self.gate.mode == managed_state.MODE_ACTIVE:
                self._tick_active()
        except Exception as e:
            self._on_error(e)

    def _on_change(self, c):
        fields = dict(session=int(c.session), driving=int(c.driving), gen=c.generation, mode=c.mode, was=c.previous_mode)
        if c.generation_changed:
            fields["prev_gen"] = c.previous_generation
        if c.skipped_changes:
            fields["coalesced"] = c.skipped_changes
        if c.closed:
            fields["closed"] = "yes"
        kinds = []
        if c.session_changed:
            kinds.append("session-on" if c.session else "session-off")
        if c.driving_changed:
            kinds.append("driving-on" if c.driving else "driving-off")
        if c.generation_changed:
            kinds.append("generation-changed")
        self._emit("state", change="+".join(kinds) if kinds else "none", **fields)
        if c.closed and not self._closed_seen:
            self._closed_seen = True
            self._emit("state-closed", reason="caller-withdrew", loss="no")     # the normal end, not a loss of the block

        if c.generation_changed:
            self._on_generation(c.generation)

        if c.mode == managed_state.MODE_ACTIVE:
            if c.previous_mode != managed_state.MODE_ACTIVE:
                self.update_starts += 1
                self._geom = None            # a resumed HUD takes the BVE window's current place again
                self._emit("hud-update-start", gen=c.generation)
                self._set_interval(ACTIVE_INTERVAL_MS)
        else:
            if c.previous_mode == managed_state.MODE_ACTIVE:
                self.update_waits += 1
                self._emit("hud-update-wait", reason="driving-off" if c.session else "session-off")
            self._set_interval(IDLE_INTERVAL_MS)
            self._hide("driving-off" if c.session else "session-off")

    def _on_generation(self, generation):
        """Phase L3: a new ScenarioGeneration. The telemetry of the previous one is retired; when the sender had already moved on to the new scenario
        its newest datagram was held and is applied now (the HUD then needs no further datagram to appear, e.g. while the simulation is paused)."""
        if self._telemetry is None:
            return
        held = self._telemetry.on_generation(generation)
        if held is not None:
            apply = getattr(self._overlay, "apply_telemetry_text", None)
            if apply is not None:
                apply(held)

    def _enter_failsafe(self, reason):
        """The state block was lost after AppReady (the reader already wrote the one `state-lost` line). The HUD is hidden and no longer
        updated, input stays closed; the process is neither killed nor restarted and the Overlay is neither rebuilt nor destroyed: it waits for
        the Caller's Stop request. The gate is forced OFF so that nothing reads it as active."""
        self._failsafe = reason
        self.failsafes += 1
        was_active = self.gate.mode == managed_state.MODE_ACTIVE
        self.gate.apply(None)
        if was_active:
            self.update_waits += 1
            self._emit("hud-update-wait", reason="state-lost")
        self._set_interval(IDLE_INTERVAL_MS)
        self._hide("state-lost")

    def _tick_active(self):
        overlay, api = self._overlay, self._api
        if self._telemetry is not None and not self._telemetry.ready:
            # Session ON and Driving ON are not enough: nothing is shown (and no placeholder HUD) until real telemetry of this generation arrived
            self._hide("telemetry-wait")
            return
        self._report_items()
        linked = self._ensure_window()
        if linked:
            try:
                if api.is_iconic(self._hwnd):
                    self._hide("bve-minimized")
                    linked = False
                else:
                    rect = api.client_rect_on_screen(self._hwnd)
                    if rect is not None and rect != self._geom:
                        overlay.setGeometry(*rect)
                        self._geom = rect
                    self._show()
                    self._ensure_owner()
                    self._ensure_z_order()
            except Exception:
                self._unlink("bve-window-error")
                linked = False
        if self._update_step is not None:
            self._update_step(overlay)
            self.updates += 1

    def _report_items(self):
        """Phase L3: which HUD items the sender cannot provide (AVAIL) - one `hud-items` line when that set changes (fixed words, no values)."""
        if self._telemetry is None:
            return
        availability = self._telemetry.availability
        unavailable = tuple(sorted(item for item in telemetry_contract.HUD_ITEM_REQUIRES if not availability.item(item)))
        if unavailable != self._items_reported:
            self._items_reported = unavailable
            self.emit_event("hud-items", unavailable="+".join(unavailable) or "none")

    def _ensure_window(self):
        api = self._api
        if self._hwnd is not None and not api.is_window(self._hwnd):
            self._unlink("bve-window-gone")
        if self._hwnd is not None:
            return True
        now = self._clock()
        if now < self._next_search:
            return False
        self._next_search = now + WINDOW_SEARCH_INTERVAL_S
        hwnd = api.find_bve_window(self._args.bve_pid)
        if hwnd is None:
            if not self._wait_logged:
                self._wait_logged = True
                self._emit("hud-window-wait", reason="bve-window-not-found")
            return False
        self._hwnd = hwnd
        self._geom = None
        self._wait_logged = False
        self.link_count += 1
        self._emit("hud-window-linked", links=self.link_count)
        return True

    def _ensure_owner(self):
        """The Overlay must be OWNED by the BVE window. It is checked after the window is shown (Qt may create the native window only then, and a
        window re-created by show() has no owner), on every active tick: one GetWindow call, and a log line only when the owner had to be set."""
        overlay_hwnd = int(self._overlay.winId())
        if self._api.owner_of(overlay_hwnd) != self._hwnd:
            self._api.set_owner(overlay_hwnd, self._hwnd)
            self.owner_sets += 1
            self._emit("hud-owner-set", n=self.owner_sets)

    def _ensure_z_order(self):
        """The HUD belongs DIRECTLY ABOVE the BVE driving window: above the driving view, below every other window that is above it - the scenario
        selection window of BVE among them, which is NOT identified (no title, no class, no ScenarioGeneration): whatever lies over the driving window
        stays over the HUD. Being the OWNER's window is not enough: show() puts a (re)created native window at the top of the Z order, in front of
        such a window, and setting the owner afterwards does not reorder anything.

        Nothing is done while the HUD already is the window directly above the driving window (one GetWindow call per active tick). Otherwise the HUD
        is moved directly under the window that lies directly above the driving window (a pure Z operation: no activation, no move, no resize), or to
        the top of the NORMAL band when that window is a topmost one - the HUD never becomes topmost. A failure here is counted and logged (a few
        lines), never hides the HUD and never unlinks it."""
        try:
            overlay_hwnd = int(self._overlay.winId())
            if not overlay_hwnd:
                return                               # the native window does not exist (yet): nothing to order
            api = self._api
            above = api.z_above(self._hwnd)
            if above == overlay_hwnd:
                return                               # already directly above the driving window
            if above and api.is_topmost(above):
                above = 0                            # stay in the normal band, right over the driving window
            api.place_below(overlay_hwnd, above)
            self.z_sets += 1
            if self.z_sets <= MAX_ZORDER_LINES:
                self._emit("hud-zorder-set", n=self.z_sets)
        except Exception as e:
            self.z_errors += 1
            if self.z_errors <= MAX_ZORDER_LINES:
                self._emit("hud-zorder-error", error=describe_exception(e), n=self.z_errors)

    def _unlink(self, reason):
        if self._hwnd is not None:
            self._hwnd = None
            self._geom = None
            self._next_search = 0.0
            self._emit("hud-window-unlinked", reason=reason)
        self._hide(reason)

    def _release_owner_before_show(self):
        """Showing a window that still has an OWNER brings the owner to the front with it (Windows keeps an owner and its owned windows together): a
        re-shown HUD that still is owned by the BVE window would lift the whole driving window over the scenario selection window. Qt only clears the
        owner while it shows the window, too late. So the owner is released BEFORE show(); _ensure_owner() links the HUD again right after it. Nothing
        happens for a window that has no owner (the first show). A failure is counted, never blocks the show."""
        try:
            overlay_hwnd = int(self._overlay.winId())
            if overlay_hwnd and self._api.owner_of(overlay_hwnd):
                self._api.set_owner(overlay_hwnd, 0)
                self.owner_releases += 1
        except Exception:
            self.z_errors += 1

    def _show(self):
        if self._shown:
            return
        self._release_owner_before_show()
        self._overlay.show()
        self._shown = True
        self.shows += 1
        self._emit("hud-show", shows=self.shows, gen=self.gate.generation)

    def _hide(self, reason):
        if not self._shown:
            return
        self._overlay.hide()
        self._shown = False
        self.hides += 1
        self._emit("hud-hide", reason=reason, hides=self.hides)

    def _set_interval(self, ms):
        if self._interval == ms:
            return
        self._interval = ms
        if self._timer is not None:
            self._timer.setInterval(ms)

    def _on_error(self, exc):
        self.errors += 1
        if self._error_lines < MAX_HUD_ERROR_LINES:
            self._error_lines += 1
            self._emit("hud-error", error=describe_exception(exc), n=self.errors)

    # -- end ----------------------------------------------------------------------------------------------------------------------------
    def start(self):
        """Called once before AppReady is published and before the event loop runs: the state block is opened and the first reading is taken
        now, so the HUD starts from the CURRENT state (hidden unless a tick later shows it).

        Returns False when the state block is missing or invalid: the managed contract is not met (one diagnostic line was written, the reason is
        in `startup_failure`). The caller must then NOT publish AppReady and must leave with the init-failure exit code."""
        self._set_interval(IDLE_INTERVAL_MS)
        if not self._reader.open():
            self.startup_failure = self._reader.open_failure or "unknown"
            return False
        snapshot = self._reader.last
        change = self.gate.apply(snapshot)
        if change is not None:
            self._on_change(change)
        else:
            self._emit("state", change="initial", session=int(self.gate.session), driving=int(self.gate.driving), gen=self.gate.generation,
                       mode=self.gate.mode, was=self.gate.mode)
        return True

    def shutdown(self):
        """The state is withdrawn on our side (HUD hidden, updates stopped, mapping released). Idempotent. The Overlay itself is closed by the caller."""
        if self._shutdown:
            return
        self._shutdown = True
        if self.gate.mode != managed_state.MODE_HIDDEN or self._shown:
            self._emit("state-withdrawn", mode=self.gate.mode)
        self._hide("shutdown")
        self._reader.close()
        # how the state ended, in words that tell the three cases apart: init-failed (contract never met), state-lost (abnormal loss after
        # AppReady), caller-closed (the Caller withdrew the state first: the normal Dispose), stop-without-closed (Stop arrived with no withdrawal)
        end = ("init-failed" if self.startup_failure is not None else "state-lost" if self._failsafe is not None
               else "caller-closed" if self._closed_seen else "stop-without-closed")
        self._emit("hud-summary", end=end, failsafes=self.failsafes, ticks=self.ticks, updates=self.updates, shows=self.shows, hides=self.hides, starts=self.update_starts,
                   waits=self.update_waits, state_changes=self.gate.changes, duplicates=self.gate.suppressed, gen_changes=self.gate.generation_changes,
                   coalesced=self.gate.skipped_changes, links=self.link_count, owner_sets=self.owner_sets, errors=self.errors)
        if self.z_sets or self.z_errors or self.owner_releases:
            self.emit_event("hud-zorder-summary", sets=self.z_sets, releases=self.owner_releases, errors=self.z_errors)    # only when the Z order was ever touched; a line of its own, hud-summary is already longer than the Caller transcribes
        if self._telemetry is not None:
            self.emit_event("telemetry-summary", **self._telemetry.summary_fields())     # a line of its own: hud-summary is already longer than the Caller transcribes


def create_controller(overlay, args, log):
    """The production wiring: real mapping source, real window API, the Overlay's own timer."""
    reader = managed_state.StateReader(args, managed_state.Win32StateSource(), log)
    gate = telemetry_gate.TelemetryGate(strict=True)
    controller = ManagedHudController(overlay, reader, Win32WindowApi(), args, log, timer=getattr(overlay, "timer", None), telemetry=gate)
    gate.log = controller.emit_event
    overlay.telemetry_gate = gate           # the Overlay's telemetry intake and its HUD items follow the same gate
    return controller
