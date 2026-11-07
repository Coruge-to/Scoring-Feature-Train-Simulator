"""Shadow sway diagnostics - the BVE passenger-sway figure ("乗客の揺れ") as DIAGNOSTIC-ONLY values. NOTHING here reaches the score, the history, the checkpoints or the result.

BVEの連続的な材質色計算を、TScoringが診断用に7段階へ近似した表示である。(SEVEN_LEVEL_NOTE)  The seven levels are NOT a discrete classification of BVE: the figure's material colour is continuous.

What the figure does (audited in BveTs 5.8.7554.391 and 6.0.7554.619, identical in both): two springs (front-back and left-right), each
    x'' = -2*zeta*omega*x' - omega^2*x + u(t - 0.25) - u(t),   zeta = 1.0, omega = 1.9792033717615696 rad/s, RK4, a 15-sample delay line,
fed by AccelerationZ (front-back) and FrontAccelerationX (left-right). Its colour comes from num = (x_c + 0.315 v_c) + (x_d + 0.315 v_d):
    A = |12.5 * num|,   n = int(A * 64.0),   red = clamp(128 + n/2, 96, 160),   green = clamp(160 - n, 96, 160),   blue = 96.
The main Shadow value is the LONGITUDINAL value (x_c + 0.315 v_c) of the state the BVE figure really keeps (read by reflection in C#, delivered raw as SWAY); its n is nZ.
The combined value (longitudinal + lateral) is REFERENCE ONLY. The public-API replica (SwayReplica: ACCELZ + ACCELX through the same spring model) is kept apart from the reflection
value and is only compared with it.
"""
import math

SWAY_K_V = 0.315                       # the figure looks 0.315 s ahead: x + 0.315 v
SWAY_K_COLOR = 12.5
SWAY_N_SCALE = 64.0
OMEGA = 1.9792033717615696
ZETA = 1.0
DELAY_SECONDS = 0.25
DELAY_SAMPLES = 15                     # max(int(60 * 0.25), 1)
MAX_FRAME_MS = 500                     # the host clamps the frame time to 1..500 ms
WINDOW_SECONDS = 1.0                   # the stop window: T .. T + 1.0 s
WARMUP_MS = 3000                       # a replica that was reset is compared only after 3.0 s
N_CANDIDATE_100 = 34                   # Shadow candidate -100 (n >= 34)
N_CANDIDATE_200 = 52                   # Shadow candidate -200 (n >= 52)
RED_DISPLAY_MIN = 59                   # the displayed red
SATURATION_N = 64                      # the material colour is fully saturated from here
SEVEN_LEVEL_NOTE = "BVEの連続的な材質色計算を、TScoringが診断用に7段階へ近似した表示である。"
LEVELS = ((5, "緑"), (15, "黄緑"), (26, "黄"), (37, "黄橙"), (48, "橙"), (58, "赤橙"))
LAST_LEVEL = "赤"

VALID_END_REASONS = ("t-plus-1s", "restart", "target-change", "station-index-change", "scoring-end")
CUT_END_REASONS = ("jump", "session-end", "generation")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# ---- the derivation (the figure's own order of operations) -----------------------------------------------------------------------------------------------------
def sway_value(x, v):
    """The longitudinal (or lateral) value of one spring: x + 0.315 v."""
    return x + SWAY_K_V * v


def sway_combined(xc, vc, xd, vd):
    """The figure's num: the SIGNED sum of both springs (opposite signs cancel). REFERENCE ONLY."""
    return sway_value(xc, vc) + sway_value(xd, vd)


def sway_n(value):
    """n = int(|12.5 * value| * 64.0), the colour code's order of operations; not clamped. None for a value that is not a finite number."""
    if not _number(value):
        return None
    return int(abs(SWAY_K_COLOR * value) * SWAY_N_SCALE)


def sway_label(n):
    """The seven-level name of n (a diagnostic approximation of the continuous colour). None for no n."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return None
    for upper, name in LEVELS:
        if n <= upper:
            return name
    return LAST_LEVEL


def sway_red_display(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= RED_DISPLAY_MIN


def sway_saturated(n):
    return isinstance(n, int) and not isinstance(n, bool) and n >= SATURATION_N


def sway_penalty_candidate(n):
    """The Shadow candidate of a stop from its n: >= 52 -> -200, >= 34 -> -100, else 0; never -300. None when there is no n. NEVER a score."""
    if not isinstance(n, int) or isinstance(n, bool):
        return None
    if n >= N_CANDIDATE_200:
        return -200
    if n >= N_CANDIDATE_100:
        return -100
    return 0


# ---- the public-API replica ------------------------------------------------------------------------------------------------------------------------------------
class _Spring(object):
    __slots__ = ("x", "v", "buf", "idx", "acc")

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = 0.0
        self.v = 0.0
        self.buf = [0.0] * DELAY_SAMPLES
        self.idx = 0
        self.acc = 0.0

    def _push(self, dt_s, value):
        before = math.floor(self.acc * 60.0)
        self.acc += dt_s
        count = math.floor(self.acc * 60.0) - before
        for _ in range(count):
            self.buf[self.idx] = value
            self.idx = (self.idx + 1) % DELAY_SAMPLES
        self.acc = math.fmod(self.acc, 1.0 / 60.0)

    def step(self, dt_ms, u):
        dt_s = dt_ms * 0.001
        self._push(dt_s, u)
        n = max(int(math.ceil(dt_ms * 60 * 0.001)), 1)
        h = dt_s / n
        delayed = self.buf[self.idx]
        two_zw = 2.0 * ZETA * OMEGA
        w2 = OMEGA * OMEGA
        for _ in range(n):
            x, v = self.x, self.v
            k1 = h * v
            k2 = h * (-two_zw * v - w2 * x + delayed - u)
            k3 = h * (v + k2 / 2.0)
            k4 = h * (-two_zw * (v + k2 / 2.0) - w2 * (x + k1 / 2.0) + delayed - u)
            k5 = h * (v + k4 / 2.0)
            k6 = h * (-two_zw * (v + k4 / 2.0) - w2 * (x + k3 / 2.0) + delayed - u)
            k7 = h * (v + k6)
            k8 = h * (-two_zw * (v + k6) - w2 * (x + k5) + delayed - u)
            self.x += (k1 + 2 * k3 + 2 * k5 + k7) / 6.0
            self.v += (k2 + 2 * k4 + 2 * k6 + k8) / 6.0


class SwayReplica(object):
    """The figure's two springs driven by the PUBLIC inputs (AccelerationZ -> front-back, FrontAccelerationX -> left-right). It is NOT the reflection value: it only reproduces it."""

    def __init__(self):
        self.longitudinal = _Spring()
        self.lateral = _Spring()
        self.reset()

    def reset(self):
        self.longitudinal.reset()
        self.lateral.reset()
        self.warm_long_ms = 0
        self.warm_lat_ms = 0
        self.valid_long = False
        self.valid_lat = False

    def step(self, dt_ms, az, ax):
        """One frame of dt_ms (clamped to 1..500 like the host; <= 0 is ignored). An input that is None / not finite resets its own channel (no 0.0 is invented)."""
        if not _number(dt_ms) or dt_ms <= 0:
            return False
        dt = max(1, min(int(round(dt_ms)), MAX_FRAME_MS))
        if _number(az):
            self.longitudinal.step(dt, float(az))
            self.warm_long_ms += dt
            self.valid_long = True
        else:
            self.longitudinal.reset()
            self.warm_long_ms = 0
            self.valid_long = False
        if _number(ax):
            self.lateral.step(dt, float(ax))
            self.warm_lat_ms += dt
            self.valid_lat = True
        else:
            self.lateral.reset()
            self.warm_lat_ms = 0
            self.valid_lat = False
        return True

    @property
    def longitudinal_value(self):
        return sway_value(self.longitudinal.x, self.longitudinal.v)

    @property
    def lateral_value(self):
        return sway_value(self.lateral.x, self.lateral.v)

    @property
    def combined_value(self):
        return self.longitudinal_value + self.lateral_value

    @property
    def warm(self):
        return self.valid_long and self.warm_long_ms >= WARMUP_MS

    @property
    def warm_lateral(self):
        return self.valid_lat and self.warm_lat_ms >= WARMUP_MS


# ---- the reflection sample ----------------------------------------------------------------------------------------------------------------------------------------
def reflection_sample(overlay):
    """The four raw states of the latest line as a tuple, or None (nothing is invented)."""
    sample = getattr(overlay, "bve_sway", None)
    if not isinstance(sample, (tuple, list)) or len(sample) != 4 or not all(_number(item) for item in sample):
        return None
    return tuple(float(item) for item in sample)


def derive(sample):
    """All derived values of one reflection sample: z (longitudinal value), lat, combined, n_z, n, labels, lateral_effect_n."""
    xc, vc, xd, vd = sample
    z = sway_value(xc, vc)
    lat = sway_value(xd, vd)
    combined = sway_combined(xc, vc, xd, vd)
    n_z = sway_n(z)
    n = sway_n(combined)
    return {"xc": xc, "vc": vc, "xd": xd, "vd": vd, "z": z, "lat": lat, "combined": combined, "n_z": n_z, "n": n,
            "z_label": sway_label(n_z), "label": sway_label(n), "lateral_effect_n": n - n_z}


# ---- the stop window --------------------------------------------------------------------------------------------------------------------------------------------
class _Window(object):
    def __init__(self, t_start, ctx):
        self.t_start = t_start
        self.ctx = ctx
        self.samples = 0
        self.z_min = None
        self.t_zmin = None
        self.abs_peak = None
        self.combined_n_peak = None
        self.peak = None            # the derived values (and the replica's) at the tick of the minimum

    def add(self, t, derived, replica_snapshot):
        self.samples += 1
        z = derived["z"]
        if self.z_min is None or z < self.z_min:
            self.z_min = z
            self.t_zmin = t
            self.peak = dict(derived, replica=replica_snapshot)
        if self.abs_peak is None or abs(z) > self.abs_peak:
            self.abs_peak = abs(z)
        if self.combined_n_peak is None or derived["n"] > self.combined_n_peak:
            self.combined_n_peak = derived["n"]


class SwayShadowState(object):
    """Everything the sway Shadow keeps. Lives on the Overlay as `sway_shadow` (created on first use) and is reset at every formal boundary."""

    def __init__(self):
        self.replica = SwayReplica()
        self.window = None
        self.last = None            # the record of the latest closed window (kept after a cut too, for the log and the tests)
        self.display_n = None       # what F2 shows as "前後最大": the n of the latest VALID window (None = nothing to show)
        self.last_t = None
        self.res_key = None

    # -- the replica follows every tick -------------------------------------------------------------------------------------------------------------------
    def _follow(self, overlay, t):
        az = getattr(overlay, "bve_accel_z", None)
        ax = getattr(overlay, "bve_accel_x", None)
        if self.last_t is not None and t < self.last_t - 1e-9:
            self.replica.reset()                      # time went backwards: the replica starts again
        elif self.last_t is not None and t > self.last_t + 1e-9:
            self.replica.step((t - self.last_t) * 1000.0, az, ax)
        self.last_t = t

    def _snapshot(self):
        r = self.replica
        return {"z": r.longitudinal_value, "n_z": sway_n(r.longitudinal_value), "valid": r.valid_long, "warm": r.warm}

    # -- one tick -------------------------------------------------------------------------------------------------------------------------------------------
    def tick(self, overlay, t, log):
        self._follow(overlay, t)
        w = self.window
        if w is None:
            return
        reason = None
        valid = True
        if getattr(overlay, "bve_jump_count", 0) != getattr(overlay, "last_jump_count", 0) or getattr(overlay, "is_official_jumping", False):
            reason, valid = "jump", False             # a Jump is the stronger boundary: it wins over a restart in the same tick
        elif getattr(overlay, "bve_tgt_idx", None) != w.ctx["target_station_index"]:
            reason = "target-change"
        elif getattr(overlay, "bve_arr_idx", None) != w.ctx["station_index"]:
            reason = "station-index-change"
        elif abs(getattr(overlay, "bve_speed", 0.0)) > 0.0:
            reason = "restart"
        elif (not getattr(overlay, "is_scoring_mode", True)) or getattr(overlay, "is_scoring_finished", False):
            reason = "scoring-end"
        elif t - w.t_start > WINDOW_SECONDS + 1e-9:
            reason = "t-plus-1s"
        if reason is not None:
            self.close(overlay, t, reason, valid, log)
            return
        self._add_sample(overlay, t)
        if t - w.t_start >= WINDOW_SECONDS - 1e-9:     # the tick at exactly T + 1.0 s still belongs to the window and ends it
            self.close(overlay, t, "t-plus-1s", True, log)

    def _add_sample(self, overlay, t):
        sample = reflection_sample(overlay)
        if sample is None or self.window is None:
            return
        self.window.add(t, derive(sample), self._snapshot())

    # -- the stop (T) ----------------------------------------------------------------------------------------------------------------------------------------
    def start(self, overlay, t, penalties):
        """The stop instant T. `penalties` = {"calcg": int, "bveg": int | "not-evaluated"} of the same stop (diagnostic copies, nothing here changes them)."""
        if self.window is not None:
            self.close(overlay, t, "new-stop", True, None)
        ctx = {"station_index": getattr(overlay, "bve_arr_idx", -1), "target_station_index": getattr(overlay, "bve_tgt_idx", -1),
               "official_jumping": bool(getattr(overlay, "is_official_jumping", False)), "generation": getattr(overlay, "current_scenario_id", -1),
               "penalties": penalties}
        self.window = _Window(t, ctx)
        self._add_sample(overlay, t)                  # the sample of T itself belongs to the window

    # -- boundaries (Jump / Retry / F5 / generation / session end) -------------------------------------------------------------------------------------------
    def boundary(self, overlay, reason, log):
        """A formal boundary: an open window is cut (not valid), the display value goes, the replica starts again, nothing of the old world is carried over."""
        if self.window is not None:
            self.close(overlay, getattr(self, "last_t", None) if self.last_t is not None else self.window.t_start, reason, False, log)
        self.display_n = None
        self.replica.reset()
        self.last_t = None
        if reason == "generation":
            self.res_key = None

    # -- closing -------------------------------------------------------------------------------------------------------------------------------------------------
    def close(self, overlay, t_end, reason, valid, log):
        w = self.window
        self.window = None
        if w is None:
            return None
        unavailable = w.samples == 0
        n_peak = None if unavailable else sway_n(w.z_min)
        record = {
            "end_reason": reason, "valid": bool(valid), "unavailable": unavailable, "t_start": w.t_start, "t_end": t_end, "samples": w.samples,
            "state_peak": None if unavailable else abs(w.z_min), "abs_peak": w.abs_peak, "n_peak": n_peak,
            "delay_ms": None if unavailable else (w.t_zmin - w.t_start) * 1000.0, "combined_n_peak": w.combined_n_peak,
            "penalty_sway": sway_penalty_candidate(n_peak), "z_min_nonneg": (not unavailable) and w.z_min >= 0.0,
            "peak": w.peak, "ctx": w.ctx,
        }
        self.last = record
        if valid and not unavailable:
            self.display_n = n_peak
        elif not valid:
            self.display_n = None
        if log is not None:
            log(format_log(record, getattr(overlay, "bve_sway_res", None), self._snapshot(), self.replica))
        return record

    # -- the resolution diagnostic (logged once per change) -----------------------------------------------------------------------------------------------
    def note_resolution(self, res, log):
        if not isinstance(res, dict):
            return
        key = (res.get("result"), res.get("version"), res.get("entry"), res.get("detail"))
        if key == self.res_key:
            return
        self.res_key = key
        if log is not None:
            log("[SHADOW SWAY RESOLVE] result=%s bve_version=%s entry=%s detail=%s" % (key[0], key[1], key[2], key[3] or "none"))

    # -- what F2 shows ------------------------------------------------------------------------------------------------------------------------------------------
    def display_peak_n(self):
        w = self.window
        if w is not None and w.samples > 0:
            return sway_n(w.z_min)
        return self.display_n


def state_of(overlay):
    state = overlay.__dict__.get("sway_shadow")
    if state is None:
        state = SwayShadowState()
        overlay.sway_shadow = state
    return state


# ---- the diagnostic log -------------------------------------------------------------------------------------------------------------------------------------------
def _f(value, digits=6):
    return "unavailable" if value is None else ("%." + str(digits) + "f") % value


def _i(value):
    return "unavailable" if value is None else "%d" % value


def format_log(record, res, now_snapshot, replica):
    """One `[SHADOW SWAY]` line per closed window. The combined value is marked REFERENCE ONLY. Everything is a diagnostic: nothing here is a score."""
    ctx = record["ctx"]
    peak = record["peak"]
    res = res if isinstance(res, dict) else {}
    available = record["samples"] > 0
    reason = res.get("result") or "no-diagnostic"
    if res.get("detail"):
        reason += ":" + res["detail"]
    if not available and reason == "ok":
        reason = "no-sample"
    rep = peak["replica"] if peak is not None else now_snapshot
    if peak is None:
        reflect_vs_replica = "unavailable"
    elif not rep["valid"]:
        reflect_vs_replica = "unavailable"
    elif not rep["warm"]:
        reflect_vs_replica = "warmup"
    else:
        reflect_vs_replica = "%.6f" % (peak["z"] - rep["z"])
    pen = ctx["penalties"] or {}
    sway_pen = record["penalty_sway"]
    fields = (
        ("bve_version", res.get("version") or "unknown"),
        ("sway_reflection_available", "1" if available else "0"),
        ("sway_reflection_reason", reason),
        ("sway_longitudinal_state", _f(peak["xc"]) if peak else "unavailable"),
        ("sway_longitudinal_velocity", _f(peak["vc"]) if peak else "unavailable"),
        ("sway_lateral_state", _f(peak["xd"]) if peak else "unavailable"),
        ("sway_lateral_velocity", _f(peak["vd"]) if peak else "unavailable"),
        ("sway_longitudinal_value", _f(peak["z"]) if peak else "unavailable"),
        ("sway_longitudinal_n", _i(peak["n_z"]) if peak else "unavailable"),
        ("sway_longitudinal_color", peak["z_label"] if peak else "unavailable"),
        ("sway_combined_state", _f(peak["combined"]) if peak else "unavailable"),
        ("sway_combined_n", _i(peak["n"]) if peak else "unavailable"),
        ("sway_combined_color", peak["label"] if peak else "unavailable"),
        ("combined", "reference-only"),
        ("lateral_effect_n", _i(peak["lateral_effect_n"]) if peak else "unavailable"),
        ("reconstructed_longitudinal_state", _f(rep["z"]) if rep["valid"] else "unavailable"),
        ("reconstructed_longitudinal_n", _i(rep["n_z"]) if rep["valid"] else "unavailable"),
        ("reflection_reconstruction_delta", reflect_vs_replica),
        ("stop_sway_longitudinal_n_peak", _i(record["n_peak"])),
        ("stop_sway_longitudinal_state_peak", _f(record["state_peak"])),
        ("stop_sway_longitudinal_abs_peak", _f(record["abs_peak"])),
        ("stop_sway_combined_n_peak", _i(record["combined_n_peak"])),
        ("stop_sway_peak_delay_ms", _f(record["delay_ms"], 1)),
        ("z_min_nonneg", "1" if record["z_min_nonneg"] else "0"),
        ("n_peak_red_display", "1" if sway_red_display(record["n_peak"]) else "0"),
        ("n_peak_saturated", "1" if sway_saturated(record["n_peak"]) else "0"),
        ("shadow_penalty_calcg", str(pen.get("calcg", "not-evaluated"))),
        ("shadow_penalty_bveg", str(pen.get("bveg", "not-evaluated"))),
        ("shadow_penalty_sway", "not-evaluated" if sway_pen is None else str(sway_pen)),
        ("official_jumping", "1" if ctx["official_jumping"] else "0"),
        ("scenario_generation", str(ctx["generation"])),
        ("station_index", str(ctx["station_index"])),
        ("target_station_index", str(ctx["target_station_index"])),
        ("end_reason", record["end_reason"]),
        ("valid", "1" if record["valid"] else "0"),
        ("window_start", "%.3f" % record["t_start"]),
        ("reflect_samples", str(record["samples"])),
    )
    return "[SHADOW SWAY] " + " ".join("%s=%s" % (k, v) for k, v in fields)


# ---- the F2 values (the third line is assembled in hud_ui.py) ------------------------------------------------------------------------------------------
def f2_values(overlay, available):
    """The three F2 texts: (前後, 前後最大, 合成). '34[黄橙]', '52[赤橙]', '32' - or '--' for what is not available. The combined one gets no colour name (REFERENCE ONLY)."""
    state = state_of(overlay)
    sample = reflection_sample(overlay) if available else None
    now_z = now_c = "--"
    if sample is not None:
        d = derive(sample)
        now_z = "%d[%s]" % (d["n_z"], d["z_label"])
        now_c = "%d" % d["n"]
    peak = state.display_peak_n()
    peak_text = "--" if peak is None else "%d[%s]" % (peak, sway_label(peak))
    return now_z, peak_text, now_c
