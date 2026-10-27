"""Phase SI-R2.1 (T-1a) - RED ledger of the RE-INITIALISATION without a distance search (an executable specification index; NOT a discoverable unit test: the file name does not start with test_).

Usage:   python -B tests/red_official_target_reinit.py [--expect red|green]      (the IT rows need PyQt6: do NOT use `python -I`, which hides it; the rows then report ENV)

D-7 / OD-X2 (Owner, adopted): the start station is host-faithful, no d=0 exception is made, after F5 the official BVE target is RE-ACQUIRED, and the BVE5 / BVE6 difference is NOT
compensated by TS Scoring.  C-1: the old RP10A-4 / RP10A-13 REDs (expectations split by the distance d) are REPLACED by the rows R-REINIT-F5-* below.  C-2: the processing of the
official target is pinned to contain no version / landing branch (red_official_target_ownership.py R-NOCOMP-1/2).  C-3: when station 0 is an operational stop or a pass station, the
HUD outside the scoring may start at station 1 after an F5 at the start station (the host's own behaviour is accepted: R-REINIT-F5-START).

E-13 (beta): a re-initialisation that carries NO requested StationIndex (first Tick, scenario change, manual time jump, A0, a changed station count) leaves the MACHINE target UNSET
(Current: targetStationIndex = stationList.Count, Legacy: target = list.Count; NEXTLOC -1, NEXTTIME -1, STIDX tgt -1) and never chooses a station from the position.

The distance-independence rows use SYNTHETIC distances (9.5, 44.9, 49.99, 50.0, 50.1 m and 0.0 m before the target station): they are not observations (only the start-station d=0.00, the
E1-D / E2-D index sequences and the terminal-T behaviour were observed; R4b/R4c were not). The machine value in those vectors is arbitrary on purpose (equal to the official one for
9.5 / 44.9 / 49.99 m, deliberately another station at the 50 m window boundary): the HUD must follow the official target whatever the machine value is.

One row per id: `ID | layer | verdict | predicted | reason`. Exit code as in the sibling runners.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import official_target_wire_fixture as F  # noqa: E402

CURRENT = "TsScoringPlugin/TsScoringPlugin/Class1.cs"
LEGACY_TL = "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs"


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

    cs_files = F.product_cs_files()
    texts = {rel: F.strip_cs_comments(F.read_source(rel)) for rel in cs_files}

    def sources_present(ctx):
        return ctx.premise(CURRENT in texts and LEGACY_TL in texts, "product-cs-files-missing")

    # ---- the fixture itself -----------------------------------------------------------------------------------------------------------------------------------------
    L.run("FIX-SCHEMA", "Py", "GUARD", lambda c: c.premise(not F.vector_problems(vec), "vector-schema:" + ";".join(F.vector_problems(vec))[:120]))
    L.run("FIX-ORACLE-REINIT", "IT", "GUARD", lambda c: c.premise(not F.oracle_problems(vec, "reinit"), "hud-literal:" + ";".join(F.oracle_problems(vec, "reinit"))[:160]))

    # ---- A0 (an official Jump of the host outside the scoring) -------------------------------------------------------------------------------------------------------
    case_row("R-REINIT-A0-1", "IT", "RED-VALID", ["A0-1A", "A0-1B"])
    case_row("R-REINIT-A0-2", "IT", "RED-VALID", ["A0-2"])

    def a0_3(ctx, results):
        if not sources_present(ctx):
            return
        cur = texts[CURRENT]
        rhs = re.findall(r"\bnextStationLoc\s*=\s*([^;]+);", cur)
        ctx.premise(len(rhs) >= 2, "nextStationLoc-assignments-not-found")
        # the machine side follows ONE index: every assignment of NEXTLOC is the declaration default or the location of the station the target index selects
        ctx.contract(all(r.strip() in ("-1", "-1.0", "targetSt.Location") for r in rhs), "NEXTLOC-NOT-FROM-ONE-INDEX:%s" % sorted(set(r.strip() for r in rhs)))
    case_row("R-REINIT-A0-3", "IT", "RED-VALID", ["A0-3"], a0_3)

    def a0_4(ctx):
        if not sources_present(ctx):
            return
        ctx.contract(re.search(r"\btargetStationIndex\s*=\s*stationList\.Count\b", texts[CURRENT]) is not None, "CURRENT-NO-list.Count-UNSET")
        ctx.contract(re.search(r"\btarget\s*=\s*list\.Count\b", texts[LEGACY_TL]) is not None, "LEGACY-NO-list.Count-UNSET")
    L.run("R-REINIT-A0-4", "SRC", "RED-VALID", a0_4)

    def unset(ctx):
        if not sources_present(ctx):
            return
        cur = texts[CURRENT]
        ctx.premise("SelectTargetByRequestedIndex" in cur, "p1-selector-missing")
        ctx.contract("SelectTargetByPosition" not in cur, "CURRENT-REINIT-CHOOSES-BY-POSITION")
        leg = F.extract_block(texts[LEGACY_TL], r"private\s+void\s+SelectTarget\s*\(")
        ctx.premise(leg is not None, "legacy-selecttarget-not-found")
        if leg is not None:
            ctx.contract(re.search(r"\bfor\s*\(", leg) is None, "LEGACY-REINIT-CHOOSES-BY-POSITION")
    L.run("R-REINIT-UNSET", "SRC", "RED-VALID", unset)

    # ---- F5: the official target is re-acquired; the distance decides nothing -------------------------------------------------------------------------------------------
    for n in range(1, 6):
        case_row("R-REINIT-F5-%d" % n, "IT", "RED-VALID", ["F5-%d" % n])

    def dist(ctx, results):
        tuples = {}
        for tag, hud, off in results:
            if tag.endswith("#1") and off["state"] is not F.MISSING:
                tuples[tag.split("#")[0]] = (off["state"], off["index"], off["location"])
        if len(tuples) == 6:
            ctx.contract(len(set(tuples.values())) == 1, "RESULT-DEPENDS-ON-DISTANCE")
    case_row("R-REINIT-F5-DIST", "IT", "RED-VALID", ["F5-D0", "F5-1", "F5-2", "F5-3", "F5-4", "F5-5"], dist)
    case_row("R-REINIT-F5-START", "IT", "RED-VALID", ["F5-START"])
    case_row("R-REINIT-F5-9", "IT", "RED-VALID", ["F5-9"])
    case_row("R-REINIT-F5-11", "IT", "RED-VALID", ["F5-11"])

    # ---- E-13: UNSET machine target is safe for the Python side -------------------------------------------------------------------------------------------------------
    case_row("R-REINIT-STATE-CNT", "IT", "GUARD", ["STATE-CNT"])

    # ---- no distance search in the product-reachable C# ---------------------------------------------------------------------------------------------------------------
    def dist01(ctx):
        if not sources_present(ctx):
            return
        n = {os.path.basename(rel): len(re.findall(r"\blocation\s*-\s*50\.0\b", t)) for rel, t in texts.items()}
        n = {k: v for k, v in n.items() if v}
        ctx.contract(not n, "DISTANCE-SEARCH-REMAINS:%s" % ",".join("%s=%d" % kv for kv in sorted(n.items())))
    L.run("R-DIST-01", "SRC", "RED-VALID", dist01)

    def guard_p1(ctx):
        if not sources_present(ctx):
            return
        cur = F.extract_block(texts[CURRENT], r"private\s+void\s+SelectTargetByRequestedIndex\s*\(")
        leg = F.extract_block(texts[LEGACY_TL], r"private\s+void\s+SelectRequestedTarget\s*\(")
        ctx.premise(cur is not None and leg is not None, "p1-selectors-not-found")
        if cur is not None:
            ctx.contract("SelectTargetByPosition" not in cur and not re.search(r"\blocation\s*-\s*50\.0\b", cur), "CURRENT-P1-REACHES-POSITION-SEARCH")
        if leg is not None:
            ctx.contract(not re.search(r"\bSelectTarget\s*\(", leg) and not re.search(r"\blocation\s*-\s*50\.0\b", leg), "LEGACY-P1-REACHES-POSITION-SEARCH")
    L.run("R-GUARD-P1", "SRC", "GUARD", guard_p1)

    left = F.harness_leftovers()
    L.run("FIX-NO-PROFILE-WRITE", "Py", "GUARD", lambda c: c.premise(not left, "profile-written:" + ",".join(left)[:80]))
    return L.report(args.expect)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
