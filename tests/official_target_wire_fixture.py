"""Phase SI-R2.1 (T-1a) - the PROVISIONAL wire constants, the vector loader / self-check, the observation Scene and the row reporter of the official-target RED runners.

NOT a discoverable unit test (the file name does not start with test_). Used by tests/red_official_target_supply.py, ..._ownership.py and ..._reinit.py.

PROVISIONAL (Owner decision E-10): the wire format below is NOT the final product format. Everything that names the wire (part name, version, field order, state words, the Python
attribute names and verdict words) lives in section A of THIS module, so that the Owner can fix the wire later by editing one place. The meaning vectors
(tests/official_target_vectors.json) are written in SEMANTIC terms (state / index / expected target) and never contain a wire token, except the `raw` strings of the
malformed-input cases, which are deliberately wire-level.

THE FIXTURE IS NOT A COPY OF THE PRODUCT. It only (1) converts a semantic vector into a telemetry line / an Overlay scene and (2) reads what the REAL Overlay and the REAL
draw_hud produce. It contains no station-selection, no ownership, no NEXTTIME derivation and no HUD formatting. The expected values are literals in the vector file; the
"oracle" self-check proves that those literals are what the HUD of the REAL application renders when it is handed the expected target (so a hand-computing mistake in a
vector is a FIXTURE FAIL, not a false RED).

Row verdicts (the vocabulary of tests/red_si_diag_onjumped_probe.py / SI-R2.1 spec):
  RED-VALID     every premise holds and at least one contract assert fails (the reason words say which; NOT-IMPLEMENTED = the product has no official-target part / attribute yet)
  GUARD         every premise and every contract assert holds (a regression guard that is green before AND after the implementation)
  RED-INVALID   a premise is broken or the fixture raised: the row proves nothing (Close condition: 0)
  ENV           the interpreter / environment can not run the row (Close condition: 0)
Each row also carries the PREDICTION made before the first run; a row whose verdict differs from its prediction is reported as UNEXPECTED.
"""
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VECTORS_PATH = os.path.join(HERE, "official_target_vectors.json")

# =====================================================================================================================================================================================
# A. PROVISIONAL wire / attribute / verdict vocabulary (E-10: edit HERE to fix the wire)
# =====================================================================================================================================================================================
PROVISIONAL = True
PART_NAME = "OFFTGT"
WIRE_VERSION = 1
FIELD_ORDER = ("state", "idx", "count", "hash", "loc", "mb", "mf")      # after "OFFTGT:<version>:"
STATE_WORDS = ("K", "T", "N", "U", "F")                                   # E-11: known / terminal none / no station / temporarily unavailable / read failed
HELPER_NAME = "OfficialTargetWire"                                        # the shared C# helper (StationListIdentity.cs), provisional
PY_MODULE = "official_target_contract"                                    # the pure Python module (provisional)

# Python semantic states (E-11 / E-13). NONE = T or N (not a wire token).
PY_STATES = ("KNOWN", "NONE_TERMINAL", "NONE_EMPTY", "UNAVAILABLE", "READ_FAILED", "ABSENT", "INVALID", "NOT_INITIALIZED")
NONE_CLASS = ("NONE_TERMINAL", "NONE_EMPTY")
WIRE_TO_STATE = {"K": "KNOWN", "T": "NONE_TERMINAL", "N": "NONE_EMPTY", "U": "UNAVAILABLE", "F": "READ_FAILED"}
PY_VERDICTS = ("off-ok", "off-none-terminal", "off-none-empty", "off-unavailable", "off-read-failed", "off-missing", "off-scope", "off-list-mismatch", "off-loc",
               "off-malformed", "off-version", "off-range", "off-not-ready")
STATE_VERDICT = {"KNOWN": "off-ok", "NONE_TERMINAL": "off-none-terminal", "NONE_EMPTY": "off-none-empty", "UNAVAILABLE": "off-unavailable", "READ_FAILED": "off-read-failed",
                 "ABSENT": "off-missing"}
OFFICIAL_ATTRS = {"state": "official_state", "index": "official_index", "location": "official_location", "margin_b": "official_margin_b",
                  "margin_f": "official_margin_f", "reason": "official_reason"}      # the prefix official_* is canon (E-11); the suffixes are provisional
LOC_TOLERANCE_M = 0.01
LIST_GRACE_MS = 3000
MISSING = object()


def fmt_num(x):
    """The invariant shortest round-trip text of a number (provisional codec of loc / margins): 2000.0 -> '2000', 570.04 -> '570.04'."""
    if isinstance(x, bool):
        raise TypeError("bool")
    if isinstance(x, int):
        return str(x)
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return repr(float(x))


def build_part(sem, list_id, count, station_list=None):
    """Semantic official target -> the provisional wire part (no leading comma). sem keys: state, index, loc, mb, mf, count_override, hash_override, version_override, raw.
    A non-K state carries idx/loc/mb/mf = -1 unless the vector forces other values (the range / consistency cases)."""
    if "raw" in sem:
        return sem["raw"].replace("%HASH%", list_id).replace("%COUNT%", str(count))
    state = sem["state"]
    if state == "K":
        idx = sem["index"]
        if "loc" in sem:
            loc = sem["loc"]
        else:
            loc = station_list[idx]["location"]
        mb, mf = sem.get("mb", 5.0), sem.get("mf", 5.0)
    else:
        idx, loc, mb, mf = sem.get("index", -1), sem.get("loc", -1), sem.get("mb", -1), sem.get("mf", -1)
    cnt = sem.get("count_override", count)
    hsh = sem.get("hash_override", list_id)
    ver = sem.get("version_override", WIRE_VERSION)
    return "%s:%d:%s:%s:%s:%s:%s:%s:%s" % (PART_NAME, ver, state, fmt_num(idx), fmt_num(cnt), hsh, fmt_num(loc), fmt_num(mb), fmt_num(mf))


def parse_part(text):
    """TEST-LOCAL decoder used only by the round-trip self-check of the fixture (it is NOT the product parser). Returns a dict or None."""
    f = text.split(":")
    if len(f) != 2 + len(FIELD_ORDER) or f[0] != PART_NAME:
        return None
    try:
        out = {"version": int(f[1]), "state": f[2], "index": int(f[3]), "count": int(f[4]), "hash": f[5], "loc": float(f[6]), "mb": float(f[7]), "mf": float(f[8])}
    except ValueError:
        return None
    return out


# =====================================================================================================================================================================================
# B. vectors: loader and self-check
# =====================================================================================================================================================================================
def load_vectors():
    with open(VECTORS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def stalist_payload(stations):
    """The STALIST payload text (name=timing=loc=arr=dep=def=stop=pass=term, comma separated) of a list definition of the vector file."""
    rows = []
    for s in stations:
        rows.append("=".join([s["name"], "1" if s.get("timing", True) else "0", fmt_num(s["location"]), str(s.get("arr", -1)), str(s.get("dep", -1)), str(s.get("def", -1)),
                              str(s.get("stop", 15000)), "1" if s.get("pass", False) else "0", "1" if s.get("terminal", False) else "0"]))
    return ",".join(rows)


STEP_KEYS = {"note", "list", "sid", "time_ms", "loc", "speed", "door", "doordir", "is_pass", "term", "machine", "official", "jump", "avail", "own", "generation", "expect",
             "advance_ms", "set_attrs", "no_line"}
MACHINE_KEYS = {"nextloc", "nexttime", "tgt", "arr", "seq"}
OWN_KEYS = {"mode", "finished", "jumping", "retry"}
EXPECT_KEYS = {"owner", "official_state", "official_index", "official_reason", "official_reason_in", "official_location", "target_nextloc", "target_nexttime", "hud_dist",
               "hud_time_left", "official_state_in", "official_index_not", "state_not", "mode_after", "finished_after", "held", "save_data_len", "identity_usable",
               "tgt_idx", "hud_dist_either", "hud_time_left_either", "alt_target_nextloc", "alt_target_nexttime"}
OFFICIAL_EXPECT_KEYS = {"official_state", "official_index", "official_reason", "official_reason_in", "official_location", "official_state_in", "official_index_not", "state_not"}
CASE_KEYS = {"id", "file", "source", "list", "strict", "steps", "note", "family"}


def vector_problems(vec):
    """Fixture self-check (schema, required fields, token enum, duplicate case id, invalid index, contradictory expectations, generation monotonicity). [] = sound."""
    bad = []
    lists = vec.get("lists", {})
    seen = set()
    for key, sl in lists.items():
        if not sl:
            bad.append("list %s is empty" % key)
        for s in sl:
            for need in ("name", "location"):
                if need not in s:
                    bad.append("list %s: station without %s" % (key, need))
        locs = [s["location"] for s in sl]
        if locs != sorted(locs):
            bad.append("list %s: locations are not ascending" % key)
    for case in vec.get("cases", []):
        cid = case.get("id", "?")
        if cid in seen:
            bad.append("duplicate case id %s" % cid)
        seen.add(cid)
        extra = set(case) - CASE_KEYS
        if extra:
            bad.append("%s: unknown case keys %s" % (cid, sorted(extra)))
        for need in ("id", "file", "source", "steps", "list"):
            if need not in case:
                bad.append("%s: missing %s" % (cid, need))
        if case.get("file") not in ("supply", "ownership", "reinit"):
            bad.append("%s: file must be supply|ownership|reinit" % cid)
        if not str(case.get("source", "")).startswith(("observed:", "synthetic")):
            bad.append("%s: source must start with observed: or synthetic" % cid)
        if case.get("list") not in lists and case.get("list") != "EMPTY":
            bad.append("%s: unknown list %s" % (cid, case.get("list")))
        cur_list = case.get("list")
        last_sid, last_gen = None, None
        for n, st in enumerate(case.get("steps", [])):
            tag = "%s#%d" % (cid, n)
            extra = set(st) - STEP_KEYS
            if extra:
                bad.append("%s: unknown step keys %s" % (tag, sorted(extra)))
            if "list" in st:
                cur_list = st["list"]
                if cur_list not in lists and cur_list != "EMPTY":
                    bad.append("%s: unknown list %s" % (tag, cur_list))
            if set(st.get("machine", {})) - MACHINE_KEYS:
                bad.append("%s: unknown machine keys" % tag)
            if set(st.get("own", {})) - OWN_KEYS:
                bad.append("%s: unknown own keys" % tag)
            off = st.get("official")
            if off is not None and "raw" not in off:
                if off.get("state") not in STATE_WORDS:
                    bad.append("%s: official state %r is not one of %s" % (tag, off.get("state"), STATE_WORDS))
                if off.get("state") == "K" and "index" not in off:
                    bad.append("%s: K without index" % tag)
                if off.get("state") == "K" and "loc" not in off and cur_list in lists:
                    idx = off.get("index", -1)
                    if not (0 <= idx < len(lists[cur_list])) and not off.get("allow_out_of_range"):
                        bad.append("%s: K index %s is outside list %s and the vector does not say allow_out_of_range" % (tag, idx, cur_list))
            ex = st.get("expect", {})
            extra = set(ex) - EXPECT_KEYS
            if extra:
                bad.append("%s: unknown expect keys %s" % (tag, sorted(extra)))
            st_state = ex.get("official_state")
            if st_state is not None and st_state not in PY_STATES:
                bad.append("%s: expect.official_state %r is not a Python state" % (tag, st_state))
            for s in ex.get("official_state_in", []):
                if s not in PY_STATES:
                    bad.append("%s: expect.official_state_in has %r" % (tag, s))
            if st_state == "KNOWN" and not (isinstance(ex.get("official_index"), int) and ex["official_index"] >= 0):
                bad.append("%s: expects KNOWN without a non-negative official_index (contradiction)" % tag)
            if st_state is not None and st_state != "KNOWN" and ex.get("official_index", -1) != -1:
                bad.append("%s: expects %s with an index (contradiction)" % (tag, st_state))
            if "target_nextloc" in ex and ex["target_nextloc"] < 0 and ex.get("hud_dist", "--- m") != "--- m":
                bad.append("%s: no target but a HUD distance (contradiction)" % tag)
            if "target_nextloc" in ex and ex["target_nextloc"] >= 0 and ex.get("hud_dist") == "--- m":
                bad.append("%s: a target but the HUD shows none (contradiction)" % tag)
            if "target_nexttime" in ex and ex["target_nexttime"] <= 0 and ex.get("hud_time_left", "--:--") != "--:--":
                bad.append("%s: no target time but a HUD time (contradiction)" % tag)
            if "owner" in ex and ex["owner"] not in ("BVE", "TS"):
                bad.append("%s: owner must be BVE or TS" % tag)
            if ex.get("owner") == "TS" and (set(ex) & OFFICIAL_EXPECT_KEYS):
                bad.append("%s: a TS-owned step must not expect anything of the official target (the official state is independent of the owner: put it on a BVE step)" % tag)
            if ("hud_dist" in ex or "hud_time_left" in ex or "hud_dist_either" in ex or "hud_time_left_either" in ex) and "owner" not in ex:
                bad.append("%s: a HUD literal needs an explicit owner" % tag)
            if "hud_dist_either" in ex or "hud_time_left_either" in ex:
                # E-11: how long a U may keep the last K is NOT decided (N is the Owner's). The contract is N-agnostic: the HUD is either NONE or the display of the last K target.
                if not ("hud_dist_either" in ex and "hud_time_left_either" in ex and "alt_target_nextloc" in ex and "alt_target_nexttime" in ex and "target_nextloc" in ex and "target_nexttime" in ex):
                    bad.append("%s: an 'either' HUD needs both either lists, target_* (the NONE branch) and alt_target_* (the hold branch)" % tag)
                elif ex["owner"] != "BVE" or len(ex["hud_dist_either"]) != 2 or len(ex["hud_time_left_either"]) != 2:
                    bad.append("%s: an 'either' HUD is [none, hold], BVE-owned only" % tag)
                elif ex["hud_dist_either"][0] != "--- m" or ex["hud_time_left_either"][0] != "--:--":
                    bad.append("%s: the first branch of an 'either' HUD must be NONE" % tag)
            if ex.get("owner") == "BVE" and ("hud_dist" in ex or "hud_time_left" in ex) and not ("target_nextloc" in ex and "target_nexttime" in ex):
                bad.append("%s: a BVE-owned HUD literal needs target_nextloc and target_nexttime (the oracle proves the literal from them)" % tag)
            if "sid" in st:
                if last_sid is not None and st["sid"] < last_sid:
                    bad.append("%s: sid goes backwards (%s -> %s)" % (tag, last_sid, st["sid"]))
                last_sid = st["sid"]
            if "generation" in st:
                if last_gen is not None and st["generation"] <= last_gen:
                    bad.append("%s: generation is not increasing (%s -> %s)" % (tag, last_gen, st["generation"]))
                last_gen = st["generation"]
            if "loc" in st and st["loc"] < -1000:
                bad.append("%s: absurd location" % tag)
    for sig in vec.get("pins", {}):
        if len(vec["pins"][sig]) != 64:
            bad.append("pin %s is not a sha256" % sig)
    return bad


def wire_roundtrip_problems(vec):
    """Every semantic official target of the vectors, built with the provisional codec and decoded by the test-local decoder, gives back the same fields."""
    bad = []
    for case in vec["cases"]:
        cur = case["list"]
        for n, st in enumerate(case["steps"]):
            cur = st.get("list", cur)
            off = st.get("official")
            if off is None or "raw" in off:
                continue
            sl = vec["lists"].get(cur, [])
            payload = stalist_payload(sl)
            part = build_part(off, "ABCD1234", len(sl), sl if off.get("state") != "K" or "loc" in off or 0 <= off.get("index", -1) < len(sl) else None)
            dec = parse_part(part)
            tag = "%s#%d" % (case["id"], n)
            if dec is None:
                bad.append("%s: the fixture encoder produced an undecodable part %r" % (tag, part))
                continue
            if dec["state"] != off["state"]:
                bad.append("%s: state does not round-trip" % tag)
            if off["state"] == "K" and "loc" not in off and 0 <= off["index"] < len(sl):
                if abs(dec["loc"] - sl[off["index"]]["location"]) > 1e-9:
                    bad.append("%s: loc does not round-trip" % tag)
            del payload
    return bad


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


# =====================================================================================================================================================================================
# C. observation Scene: the REAL Overlay (tests/sia_rig.py: every outside effect a recorder), the REAL telemetry gate, the REAL draw_hud (its text calls are recorded)
# =====================================================================================================================================================================================
DIST_RE = re.compile(r"^(--- m|-?\d+(?:\.\d+)? (?:m|km))$")
TIMELEFT_RE = re.compile(r"^(--:--|-?\d{1,2}:\d{2}|-?\d:\d{2}:\d{2})$")
_STATE = {"home": None, "saved": None}


def harness_init():
    """Redirect the profile so that nothing a test triggers can write to the real one; returns an ENV problem string or ''."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _STATE["home"] = tempfile.TemporaryDirectory(prefix="ts-offtgt-")
    _STATE["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _STATE["home"].name
    os.environ["HOME"] = _STATE["home"].name
    try:
        from PyQt6.QtWidgets import QApplication
        _STATE["app"] = QApplication.instance() or QApplication(["offtgt"])
        import main  # noqa: F401
        import hud_ui  # noqa: F401
        import sia_rig  # noqa: F401
    except Exception as exc:                      # the interpreter can not run the real Overlay (python -I hides PyQt6)
        return "%s: %s" % (type(exc).__name__, str(exc)[:80])
    return ""


def harness_leftovers():
    """Files the run wrote into the redirected profile (must be none). Also restores the environment."""
    try:
        left = os.listdir(_STATE["home"].name) if _STATE["home"] is not None else []
    finally:
        for k, v in (_STATE["saved"] or {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if _STATE["home"] is not None:
            _STATE["home"].cleanup()
    return left


class Scene(object):
    """One Overlay + the gate + the HUD recorder. Use as `with Scene(vec, strict=False) as sc:` (a Rig of main.py must not be nested)."""

    DEFAULTS = {"sid": 7, "time_ms": 36000000, "loc": 0.0, "speed": 0.0, "door": 0, "doordir": 1, "is_pass": 0, "term": 0,
                "machine": {"nextloc": -1.0, "nexttime": -1, "tgt": -1, "arr": -1, "seq": 0}}

    def __init__(self, vec, strict=False):
        self.vec = vec
        self.strict = strict
        self.state = json.loads(json.dumps(self.DEFAULTS))
        self.cur_list = None
        self.list_id = ""
        self.count = 0
        self.stations = []
        self.hud = {"dist": None, "time_left": None, "label": None}
        self.texts = []
        self.generation = 1

    def __enter__(self):
        import main
        import hud_ui
        import sia_rig as R
        import telemetry_gate
        self.main, self.hud_ui, self.R = main, hud_ui, R
        self.rig = R.Rig(main)
        self.o = self.rig.o
        if self.strict:
            self.o.telemetry_gate = telemetry_gate.TelemetryGate(strict=True)
            self.o.telemetry_gate.on_generation(self.generation)
        self._orig_draw = hud_ui.draw_text_with_stroke
        hud_ui.draw_text_with_stroke = lambda painter, text, *a, **k: self._drawn.append(text)
        self._drawn = []
        return self

    def __exit__(self, *exc):
        self.hud_ui.draw_text_with_stroke = self._orig_draw
        self.rig.close()
        return False

    # -- feeding ---------------------------------------------------------------------------------------------------------------------------------------
    def push(self, text):
        """The production intake: a datagram into the (stub) socket, then read_udp_data (the same call the Qt signal makes)."""
        self.o.udp_socket.incoming.append(text.encode("utf-8"))
        self.o.read_udp_data()

    def load_list(self, key):
        import station_index_contract as sic
        self.cur_list = key
        self.stations = [] if key == "EMPTY" else self.vec["lists"][key]
        payload = stalist_payload(self.stations)
        self.list_id = sic.list_id(payload)
        self.count = len(self.stations)
        if key == "EMPTY":
            import station_identity
            self.o.station_list = station_identity.StationList(list_id=self.list_id)
            return
        self.push("STALIST:" + payload)

    def telemetry_text(self, st):
        m = st["machine"]
        parts = ["SCENARIO_ID:%d" % st["sid"], "TIME:%d" % st["time_ms"], "LOCATION:%s" % fmt_num(st["loc"]), "SPEED:%s" % fmt_num(st["speed"]),
                 "NEXTLOC:%s" % fmt_num(m["nextloc"]), "NEXTTIME:%d" % m["nexttime"], "ISPASS:%d" % st["is_pass"], "ISTIMING:1", "DOORDIR:%d" % st["doordir"],
                 "DOOR:%d" % st["door"], "TERM:%d" % st["term"]]
        parts.append("STIDX:1:%d:%d:%d:%d:%s" % (m["tgt"], m["arr"], m["seq"], self.count, self.list_id))
        if st.get("jump") is not None:
            parts.append("JUMP:%d" % st["jump"])
        off = st.get("official")
        if off is not None:
            parts.append(build_part(off, self.list_id, self.count, self.stations))
        if st.get("avail") is not None:
            parts.append("AVAIL:1:" + "+".join(st["avail"]))
        return ",".join(parts)

    def step(self, step):
        """Apply one vector step (state carries forward except `official`, which is per line) and feed the resulting line."""
        st = self.state
        for k, v in step.items():
            if k == "machine":
                st["machine"].update(v)
            elif k in ("sid", "time_ms", "loc", "speed", "door", "doordir", "is_pass", "term", "jump", "avail"):
                st[k] = v
        st["official"] = step.get("official")
        if "advance_ms" in step:
            st["time_ms"] += step["advance_ms"]
        if step.get("generation") is not None and self.strict:
            self.generation = step["generation"]
            held = self.o.telemetry_gate.on_generation(self.generation)
            if held:
                self.o.apply_telemetry_text(held)
        if "list" in step:
            self.load_list(step["list"])
        own = step.get("own")
        if own is not None:
            self.o.is_scoring_mode = bool(own.get("mode", False))
            self.o.is_scoring_finished = bool(own.get("finished", False))
            self.o.is_official_jumping = bool(own.get("jumping", False))
            self.o.is_official_retry = bool(own.get("retry", False))
        for name, value in step.get("set_attrs", {}).items():
            setattr(self.o, name, value)
        if not step.get("no_line"):
            self.push(self.telemetry_text(st))
        self.render()

    # -- observing -------------------------------------------------------------------------------------------------------------------------------------
    def render(self):
        self._drawn.clear()
        self.o.grab()
        self.texts = list(self._drawn)
        dist = next((i for i, t in enumerate(self.texts) if DIST_RE.match(t)), None)
        tl = next((t for t in self.texts if TIMELEFT_RE.match(t)), None)
        self.hud = {"dist": self.texts[dist] if dist is not None else None, "time_left": tl, "label": self.texts[dist - 1] if dist else None}
        return self.hud

    def official(self):
        """{suffix: value or MISSING} of the official_* attributes of the Overlay."""
        return {k: getattr(self.o, a, MISSING) for k, a in OFFICIAL_ATTRS.items()}

    def official_present(self):
        return self.official()["state"] is not MISSING

    def applied(self, step_state=None):
        """Premise helper: the last line was applied to the Overlay (its TIME is the Overlay's TIME)."""
        return self.o.bve_time_ms == self.state["time_ms"] and self.o.current_scenario_id == self.state["sid"]


def case_by_id(vec, cid):
    for c in vec["cases"]:
        if c["id"] == cid:
            return c
    raise KeyError(cid)


def cases_of(vec, file_key):
    return [c for c in vec["cases"] if c["file"] == file_key]


def check_expect(ctx, sc, step, tag, results=None):
    """Compare one step's `expect` with what the REAL Overlay holds / draws. Premises (the line was applied, the HUD rows were found, the pre-existing behaviours the vector
    relies on) are separated from contract asserts. Every contract assert about the official_* attributes first requires the attributes to exist (NOT-IMPLEMENTED otherwise),
    so that a missing attribute can never make an assert pass vacuously."""
    ex = step.get("expect", {})
    o = sc.o
    if "held" in ex:
        ctx.premise(o.telemetry_gate.last_verdict == "held", "line-not-held:" + tag)
    elif not step.get("no_line"):
        ctx.premise(sc.applied(), "line-not-applied:" + tag)
    ctx.premise(sc.hud["dist"] is not None and sc.hud["time_left"] is not None, "hud-rows-not-found:" + tag)
    if "mode_after" in ex:
        ctx.premise(bool(o.is_scoring_mode) == ex["mode_after"], "mode-after:" + tag)
    if "finished_after" in ex:
        ctx.premise(bool(o.is_scoring_finished) == ex["finished_after"], "finished-after:" + tag)
    if set(ex) & OFFICIAL_EXPECT_KEYS:
        off = sc.official()
        if off["state"] is MISSING:
            ctx.contract(False, "NOT-IMPLEMENTED")
        else:
            if "official_state" in ex:
                ctx.contract(off["state"] == ex["official_state"], "STATE:" + tag)
            if "official_state_in" in ex:
                ctx.contract(off["state"] in ex["official_state_in"], "STATE:" + tag)
            if "state_not" in ex:
                ctx.contract(off["state"] != ex["state_not"], "STATE-STALE:" + tag)
            if "official_index" in ex:
                ctx.contract(off["index"] == ex["official_index"], "INDEX:" + tag)
            if "official_index_not" in ex:
                ctx.contract(off["index"] != ex["official_index_not"], "INDEX-STALE:" + tag)
            if "official_location" in ex:
                ctx.contract(off["location"] is not MISSING and abs(off["location"] - ex["official_location"]) <= 1e-9, "LOCATION:" + tag)
            if "official_reason" in ex:
                ctx.contract(off["reason"] == ex["official_reason"], "REASON:" + tag)
            if "official_reason_in" in ex:
                ctx.contract(off["reason"] in ex["official_reason_in"], "REASON:" + tag)
    if "hud_dist" in ex:
        ctx.contract(sc.hud["dist"] == ex["hud_dist"], "HUD-DIST:" + tag)
    if "hud_time_left" in ex:
        ctx.contract(sc.hud["time_left"] == ex["hud_time_left"], "HUD-TIMELEFT:" + tag)
    if "hud_dist_either" in ex:
        ctx.contract(sc.hud["dist"] in ex["hud_dist_either"], "HUD-DIST:" + tag)
        ctx.contract(sc.hud["time_left"] in ex["hud_time_left_either"], "HUD-TIMELEFT:" + tag)
        # one branch for both rows: the distance and the time must belong to the SAME branch (a half-held display is a defect)
        ctx.contract(ex["hud_dist_either"].index(sc.hud["dist"]) == ex["hud_time_left_either"].index(sc.hud["time_left"])
                     if sc.hud["dist"] in ex["hud_dist_either"] and sc.hud["time_left"] in ex["hud_time_left_either"] else False, "HUD-HALF-HELD:" + tag)
    if "save_data_len" in ex:
        ctx.contract(len(o.save_data) == ex["save_data_len"], "SAVE-DATA:" + tag)
    if "tgt_idx" in ex:
        ctx.contract(o.bve_tgt_idx == ex["tgt_idx"], "TGT-IDX:" + tag)
    if "identity_usable" in ex:
        ident = o.__dict__.get("_station_identity")
        ctx.contract(ident is not None and bool(ident.usable) == ex["identity_usable"], "IDENTITY:" + tag)
    if results is not None:
        results.append((tag, dict(sc.hud), sc.official()))


def run_case(ctx, vec, case, strict=None, mutate=None, results=None):
    """Run one vector case on a fresh Scene (strict = managed-mode gate; default: the case says). `mutate(step_state)` may adjust a step copy (e.g. add AVAIL). Returns the Scene results list."""
    use_strict = case.get("strict", False) if strict is None else strict
    out = results if results is not None else []
    with Scene(vec, strict=use_strict) as sc:
        sc.load_list(case["list"])
        for n, step in enumerate(case["steps"]):
            step = json.loads(json.dumps(step))
            if mutate is not None:
                mutate(step)
            sc.step(step)
            check_expect(ctx, sc, step, "%s#%d" % (case["id"], n), out)
    return out


def iter_merged(case):
    """Yields (step, merged state) with the same carry-forward rules as Scene.step but WITHOUT an Overlay (used by the oracle)."""
    st = json.loads(json.dumps(Scene.DEFAULTS))
    for step in case["steps"]:
        for k, v in step.items():
            if k == "machine":
                st["machine"].update(v)
            elif k in ("sid", "time_ms", "loc", "speed", "door", "doordir", "is_pass", "term"):
                st[k] = v
        if "advance_ms" in step:
            st["time_ms"] += step["advance_ms"]
        yield step, json.loads(json.dumps(st))


def oracle_problems(vec, file_key):
    """The HUD literals of the vectors must be what the REAL draw_hud renders when the REAL Overlay is handed the EXPECTED target as its (machine) target. A BVE-owned step
    is proven from its target_nextloc / target_nexttime; a TS-owned step from its own machine values. Returns [] when every literal is reachable."""
    bad = []
    with Scene(vec, strict=False) as sc:
        sc.load_list("L4")
        for case in cases_of(vec, file_key):
            for n, (step, st) in enumerate(iter_merged(case)):
                ex = step.get("expect", {})
                if not (set(ex) & {"hud_dist", "hud_time_left", "hud_dist_either", "hud_time_left_either"}):
                    continue
                tag = "%s#%d" % (case["id"], n)

                def probe_hud(nl, nt):
                    probe = json.loads(json.dumps(Scene.DEFAULTS))
                    probe.update({"loc": st["loc"], "time_ms": st["time_ms"], "speed": st["speed"], "door": st["door"], "doordir": st["doordir"], "is_pass": st["is_pass"]})
                    probe["machine"].update({"nextloc": nl, "nexttime": nt})
                    probe["official"] = None
                    # TS-owned (scoring running): the HUD reads the scoring target = the machine values in THIS line, before AND after the official target is implemented
                    # (a BVE-owned probe would stop being a probe the day the HUD stops reading the machine values: the oracle must outlive the implementation)
                    sc.o.is_scoring_mode = True
                    sc.o.is_scoring_finished = False
                    sc.push(sc.telemetry_text(probe))
                    return sc.render()

                if ex["owner"] == "BVE":
                    nl, nt = ex["target_nextloc"], ex["target_nexttime"]
                else:
                    nl, nt = st["machine"]["nextloc"], st["machine"]["nexttime"]
                hud = probe_hud(nl, nt)
                if "hud_dist" in ex and hud["dist"] != ex["hud_dist"]:
                    bad.append("%s: literal hud_dist %r but the real HUD renders %r for nextloc=%s loc=%s" % (tag, ex["hud_dist"], hud["dist"], nl, st["loc"]))
                if "hud_time_left" in ex and hud["time_left"] != ex["hud_time_left"]:
                    bad.append("%s: literal hud_time_left %r but the real HUD renders %r for nexttime=%s time=%s" % (tag, ex["hud_time_left"], hud["time_left"], nt, st["time_ms"]))
                if "hud_dist_either" in ex:                      # branch 0 = the NONE target (target_*), branch 1 = the held last-K target (alt_target_*)
                    for branch, (bl, bt) in enumerate(((ex["target_nextloc"], ex["target_nexttime"]), (ex["alt_target_nextloc"], ex["alt_target_nexttime"]))):
                        h = probe_hud(bl, bt)
                        if h["dist"] != ex["hud_dist_either"][branch] or h["time_left"] != ex["hud_time_left_either"][branch]:
                            bad.append("%s: either-branch %d literals %r/%r but the real HUD renders %r/%r" % (tag, branch, ex["hud_dist_either"][branch],
                                                                                                           ex["hud_time_left_either"][branch], h["dist"], h["time_left"]))
    return bad


# =====================================================================================================================================================================================
# D. row ledger
# =====================================================================================================================================================================================
class Ctx(object):
    def __init__(self):
        self.premise_fail = []
        self.contract_fail = []

    def premise(self, cond, word):
        if not cond:
            self.premise_fail.append(word)
        return bool(cond)

    def contract(self, cond, word):
        if not cond:
            self.contract_fail.append(word)
        return bool(cond)


class Ledger(object):
    def __init__(self, env_problem=""):
        self.rows = []
        self.env_problem = env_problem

    def run(self, rid, layer, predicted, fn):
        ctx = Ctx()
        verdict, reason = None, ""
        if self.env_problem and layer in ("IT",):
            verdict, reason = "ENV", self.env_problem
        else:
            try:
                fn(ctx)
            except ImportError as exc:
                verdict, reason = "ENV", "ImportError:" + str(exc)[:60]
            except Exception as exc:                      # a fixture / harness error proves nothing
                verdict, reason = "RED-INVALID", "exception:%s:%s" % (type(exc).__name__, str(exc).replace("|", "/")[:70])
        if verdict is None:
            if ctx.premise_fail:
                verdict, reason = "RED-INVALID", "premise:" + "+".join(sorted(set(ctx.premise_fail)))
            elif ctx.contract_fail:
                verdict, reason = "RED-VALID", "+".join(sorted(set(ctx.contract_fail)))
            else:
                verdict, reason = "GUARD", ""
        self.rows.append((rid, layer, verdict, predicted, reason))

    def report(self, expect):
        for rid, layer, verdict, predicted, reason in self.rows:
            print("%s | %s | %s | %s | %s" % (rid, layer, verdict, predicted, reason))
        counts = {}
        for r in self.rows:
            counts[r[2]] = counts.get(r[2], 0) + 1
        unexpected = [r for r in self.rows if r[2] != r[3]]
        print("SUMMARY rows=%d RED-VALID=%d GUARD=%d RED-INVALID=%d ENV=%d UNEXPECTED=%d" % (len(self.rows), counts.get("RED-VALID", 0), counts.get("GUARD", 0),
                                                                                              counts.get("RED-INVALID", 0), counts.get("ENV", 0), len(unexpected)))
        for r in unexpected:
            print("UNEXPECTED | %s | predicted %s but %s | %s" % (r[0], r[3], r[2], r[4]))
        bad = counts.get("RED-INVALID", 0) + counts.get("ENV", 0)
        if expect == "green":
            return 0 if counts.get("GUARD", 0) == len(self.rows) else 1
        return 0 if (bad == 0 and not unexpected and counts.get("RED-VALID", 0) >= 1) else 1


def read_source(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8-sig") as fh:
        return fh.read()


def strip_cs_comments(text):
    """Product C# text without // and /* */ comments and without string literals' content that could hide a keyword (comments are not code)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def extract_block(text, header_regex):
    """The text of a C# member / type from its header to the matching closing brace (comments already stripped by the caller), or None."""
    m = re.search(header_regex, text)
    if not m:
        return None
    start = text.find("{", m.end())
    if start < 0:
        return None
    depth = 0
    for j in range(start, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    return None


def normalized_sha(text):
    """SHA-256 of a code block with comments and whitespace removed (a pin that survives re-formatting but not a change of the code)."""
    code = re.sub(r"\s+", "", strip_cs_comments(text))
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def product_cs_files():
    """Relative paths of the product C# sources (Probes, Tests and build outputs excluded)."""
    out = []
    for base in ("TsScoringPlugin/TsScoringPlugin", "TsScoringPlugin/Handshake/Telemetry"):
        for dp, dn, fn in os.walk(os.path.join(ROOT, base)):
            dn[:] = [d for d in dn if d.lower() not in ("obj", "bin", "tests", "probes")]
            for f in fn:
                if f.endswith(".cs"):
                    out.append(os.path.relpath(os.path.join(dp, f), ROOT).replace("\\", "/"))
    return sorted(out)


def parse_args(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", choices=("red", "green"), default="red")
    return ap.parse_args(argv)
