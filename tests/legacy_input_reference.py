"""Phase LI1 - an independent statement of the Legacy generic display contract, used by the offline tests only (nothing imports it at run time).

The C# sender (Telemetry\\Legacy\\src\\LegacyHandleContract.cs) turns the handle NUMBERS of the AtsEX Legacy host into the texts of the CURRENT telemetry
format. This module states the same rules a second time, in the words of the phase brief, so that the tests can compare the two:

    python -I tests\\legacy_input_reference.py cases <file>     writes the case table as UTF-8 JSON (Test-LegacyInputLI1.ps1 feeds every case to the C# contract)

A case is { "in": [handle_type, brake_kind, rev, pow, brk, pow_n, brk_n, eb_n, hold], "out": ["ok", REV, POW, BRK, HTYPE, ALLTXT] | ["drop", reason] }
where the values after "ok" are the texts after the key as they travel on the wire (REV:前:1 -> "前:1").
"""
import json
import sys

MAX_NOTCHES = 99
REV_TEXT = {-1: "後", 0: "切", 1: "前"}
CL_TEXTS = ("運転", "重なり", "常用", "非常")
ONE_LEVER, TWO_LEVER = 1, 2
ECB, SMEE, CL = 1, 2, 3


def expected_handle(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold):
    if htype not in (ONE_LEVER, TWO_LEVER):
        return ["drop", "type-unknown"]
    if brake not in (ECB, SMEE, CL):
        return ["drop", "brake-unknown"]
    one = htype == ONE_LEVER
    cl = brake == CL
    if one and cl:
        return ["drop", "one-lever-cl"]
    if rev is None:
        return ["drop", "rev-missing"]
    if pow_ is None:
        return ["drop", "pow-missing"]
    if brk is None:
        return ["drop", "brk-missing"]
    if pow_n is None or brk_n is None or eb_n is None:
        return ["drop", "layout-missing"]
    if hold is None:
        return ["drop", "hold-missing"]
    if hold:
        return ["drop", "holding-unconfirmed"]
    if pow_n < 0 or pow_n > MAX_NOTCHES or brk_n < 1 or brk_n > MAX_NOTCHES or eb_n < 1 or eb_n > MAX_NOTCHES + 1:
        return ["drop", "layout-range"]
    if cl:
        if brk_n != 2 or eb_n != 3:
            return ["drop", "cl-layout"]
    elif eb_n != brk_n + 1:
        return ["drop", "eb-layout"]
    if rev < -1 or rev > 1:
        return ["drop", "rev-range"]
    if pow_ < 0 or pow_ > pow_n:
        return ["drop", "pow-range"]
    if brk < 0:
        return ["drop", "brk-range"]

    def power_text(n):
        return "N" if (n == 0 and one) else "P%d" % n

    def brake_text(n):
        # one lever: position 0 is the neutral N of the single handle; two lever: the brake handle shows B0
        return "N" if (n == 0 and one) else "B%d" % n

    all_pow = "_".join(power_text(n) for n in range(pow_n + 1))
    if cl:
        brk_text = CL_TEXTS[3] if brk >= eb_n else CL_TEXTS[brk]
        all_brk = "_".join(CL_TEXTS)
    else:
        brk_text = "EB" if brk >= eb_n else brake_text(brk)
        all_brk = "_".join([brake_text(0)] + ["B%d" % i for i in range(1, eb_n)] + ["EB"])
    return ["ok",
            "%s:%d" % (REV_TEXT[rev], rev),
            "%s:%d" % (power_text(pow_), pow_),
            "%s:%d:%d" % (brk_text, brk, eb_n),
            str(htype),
            "%s:%s:%s:" % ("_".join(REV_TEXT[r] for r in (-1, 0, 1)), all_pow, all_brk)]


# layouts seen on the real machine (BVE5 + AtsEX Legacy, Phase LI0 logs): (handle type, brake kind, power notches, brake notches, emergency notch)
OBSERVED_LAYOUTS = (
    (ONE_LEVER, ECB, 4, 5, 6),
    (ONE_LEVER, ECB, 5, 6, 7),
    (ONE_LEVER, ECB, 5, 8, 9),
    (TWO_LEVER, ECB, 4, 7, 8),
    (TWO_LEVER, ECB, 6, 8, 9),
    (TWO_LEVER, SMEE, 4, 9, 10),
    (TWO_LEVER, CL, 5, 2, 3),
    (ONE_LEVER, SMEE, 4, 9, 10),       # same numbers as the two-lever Smee; a one-lever Smee cab has not been seen yet
)


def case(inputs):
    return {"in": list(inputs), "out": expected_handle(*inputs)}


def all_cases():
    cases = []
    for htype, brake, pow_n, brk_n, eb_n in OBSERVED_LAYOUTS:
        for rev in (-1, 0, 1):
            for pow_ in range(pow_n + 1):
                for brk in range(eb_n + 2):
                    cases.append(case((htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, False)))
    # the combinations that must NOT produce a handle group (each reason once or more), and the borders of the layout
    base = (TWO_LEVER, ECB, 0, 0, 0, 4, 7, 8, False)

    def vary(**kw):
        names = ("htype", "brake", "rev", "pow", "brk", "pow_n", "brk_n", "eb_n", "hold")
        values = dict(zip(names, base))
        values.update(kw)
        return tuple(values[n] for n in names)

    for kw in (
        {"htype": 0}, {"htype": 3}, {"brake": 0}, {"brake": 4},
        {"htype": ONE_LEVER, "brake": CL}, {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3},
        {"rev": None}, {"pow": None}, {"brk": None}, {"pow_n": None}, {"brk_n": None}, {"eb_n": None},
        {"hold": None}, {"hold": True},
        {"pow_n": -1}, {"pow_n": 100}, {"brk_n": 0}, {"brk_n": 100, "eb_n": 101}, {"eb_n": 0}, {"eb_n": 101, "brk_n": 100},
        {"eb_n": 10}, {"eb_n": 7}, {"eb_n": 9},                                     # not brake notches + 1
        {"brake": CL, "pow_n": 5, "brk_n": 3, "eb_n": 4}, {"brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 4}, {"brake": CL, "pow_n": 5, "brk_n": 1, "eb_n": 2},
        {"rev": 2}, {"rev": -2}, {"rev": 100},
        {"pow": 5}, {"pow": -1}, {"pow": 1000},
        {"brk": -1}, {"brk": 9}, {"brk": 10}, {"brk": 1000},
        {"pow_n": 0, "pow": 0}, {"pow_n": 99, "pow": 99}, {"brk_n": 99, "eb_n": 100, "brk": 100},
    ):
        cases.append(case(vary(**kw)))
    return cases


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "cases":
        with open(sys.argv[2], "wb") as f:                      # a file, not a pipe: no console encoding or BOM in between
            f.write(json.dumps(all_cases(), ensure_ascii=False).encode("utf-8"))
    else:
        sys.stderr.write("usage: legacy_input_reference.py cases <output file>\n")
        sys.exit(2)
