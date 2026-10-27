"""Phase SI-R2.1 (T-1a) - RED ledger of the SUPPLY of the official BVE target (an executable specification index; NOT a discoverable unit test: the file name does not start with test_).

Usage:   python -B tests/red_official_target_supply.py [--expect red|green]      (the IT rows need PyQt6: do NOT use `python -I`, which hides it; the rows then report ENV)

Contract (Owner decisions SI-R2.1 / D-7 / E-10 / E-11 / E-13): the host's official next-station target (Conductor.Stations.CurrentIndex + 1) is supplied to the application by a new
telemetry part; the application derives ONE of
    KNOWN (K) / NONE_TERMINAL (T) / NONE_EMPTY (N) / UNAVAILABLE (U) / READ_FAILED (F)          from the wire
    ABSENT / INVALID / NOT_INITIALIZED                                                          derived by the application
NONE = NONE_TERMINAL or NONE_EMPTY (not a wire token). U and F are never confused with NONE or with each other; the last K is never replayed for them (E11-F3).
The machine target (NEXTLOC / NEXTTIME / STIDX tgt) is untouched and the official value is never written into bve_next_* / bve_tgt_idx / bve_arr_idx (R-OFF-09/10).

Nothing of this is implemented yet: every row that reads an official_* attribute reports RED-VALID with the reason word NOT-IMPLEMENTED. The wire format is PROVISIONAL (E-10, section A of
tests/official_target_wire_fixture.py). The expected values are literals of tests/official_target_vectors.json; this file contains no copy of any product processing.

One row per id: `ID | layer | verdict | predicted | reason`. Exit code: --expect red -> 0 when no row is RED-INVALID / ENV / UNEXPECTED and at least one is RED-VALID; --expect green -> 0 when every row is GUARD.
"""
import os
import re
import sys
import time
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import official_target_wire_fixture as F  # noqa: E402


class FakeWallClock(object):
    """Patches the module-level clock functions of `time` for the grace row (R-OFF-07), so that the 3,000 ms grace is a fact about the data, not about the speed of this machine."""

    def __init__(self):
        self.now = 1000.0
        self._patches = []

    def __enter__(self):
        for name in ("time", "monotonic", "perf_counter"):
            p = mock.patch.object(time, name, lambda: self.now)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        return False


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

    # ---- the fixture itself -------------------------------------------------------------------------------------------------------------------------------------------
    L.run("FIX-SCHEMA", "Py", "GUARD", lambda c: c.premise(not F.vector_problems(vec), "vector-schema:" + ";".join(F.vector_problems(vec))[:120]))
    L.run("FIX-WIRE-ROUNDTRIP", "Py", "GUARD", lambda c: c.premise(not F.wire_roundtrip_problems(vec), "wire-roundtrip:" + ";".join(F.wire_roundtrip_problems(vec))[:120]))
    L.run("FIX-ORACLE-SUPPLY", "IT", "GUARD", lambda c: c.premise(not F.oracle_problems(vec, "supply"), "hud-literal:" + ";".join(F.oracle_problems(vec, "supply"))[:160]))

    # ---- A. supply: the five wire states and the application's three derived states ------------------------------------------------------------------------------
    case_row("R-OFF-01", "IT", "RED-VALID", ["SUP-K"])

    def distinct_states(ctx, results):
        states = [r[2]["state"] for r in results if r[2]["state"] is not F.MISSING]
        if states:
            ctx.contract(len(set(states)) == len(states), "STATES-NOT-DISTINCT")

    case_row("R-OFF-02", "IT", "RED-VALID", ["SUP-K", "SUP-T", "SUP-N", "SUP-U", "SUP-F"], distinct_states)
    def none_class(ctx, results):
        # E-11: NONE (= T or N) is a semantic class of the application, NOT a wire token: the wire has five words and 'NONE' is not one of them (SUP-MALFORMED refuses it)
        ctx.premise("NONE" not in F.STATE_WORDS and set(F.NONE_CLASS) == {F.WIRE_TO_STATE["T"], F.WIRE_TO_STATE["N"]}, "none-class-definition")
        states = [r[2]["state"] for r in results if r[2]["state"] is not F.MISSING]
        if states:
            ctx.contract(all(s in F.NONE_CLASS for s in states) and len(set(states)) == 2, "NONE-CLASS")
    case_row("R-OFF-NONE", "IT", "RED-VALID", ["SUP-T", "SUP-N"], none_class)
    case_row("R-OFF-03", "IT", "RED-VALID", ["SUP-ABSENT"])

    def off04(ctx):
        F.run_case(ctx, vec, F.case_by_id(vec, "SUP-GEN"))
        # the reset itself (the epoch reset of the strict gate calls exactly this method before the first line of a new instance is applied)
        with F.Scene(vec, strict=False) as sc:
            sc.load_list("L5")
            sc.step({"loc": 2500.0, "machine": {"nextloc": 3000.0, "nexttime": 36660000, "tgt": 3}, "official": {"state": "K", "index": 3}})
            ctx.premise(hasattr(sc.o, "reset_telemetry_state"), "reset_telemetry_state-missing")
            sc.o.reset_telemetry_state()
            off = sc.official()
            if off["state"] is F.MISSING:
                ctx.contract(False, "NOT-IMPLEMENTED")
            else:
                ctx.contract(off["state"] == "NOT_INITIALIZED" and off["index"] == -1, "RESET-NOT-NOT_INITIALIZED")
    L.run("R-OFF-04", "IT", "RED-VALID", off04)

    case_row("R-OFF-05", "IT", "RED-VALID", ["SUP-RANGE"])
    case_row("R-OFF-06", "IT", "RED-VALID", ["SUP-LOC"])

    def off07(ctx):
        with FakeWallClock() as clock:
            for cid in ("SUP-LISTMM-HASH", "SUP-LISTMM-COUNT"):
                case = F.case_by_id(vec, cid)
                with F.Scene(vec, strict=False) as sc:
                    sc.load_list(case["list"])
                    for n, step in enumerate(case["steps"]):
                        clock.now += step.get("advance_ms", 0) / 1000.0
                        sc.rig.clock.now += step.get("advance_ms", 0) / 1000.0
                        sc.step(step)
                        F.check_expect(ctx, sc, step, "%s#%d" % (cid, n))
    L.run("R-OFF-07", "IT", "RED-VALID", off07)
    case_row("R-OFF-08", "IT", "RED-VALID", ["SUP-MALFORMED", "SUP-VERSION"])

    def off09(ctx):
        path = os.path.join(F.HERE, "stidx_vectors_st0.json")
        ctx.premise(os.path.exists(path), "stidx-vectors-missing")
        ctx.contract(F.sha256_file(path) == vec["pins"]["stidx_vectors_st0.json"], "STIDX-VECTORS-CHANGED")
        F.run_case(ctx, vec, F.case_by_id(vec, "SUP-STIDX-GUARD"))
    L.run("R-OFF-09", "IT", "GUARD", off09)

    def off10(ctx):
        counts = {}
        for rel in ("main.py", "network.py"):
            text = F.read_source(rel)
            counts[rel] = len(re.findall(r"self\.bve_next_loc\s*=[^=]", text))
        ctx.premise(counts == {"main.py": 2, "network.py": 1}, "bve_next_loc-baseline-moved:%s" % counts)
        # the official value is never assigned into the machine mirrors (a source reading of every assignment to them)
        bad = []
        for rel in ("main.py", "telemetry_contract.py", "scoring_logic.py", "hud_ui.py", "managed_input.py"):
            if not os.path.exists(os.path.join(F.ROOT, rel)):
                continue
            for m in re.finditer(r"self\.(bve_next_loc|bve_next_time|bve_tgt_idx|bve_arr_idx)\s*=[^=][^\n]*", F.read_source(rel)):
                if "official" in m.group(0):
                    bad.append(rel + ":" + m.group(1))
        ctx.contract(not bad, "OFFICIAL-WRITTEN-INTO-MACHINE:" + ",".join(bad))
    L.run("R-OFF-10", "SRC", "GUARD", off10)

    # ---- the C# side as a source reading (no compilation: R-CS-FIX is a later Substage) ---------------------------------------------------------------------
    cs_files = F.product_cs_files()
    texts = {rel: F.strip_cs_comments(F.read_source(rel)) for rel in cs_files}
    shared = "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs"
    current = "TsScoringPlugin/TsScoringPlugin/Class1.cs"
    legacy_session = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs"

    def premise_sources(ctx):
        ctx.premise(all(p in texts for p in (shared, current, legacy_session)), "product-cs-files-missing")

    def src01(ctx):
        premise_sources(ctx)
        ctx.contract(F.PART_NAME in texts[shared] and F.HELPER_NAME in texts[shared], "NOT-IMPLEMENTED:helper-in-shared")
        ctx.contract(F.HELPER_NAME in texts[current], "NOT-IMPLEMENTED:current-calls-helper")
        ctx.contract(F.HELPER_NAME in texts[legacy_session] or any(F.HELPER_NAME in t for r, t in texts.items() if "/Legacy/src/" in r), "NOT-IMPLEMENTED:legacy-calls-helper")
    L.run("R-CS-SRC-01", "SRC", "RED-VALID", src01)

    def src02(ctx):
        premise_sources(ctx)
        block = F.extract_block(texts[shared], r"class\s+" + F.HELPER_NAME) if F.HELPER_NAME in texts[shared] else None
        if block is None:
            ctx.contract(False, "NOT-IMPLEMENTED:helper-absent")
            return
        words = set(re.findall(r'"([KTNUF])"', block)) | set(re.findall(r"'([KTNUF])'", block))
        ctx.contract(words == set(F.STATE_WORDS), "STATE-WORDS:%s" % "".join(sorted(words)))
    L.run("R-CS-SRC-02", "SRC", "RED-VALID", src02)

    def src03(ctx):
        premise_sources(ctx)
        hits = []
        for rel, text in texts.items():
            for pat in (r"GoToByIndex", r"\.GoTo\(", r"\bCurrentIndex\s*=(?!=)"):
                if re.search(pat, text):
                    hits.append("%s:%s" % (os.path.basename(rel), pat))
        ctx.contract(not hits, "HOST-WRITE:" + ",".join(hits))
    L.run("R-CS-SRC-03", "SRC", "GUARD", src03)

    def src04(ctx):
        premise_sources(ctx)
        text = texts[current]
        i = text.find(F.HELPER_NAME)
        if i < 0:
            ctx.contract(False, "NOT-IMPLEMENTED:no-official-part-in-current")
            return
        window = text[max(0, i - 600):i + 900]
        ctx.contract(re.search(r"\btry\b", window) is not None and re.search(r"\bcatch\b", window) is not None, "NO-INDEPENDENT-TRY")
        ctx.contract('"F"' in window or "'F'" in window, "NO-F-ON-FAILURE")
    L.run("R-CS-SRC-04", "SRC", "RED-VALID", src04)

    def src05(ctx):
        premise_sources(ctx)
        hits = [os.path.basename(r) for r, t in texts.items() if re.search(r"is_scoring_mode|is_scoring_finished|scoring_active", t)]
        ctx.contract(not hits, "C#-KNOWS-SCORING:" + ",".join(hits))
    L.run("R-CS-SRC-05", "SRC", "GUARD", src05)

    def src06(ctx):
        premise_sources(ctx)
        ctx.contract('data += ",STIDX:1:" + TSScoringPlugin.Telemetry.StationIndexWire.Fields(stidxTarget, stidxArrivalIndex, stidxArrivalSeq, stidxListCount, stidxListId);' in texts[current], "STIDX-APPEND-CHANGED")
    L.run("R-CS-SRC-06", "SRC", "GUARD", src06)

    def src07(ctx):
        api_text = F.strip_cs_comments(F.read_source("TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs"))
        fake_text = F.strip_cs_comments(F.read_source("TsScoringPlugin/Handshake/Tests/TelemetryTestFixture.cs"))
        api = F.extract_block(api_text, r"internal\s+interface\s+ILegacyApi")
        fake = F.extract_block(fake_text, r"public\s+class\s+FakeApi\s*:\s*ILegacyApi")
        ctx.premise(api is not None and fake is not None, "legacy-api-blocks-not-found")
        if api is not None:
            ctx.contract(F.normalized_sha(api) == vec["pins"]["ILegacyApi_block_normalized"], "ILegacyApi-CHANGED")
        if fake is not None:
            ctx.contract(F.normalized_sha(fake) == vec["pins"]["FakeApi_block_normalized"], "FakeApi-CHANGED")
    L.run("R-CS-SRC-07", "SRC", "GUARD", src07)

    def src08(ctx):
        premise_sources(ctx)
        text = texts[current]
        i = text.find(F.HELPER_NAME)
        j = text.find("StationIndexWire.Fields(")
        ctx.premise(j >= 0, "stidx-append-missing")
        if i < 0:
            ctx.contract(False, "NOT-IMPLEMENTED:no-official-part-in-current")
            return
        # the official part is written under the same condition as STIDX: both appends lie in the same if-block (no closing brace between them)
        lo, hi = min(i, j), max(i, j)
        ctx.contract("}" not in text[lo:hi].split(";", 1)[-1].replace("StationIndexWire", ""), "NOT-UNDER-THE-STIDX-CONDITION")
    L.run("R-CS-SRC-08", "SRC", "RED-VALID", src08)

    # ---- R-STATE-1..4: the meaning is told apart by diagnostic words ----------------------------------------------------------------------------------------------
    case_row("R-STATE-1", "IT", "RED-VALID", ["SUP-K"])
    case_row("R-STATE-2", "IT", "RED-VALID", ["SUP-T"])
    case_row("R-STATE-3", "IT", "RED-VALID", ["SUP-U-AFTER-K"])
    case_row("R-STATE-4", "IT", "RED-VALID", ["SUP-F-AFTER-K"])

    # ---- generation ------------------------------------------------------------------------------------------------------------------------------------------------
    case_row("R-GEN-1", "IT", "RED-VALID", ["SUP-REACQ"])
    case_row("R-GEN-2", "IT", "RED-VALID", ["SUP-N6"])

    # ---- E-13: the initial state -----------------------------------------------------------------------------------------------------------------------------------
    def init1(ctx):
        import telemetry_contract
        d = telemetry_contract.telemetry_state_defaults()
        ctx.contract(d.get("official_state") == "NOT_INITIALIZED" and d.get("official_index") == -1, "NOT-IMPLEMENTED:defaults-have-no-official")
        ctx.contract(F.PART_NAME in " ".join(sum((list(v) for v in telemetry_contract.TOKEN_KEYS.values()), [])), "NOT-IMPLEMENTED:token-keys-have-no-part")
    L.run("R-INIT-1", "Py", "RED-VALID", init1)

    def init2(ctx):
        with F.Scene(vec) as sc:
            o = sc.o
            ctx.premise(all(hasattr(o, a) for a in ("bve_next_loc", "bve_next_time", "bve_tgt_idx")), "initial-attrs-missing")
            ctx.contract((o.bve_next_loc, o.bve_next_time, o.bve_tgt_idx) == (-1.0, -1, -1), "INITIAL-NOT-BETA")
    L.run("R-INIT-2", "IT", "GUARD", init2)

    def init3(ctx):
        with F.Scene(vec) as sc:
            hud = sc.render()
            ctx.premise(hud["dist"] is not None and hud["time_left"] is not None, "hud-rows-not-found")
            ctx.contract(hud["dist"] == "--- m" and hud["time_left"] == "--:--", "STATION0-SHOWN-BEFORE-FIRST-VALUE")
    L.run("R-INIT-3", "IT", "GUARD", init3)

    def init7(ctx):
        # E-13 beta is safe for the SCORING side too: with NEXTLOC -1 / NEXTTIME -1 / STIDX tgt -1 (the machine target UNSET) a scoring tick neither raises nor scores
        import scoring_logic
        with F.Scene(vec) as sc:
            sc.load_list("L4")
            sc.step({"loc": 500.0, "machine": {"nextloc": -1.0, "nexttime": -1, "tgt": -1}})
            o = sc.o
            ctx.premise(sc.applied() and o.bve_next_loc == -1.0, "unset-line-not-applied")
            R = sc.R
            R.bind_identity(o, arr_idx=-1, tgt_idx=-1)
            o.is_scoring_mode, o.is_scoring_finished = True, False
            before = dict(o.score_details)
            t = 100.0
            for _ in range(4):
                t += 0.016
                scoring_logic.update_physics_and_scoring(o, t, 0.016)
            ctx.contract(dict(o.score_details) == before and o.bve_next_loc == -1.0, "SCORING-REACTS-TO-UNSET")
    L.run("R-INIT-7", "IT", "GUARD", init7)
    case_row("R-INIT-4", "IT", "RED-VALID", ["SUP-INIT-MACHINE-A"])

    def init5(ctx):
        import telemetry_contract
        d = telemetry_contract.telemetry_state_defaults()
        others = {F.WIRE_TO_STATE[w] for w in F.STATE_WORDS}
        ctx.contract(d.get("official_state") == "NOT_INITIALIZED" and d.get("official_state") not in others, "NOT-IMPLEMENTED:no-distinct-initial-state")
    L.run("R-INIT-5", "Py", "RED-VALID", init5)

    def init6(ctx):
        cur = texts[current]
        ctx.premise(current in texts, "class1-missing")
        ctx.contract(all(s in cur for s in ("int stidxTarget = -1;", "double nextStationLoc = -1;", "int nextStationTime = -1;")), "CURRENT-DEFAULTS-MOVED")
        leg = F.strip_cs_comments(F.read_source("TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs"))
        ctx.contract(all(s in leg for s in ("v.NextLoc = -1;", "v.NextTime = -1;", "v.Index = -1;")), "LEGACY-DEFAULTS-MOVED")
    L.run("R-INIT-6", "SRC", "GUARD", init6)

    left = F.harness_leftovers()
    L.run("FIX-NO-PROFILE-WRITE", "Py", "GUARD", lambda c: c.premise(not left, "profile-written:" + ",".join(left)[:80]))
    return L.report(args.expect)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
