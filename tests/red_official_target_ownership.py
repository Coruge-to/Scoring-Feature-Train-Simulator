"""Phase SI-R2.1 (T-1a) - RED ledger of the OWNERSHIP of the displayed target (an executable specification index; NOT a discoverable unit test: the file name does not start with test_).

Usage:   python -B tests/red_official_target_ownership.py [--expect red|green]      (the IT rows need PyQt6: do NOT use `python -I`, which hides it; the rows then report ENV)

THE OWNERSHIP RULE (decided; the same expression is already used at 7 places of the application):
        target_owner_is_scoring = is_scoring_mode and not is_scoring_finished
  * owner == TS  (scoring running): the HUD and the scoring keep the SCORING target (the machine target the C# state machine holds: B2/B3 operational-stop hold, MISSED hold, terminal hold).
    The official target keeps being received but is not read by the HUD / scoring.
  * owner == BVE (scoring off, or finished): the HUD shows the OFFICIAL target and nothing else. When there is no valid official target (terminal none, no target, temporarily
    unavailable, read failed, part absent, scope / location mismatch, not initialised) the HUD shows NONE ("--- m", "--:--"); it never falls back to the machine target, a distance,
    the nearest station, a 50 m / 100 m search or the old scoring target (R-FB-01, R-HUD-NONE-1..5). A negative remaining time of an old terminal (-00:57 after F5) is a defect.
  * the remaining time of the official target is derived in Python (running: arrival time; stopped with the doors open: departure time; pass: arrival time; terminal: the difference
    of the first door-open Tick is frozen and re-initialised by a generation change). NEXTTIME == 0 is none (the existing '> 0' contract).

NOTE (Owner contract RED): the ownership transitions and the HUD-after-F5 behaviour were not observed on a real machine in this form; these rows are contract REDs fixed by the Owner's
decisions (D-5 / D-7 / E-11 / E-13 and the SI-R2 entry contract), not observations. The expected texts are literals of tests/official_target_vectors.json, proven reachable by the
oracle row FIX-ORACLE-OWNERSHIP against the REAL draw_hud.

One row per id: `ID | layer | verdict | predicted | reason`. Exit code as in the sibling runners.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import official_target_wire_fixture as F  # noqa: E402

LEGACY_AVAIL = ["time", "speed", "loc", "grad", "station", "door"]
# tokens that may not steer the identification of the official target (D-7 C-2): the BVE version, the landing error. (The doors are read by the NEXTTIME derivation on purpose: not here.)
FORBIDDEN_IN_OFFICIAL = re.compile(r"(?i)\bbve[\s_]?[56]\b|bve_?version|host_?version|\blanding|touchdown|TerminalDepartureTime")
FORBIDDEN_IN_HELPER = re.compile(r"(?i)\bbve[\s_]?[56]\b|TerminalDepartureTime|AreAllClosed|\bDoors?\b|landing|touchdown|SpeedMeterPerSecond")


def oracle_huds(vec, case):
    """The HUD the REAL application draws when it is handed the expected target as its machine target (the C# NEXTLOC / NEXTTIME vector) for every step of `case`."""
    out = []
    with F.Scene(vec, strict=False) as sc:
        sc.load_list("L4")
        for step, st in F.iter_merged(case):
            ex = step.get("expect", {})
            nl = ex.get("target_nextloc", st["machine"]["nextloc"])
            nt = ex.get("target_nexttime", st["machine"]["nexttime"])
            probe = {"sid": st["sid"], "time_ms": st["time_ms"], "loc": st["loc"], "speed": st["speed"], "door": st["door"], "doordir": st["doordir"], "is_pass": st["is_pass"],
                     "term": st["term"], "machine": {"nextloc": nl, "nexttime": nt, "tgt": -1, "arr": -1, "seq": 0}, "official": None}
            sc.o.is_scoring_mode = True            # TS-owned: the HUD reads the machine values of this line before AND after the official target is implemented
            sc.o.is_scoring_finished = False
            sc.push(sc.telemetry_text(probe))
            h = sc.render()
            out.append((h["dist"], h["time_left"]))
    return out


def main(argv):
    args = F.parse_args(argv)
    vec = F.load_vectors()
    env = F.harness_init()
    L = F.Ledger(env)

    def case_row(rid, layer, predicted, ids, extra=None):
        def fn(ctx):
            results = []
            for cid in ids:
                F.run_case(ctx, vec, F.case_by_id(vec, cid), results=results)
            if extra is not None:
                extra(ctx, results)
        L.run(rid, layer, predicted, fn)

    # ---- the fixture itself ----------------------------------------------------------------------------------------------------------------------------------------
    L.run("FIX-SCHEMA", "Py", "GUARD", lambda c: c.premise(not F.vector_problems(vec), "vector-schema:" + ";".join(F.vector_problems(vec))[:120]))
    L.run("FIX-ORACLE-OWNERSHIP", "IT", "GUARD", lambda c: c.premise(not F.oracle_problems(vec, "ownership"), "hud-literal:" + ";".join(F.oracle_problems(vec, "ownership"))[:160]))

    # ---- B. ownership ------------------------------------------------------------------------------------------------------------------------------------------------
    case_row("R-OWN-01", "IT", "RED-VALID", ["OWN-01"])
    case_row("R-OWN-02", "IT", "GUARD", ["OWN-02"])
    case_row("R-OWN-03", "IT", "RED-VALID", ["OWN-03"])
    case_row("R-OWN-04", "IT", "RED-VALID", ["OWN-04"])
    case_row("R-OWN-05", "IT", "GUARD", ["OWN-05"])
    case_row("R-OWN-06", "IT", "RED-VALID", ["OWN-06"])
    case_row("R-OWN-07", "IT", "GUARD", ["OWN-07"])
    case_row("R-OP-01", "IT", "RED-VALID", ["OP-01"])
    case_row("R-OP-02", "IT", "RED-VALID", ["OP-02"])
    case_row("R-OP-03", "IT", "GUARD", ["OP-03"])
    case_row("R-OP-04", "IT", "GUARD", ["OP-04"])

    # ---- NEXTTIME: the Python derivation of the remaining time of the official target ------------------------------------------------------------------------------
    case_row("R-NT-01", "IT", "RED-VALID", ["NT-01"])
    case_row("R-NT-02", "IT", "RED-VALID", ["NT-02"])
    case_row("R-NT-03", "IT", "RED-VALID", ["NT-03"])
    case_row("R-NT-04", "IT", "RED-VALID", ["NT-04"])
    case_row("R-NT-NONE", "IT", "RED-VALID", ["NT-ZERO", "TERM-1"])
    case_row("R-NT-POS", "IT", "RED-VALID", ["NT-POS"])
    case_row("R-NT-04-GEN", "IT", "RED-VALID", ["NT-04-GEN"])

    def nt_eq(ctx):
        # EQUIVALENCE with the C# NEXTTIME: the HUD the official path draws must equal the HUD the REAL application draws for the C# vector (the expected target as machine values).
        ids = ["NT-01", "NT-02", "NT-03", "NT-04"]
        expected = {cid: oracle_huds(vec, F.case_by_id(vec, cid)) for cid in ids}
        for cid in ids:
            results = []
            F.run_case(ctx, vec, F.case_by_id(vec, cid), results=results)
            got = [(r[1]["dist"], r[1]["time_left"]) for r in results]
            ctx.contract(got == expected[cid], "NOT-EQUIVALENT-TO-CSHARP:" + cid)
    L.run("R-NT-EQ", "IT", "RED-VALID", nt_eq)

    # ---- semantics / terminal ----------------------------------------------------------------------------------------------------------------------------------------
    def sem01(ctx):
        flavours = {
            "current": dict(strict=False, mutate=None),
            "legacy": dict(strict=False, mutate=lambda step: step.__setitem__("avail", LEGACY_AVAIL)),
            "managed": dict(strict=True, mutate=None),
        }
        seen = {}
        for name, kw in flavours.items():
            results = []
            F.run_case(ctx, vec, F.case_by_id(vec, "SUP-SEM"), strict=kw["strict"], mutate=kw["mutate"], results=results)
            seen[name] = [(r[2]["state"], r[2]["index"]) for r in results if r[2]["state"] is not F.MISSING]
        if all(seen.values()):
            ctx.contract(seen["current"] == seen["legacy"] == seen["managed"], "MODES-DIFFER")
    L.run("R-SEM-01", "IT", "RED-VALID", sem01)
    case_row("R-SEM-02", "IT", "RED-VALID", ["SEM-02"])
    case_row("R-TERM-1", "IT", "RED-VALID", ["TERM-1"])
    case_row("R-TERM-2", "IT", "RED-VALID", ["TERM-2"])

    # ---- D. HUD NONE slice (R-HUD-NONE-1..5) -----------------------------------------------------------------------------------------------------------------------------
    case_row("R-HUD-NONE-1", "IT", "RED-VALID", ["HUD-NONE-1"])
    case_row("R-HUD-NONE-2", "IT", "RED-VALID", ["HUD-NONE-2"])
    case_row("R-HUD-NONE-3", "IT", "RED-VALID", ["HUD-NONE-3"])
    case_row("R-HUD-NONE-4", "IT", "RED-VALID", ["HUD-NONE-4"])
    case_row("R-HUD-NONE-5", "IT", "RED-VALID", ["HUD-NONE-5"])
    # last-known (the sixth meaning of the HUD NONE slice, which the Stage 0 id list has no number for): a held value never crosses a generation and is never kept for a terminal none /
    # a read failure / a missing part. How long a U may keep the last K INSIDE one scope is the Owner's open number (E-11, N): R-STATE-3 accepts both answers.
    case_row("R-HUD-NONE-6", "IT", "RED-VALID", ["LK-GEN", "LK-T", "SUP-F-AFTER-K", "SUP-ABSENT"])
    case_row("R-FB-01", "IT", "RED-VALID", ["FB-01"])

    # ---- E. D-7 C-2: no compensation of the BVE5 / BVE6 difference in the official-target processing --------------------------------------------------------------
    def nocomp1(ctx):
        cur = F.strip_cs_comments(F.read_source("TsScoringPlugin/TsScoringPlugin/Class1.cs"))
        # the scope of the pin is limited to the NEW official-target processing: the existing BVE5 / BVE6 terminal sentinel normalisation (departure time 't') is outside it on purpose
        ctx.premise("TerminalDepartureTimeBve5Ms" in cur, "existing-sentinel-not-found(scope-premise)")
        ctx.premise(not [k for k in vec["cases"] if any(w in str(k).lower() for w in ("bve5_only", "bve6_only", "host_version"))], "vectors-carry-a-version")
        py = os.path.join(F.ROOT, F.PY_MODULE + ".py")
        if os.path.exists(py):
            hits = FORBIDDEN_IN_OFFICIAL.findall(F.read_source(F.PY_MODULE + ".py"))
            ctx.contract(not hits, "VERSION-OR-LANDING-BRANCH-IN-PY:" + ",".join(sorted(set(hits)))[:60])
        shared = F.strip_cs_comments(F.read_source("TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs"))
        block = F.extract_block(shared, r"class\s+" + F.HELPER_NAME)
        if block is not None:
            hits = FORBIDDEN_IN_HELPER.findall(block)
            ctx.contract(not hits, "VERSION-OR-DOOR-BRANCH-IN-HELPER:" + ",".join(sorted(set(h if isinstance(h, str) else h[0] for h in hits)))[:60])
    L.run("R-NOCOMP-1", "SRC", "GUARD", nocomp1)

    def nocomp2(ctx):
        # the SAME processing (one function, no per-case arguments) for the BVE6 observation (3 -> 3, 570.00 -> 570.04) and the BVE5 observation (3 -> 2, 570.00 -> 570.00)
        for cid in ("NOCOMP-E1D", "NOCOMP-E2D"):
            F.run_case(ctx, vec, F.case_by_id(vec, cid))
    L.run("R-NOCOMP-2", "IT", "RED-VALID", nocomp2)

    left = F.harness_leftovers()
    L.run("FIX-NO-PROFILE-WRITE", "Py", "GUARD", lambda c: c.premise(not left, "profile-written:" + ",".join(left)[:80]))
    return L.report(args.expect)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
