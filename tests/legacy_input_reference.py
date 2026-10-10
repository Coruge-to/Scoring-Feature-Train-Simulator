"""Phase LI1 / LI2 - an independent statement of the Legacy generic display contract, used by the offline tests only (nothing imports it at run time).

The C# sender (Telemetry\\Legacy\\src\\LegacyHandleContract.cs) turns the handle NUMBERS of the AtsEX Legacy host into the texts of the CURRENT telemetry
format. This module states the same rules a second time, in the words of the phase briefs, so that the tests can compare the two:

    python -I tests\\legacy_input_reference.py cases <file>     writes the case table as UTF-8 JSON (Test-LegacyInputLI1.ps1 feeds every case to the C# contract)

A case is { "in": [handle_type, brake_kind, rev, pow, brk, pow_n, brk_n, eb_n, hold, hold_n], "out": ["ok", REV, POW, BRK, HTYPE, ALLTXT] | ["drop", reason] }
where the values after "ok" are the texts after the key as they travel on the wire (REV:前:1 -> "前:1"), `hold` is HasHoldingSpeedBrake (the first BRAKE position
is the holding speed brake) and `hold_n` is HoldingSpeedNotchCount (the independent holding speed notches H1..Hn of a two-lever cab). The two are different
features and are never mixed up. hold_n is not used (and may be anything) unless the cab is a two-lever Ecb / Smee cab without the holding speed brake.

hold_n is the value AS THE HOST REPORTS IT, and the host reports it NEGATED: the BVE5 vehicle loader keeps the vehicle's count n as -n (it is the lower bound the
handle is clamped to, Min(Max(input, -n), power notches)), so a car with five independent holding speed notches reports -5 (real machine, Phase LI2 retest);
the number of notches is -hold_n. 0 = none; a value above 0, below -99 or unreadable (None) is not a count.

Phase LI2 final: the 24 combinations cab (one / two lever) x brake (Ecb / Smee / Cl) x hold_n (0 / set) x hold (False / True) were all observed on the real BVE5
(artificial vehicles included) and are ALL built; this module states them twice: `expected_handle` (the rule) and `MATRIX24` / `matrix_rows()` (every combination spelled
out, texts and ALLTXT included, machine readable: `python -I tests\\legacy_input_reference.py matrix <file>`).
"""
import json
import sys

MAX_NOTCHES = 99
REV_TEXT = {-1: "後", 0: "切", 1: "前"}
CL_TWO = ("運転", "重なり", "常用", "非常")          # Cl brake handle (two lever)
CL_ONE = CL_TWO                                    # one-lever Cl: the handle at rest is the run word too (LI2 final: it used to be the word for "off")
CL_TEXTS = CL_TWO
HOLD_BRAKE_WORD = "抑速"                             # the holding speed BRAKE position (brake position 1); never "H1"
ONE_LEVER, TWO_LEVER = 1, 2
ECB, SMEE, CL = 1, 2, 3


def expected_handle(htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n=0):
    if htype not in (ONE_LEVER, TWO_LEVER):
        return ["drop", "type-unknown"]
    if brake not in (ECB, SMEE, CL):
        return ["drop", "brake-unknown"]
    one = htype == ONE_LEVER
    cl = brake == CL
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
    if pow_n < 0 or pow_n > MAX_NOTCHES or brk_n < 1 or brk_n > MAX_NOTCHES or eb_n < 1 or eb_n > MAX_NOTCHES + 1:
        return ["drop", "layout-range"]
    if cl:
        if brk_n != 2 or eb_n != 3:
            return ["drop", "cl-layout"]
    elif eb_n != brk_n + 1:
        return ["drop", "eb-layout"]
    if rev < -1 or rev > 1:
        return ["drop", "rev-range"]
    independent = not one                                       # only a two-lever cab has the independent holding speed notches (any brake kind, with or without the holding speed brake)
    h_n = 0
    hold_why = None
    if independent:
        # the host reports the count NEGATED (the lower bound of POW: 5 notches = -5, see the module text): 0..-99 is a count, anything else is not
        if hold_n is None:
            hold_why = "holdn-missing"
        elif hold_n > 0 or hold_n < -MAX_NOTCHES:
            hold_why = "hold-range"
        else:
            h_n = -hold_n
    if pow_ < 0 and hold_why:                                   # an unusable count takes only the POW-below-zero positions away
        return ["drop", hold_why]
    if pow_ < -h_n or pow_ > pow_n:
        return ["drop", "pow-range"]
    if brk < 0 or brk > eb_n:                                   # at the emergency notch is EB / the emergency word, beyond it is not a position
        return ["drop", "brk-range"]
    if one and pow_ > 0 and brk > 0:                            # a single handle cannot hold power and brake
        return ["drop", "pow-brk-both"]

    def power_text(n):
        if n < 0:
            return "H%d" % -n
        if n == 0 and one:
            return "運転" if cl else "N"
        return "P%d" % n

    def brake_text(n):
        # one lever: position 0 is the neutral N of the single handle; two lever: the brake handle shows B0
        return "N" if (n == 0 and one) else "B%d" % n

    all_pow = "_".join(power_text(n) for n in range(pow_n + 1))
    if cl:
        words = list(CL_ONE if one else CL_TWO)
        if hold:
            words[1] = HOLD_BRAKE_WORD                           # the holding speed brake replaces "lap" at brake position 1
        brk_text = words[3] if brk >= eb_n else words[brk]
        all_brk = "_".join(words)
    elif hold:
        # B0 (one lever N), holding speed brake, B1 .. B(brake notches - 1), EB: the first brake position is the holding speed brake
        if brk >= eb_n:
            brk_text = "EB"
        elif brk == 0:
            brk_text = brake_text(0)
        elif brk == 1:
            brk_text = HOLD_BRAKE_WORD
        else:
            brk_text = "B%d" % (brk - 1)
        all_brk = "_".join([brake_text(0), HOLD_BRAKE_WORD] + ["B%d" % i for i in range(1, brk_n)] + ["EB"])
    else:
        brk_text = "EB" if brk >= eb_n else brake_text(brk)
        all_brk = "_".join([brake_text(0)] + ["B%d" % i for i in range(1, eb_n)] + ["EB"])
    all_hold = "_".join("H%d" % i for i in range(1, h_n + 1))
    return ["ok",
            "%s:%d" % (REV_TEXT[rev], rev),
            "%s:%d" % (power_text(pow_), pow_),
            "%s:%d:%d" % (brk_text, brk, eb_n),
            str(htype),
            "%s:%s:%s:%s" % ("_".join(REV_TEXT[r] for r in (-1, 0, 1)), all_pow, all_brk, all_hold)]


# layouts seen on the real machine (BVE5 + AtsEX Legacy, Phase LI0 / LI2 logs): (handle type, brake kind, power notches, brake notches, emergency notch)
OBSERVED_LAYOUTS = (
    (ONE_LEVER, ECB, 4, 5, 6),
    (ONE_LEVER, ECB, 5, 6, 7),
    (ONE_LEVER, ECB, 5, 8, 9),
    (TWO_LEVER, ECB, 4, 7, 8),
    (TWO_LEVER, ECB, 6, 8, 9),
    (TWO_LEVER, SMEE, 4, 9, 10),
    (TWO_LEVER, CL, 5, 2, 3),
    (ONE_LEVER, CL, 5, 2, 3),          # LI2: the one-lever Cl cab (an ordinary Cl car with [OneLeverCab])
    (ONE_LEVER, SMEE, 4, 9, 10),       # same numbers as the two-lever Smee; a one-lever Smee cab has not been seen yet
)

# LI2: the holding speed layouts: (handle type, brake kind, power notches, brake notches, emergency notch, holding speed brake, holding speed notches)
HOLD_LAYOUTS = (
    (TWO_LEVER, ECB, 5, 8, 9, True, 0),        # the holding speed BRAKE car seen on the real machine (brake position 1 = the holding speed brake)
    (TWO_LEVER, SMEE, 4, 9, 10, True, 0),
    (TWO_LEVER, SMEE, 5, 8, 9, False, -5),     # the independent holding speed car seen on the real machine (H1..H5 = POW -1..-5; the host reports HoldingSpeedNotchCount = -5)
    (TWO_LEVER, ECB, 6, 8, 9, False, -3),
    (ONE_LEVER, ECB, 5, 8, 9, False, -5),      # a one-lever cab with a HoldingSpeedNotchCount only: an ordinary one-lever cab
    (ONE_LEVER, SMEE, 4, 9, 10, False, -2),
    (TWO_LEVER, CL, 5, 2, 3, False, -5),       # (the holding speed notches are not used by Cl)
)


# ---------------------------------------------------------------------------------------------------------------------------------------
# LI2 final: the 24 combinations observed on the real BVE5 (artificial vehicles included): cab x brake x HoldingSpeedNotchCount x HoldingSpeedBrake.
# hold_n is the HOST value (0 = none, -5 = five independent holding speed notches). Ecb and Smee are separate rows although the texts are the same.
CABS = (ONE_LEVER, TWO_LEVER)
BRAKES = (ECB, SMEE, CL)
HOLD_NS = (0, -5)
HOLD_BRAKES = (False, True)
LAYOUT_OF = {ECB: (5, 8, 9), SMEE: (5, 8, 9), CL: (5, 2, 3)}        # power notches, brake notches, emergency notch (the layouts seen on the real machine)
BRAKE_NAME = {ECB: "ecb", SMEE: "smee", CL: "cl"}


def matrix_combinations():
    """(handle type, brake, hold brake, hold_n, power notches, brake notches, emergency notch) for all 2 x 3 x 2 x 2 = 24 combinations, in a fixed order."""
    rows = []
    for htype in CABS:
        for brake in BRAKES:
            for hold_n in HOLD_NS:
                for hold in HOLD_BRAKES:
                    rows.append((htype, brake, hold, hold_n) + LAYOUT_OF[brake])
    return rows


# the brake texts by brake position 0..eb, spelled out (not computed from the rule above)
_B_ECB_TWO = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "EB"]
_B_ECB_TWO_HOLD = ["B0", "抑速", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "EB"]
_B_ECB_ONE = ["N", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "EB"]
_B_ECB_ONE_HOLD = ["N", "抑速", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "EB"]
_B_CL = ["運転", "重なり", "常用", "非常"]
_B_CL_HOLD = ["運転", "抑速", "常用", "非常"]
_P_TWO = ["P0", "P1", "P2", "P3", "P4", "P5"]
_P_ONE = ["N", "P1", "P2", "P3", "P4", "P5"]
_P_ONE_CL = ["運転", "P1", "P2", "P3", "P4", "P5"]
_H = ["H1", "H2", "H3", "H4", "H5"]


def matrix_rows():
    """The 24 combinations with every text spelled out: name, inputs and, for POW -h..n and BRK 0..e, the POW / BRK texts, ALLTXT and HTYPE."""
    rows = []
    for htype, brake, hold, hold_n, pow_n, brk_n, eb_n in matrix_combinations():
        one = htype == ONE_LEVER
        if brake == CL:
            brks = list(_B_CL_HOLD if hold else _B_CL)
            pows = list(_P_ONE_CL if one else _P_TWO)
        else:
            brks = list(_B_ECB_ONE_HOLD if hold else _B_ECB_ONE) if one else list(_B_ECB_TWO_HOLD if hold else _B_ECB_TWO)
            pows = list(_P_ONE if one else _P_TWO)
        h_n = 0 if one else -hold_n                             # the independent notches exist on a two-lever cab only
        hold_texts = "_".join(_H[:h_n])
        pow_by_notch = {}
        for k in range(1, h_n + 1):
            pow_by_notch[-k] = _H[k - 1]
        for k, text in enumerate(pows):
            pow_by_notch[k] = text
        assert len(brks) == eb_n + 1                            # one text per brake position 0..e
        brk_by_notch = dict(enumerate(brks))
        name = "%s-lever-%s-holdN%d-holdBrake%d" % ("one" if one else "two", BRAKE_NAME[brake], hold_n, 1 if hold else 0)
        rows.append({
            "name": name,
            "in": [htype, brake, hold, hold_n, pow_n, brk_n, eb_n],
            "htype": str(htype),
            "pow_min": -h_n,
            "pow_texts": {str(k): v for k, v in sorted(pow_by_notch.items())},
            "brk_texts": {str(k): v for k, v in sorted(brk_by_notch.items())},
            "alltxt": "後_切_前:%s:%s:%s" % ("_".join(pows), "_".join(brks), hold_texts),
        })
    return rows


def case(inputs):
    return {"in": list(inputs), "out": expected_handle(*inputs)}


def all_cases():
    cases = []
    for htype, brake, pow_n, brk_n, eb_n in OBSERVED_LAYOUTS:
        for rev in (-1, 0, 1):
            for pow_ in range(pow_n + 1):
                for brk in range(eb_n + 2):
                    cases.append(case((htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, False, 0)))
    for htype, brake, pow_n, brk_n, eb_n, hold, hold_n in HOLD_LAYOUTS:
        for rev in (-1, 0, 1):
            for pow_ in range(hold_n - 1, pow_n + 2):
                for brk in range(eb_n + 2):
                    cases.append(case((htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n)))
    # LI2 final: every one of the 24 combinations (Ecb and Smee kept apart) at every position, power side down to the host count - 1
    for htype, brake, hold, hold_n, pow_n, brk_n, eb_n in matrix_combinations():
        for rev in (-1, 0, 1):
            for pow_ in range(hold_n - 1, pow_n + 2):
                for brk in range(eb_n + 3):
                    cases.append(case((htype, brake, rev, pow_, brk, pow_n, brk_n, eb_n, hold, hold_n)))
    # the combinations that must NOT produce a handle group (each reason once or more), and the borders of the layout
    base = (TWO_LEVER, ECB, 0, 0, 0, 4, 7, 8, False, 0)

    def vary(**kw):
        names = ("htype", "brake", "rev", "pow", "brk", "pow_n", "brk_n", "eb_n", "hold", "hold_n")
        values = dict(zip(names, base))
        values.update(kw)
        return tuple(values[n] for n in names)

    for kw in (
        {"htype": 0}, {"htype": 3}, {"brake": 0}, {"brake": 4},
        {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 3, "eb_n": 4}, {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 4},
        {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 1, "eb_n": 2}, {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3, "pow": 1, "brk": 1},
        {"htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3, "pow": 5, "brk": 3},
        {"rev": None}, {"pow": None}, {"brk": None}, {"pow_n": None}, {"brk_n": None}, {"eb_n": None},
        {"hold": None}, {"hold": True}, {"hold": True, "htype": ONE_LEVER}, {"hold": True, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3},
        {"hold": True, "htype": ONE_LEVER, "brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3},         # (LI2 final: all of these are built now)
        {"hold_n": None}, {"hold_n": None, "pow": -1}, {"hold_n": None, "pow": 3},                                     # unreadable: only POW below zero is gone
        {"hold_n": 1}, {"hold_n": 1, "pow": -1}, {"hold_n": 5, "pow": 2},                                           # above 0 is not a count (the positive value used before the retest)
        {"hold_n": 100, "pow": -1}, {"hold_n": -100}, {"hold_n": -100, "pow": -1}, {"hold_n": -100, "pow": 4},       # beyond 99 notches
        {"hold_n": -5}, {"hold_n": -5, "pow": -5}, {"hold_n": -5, "pow": -6}, {"hold_n": -1, "pow": -1}, {"hold_n": -1, "pow": -2},
        {"hold_n": -99, "pow": -99}, {"hold_n": -99, "pow": -100}, {"hold": True, "hold_n": None}, {"hold": True, "hold_n": -5, "pow": -1},
        {"htype": ONE_LEVER, "hold_n": None}, {"htype": ONE_LEVER, "hold_n": -5, "pow": -1}, {"brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 3, "hold_n": -5, "pow": -1},
        {"pow_n": -1}, {"pow_n": 100}, {"brk_n": 0}, {"brk_n": 100, "eb_n": 101}, {"eb_n": 0}, {"eb_n": 101, "brk_n": 100},
        {"eb_n": 10}, {"eb_n": 7}, {"eb_n": 9},                                     # not brake notches + 1
        {"brake": CL, "pow_n": 5, "brk_n": 3, "eb_n": 4}, {"brake": CL, "pow_n": 5, "brk_n": 2, "eb_n": 4}, {"brake": CL, "pow_n": 5, "brk_n": 1, "eb_n": 2},
        {"rev": 2}, {"rev": -2}, {"rev": 100},
        {"pow": 5}, {"pow": -1}, {"pow": 1000}, {"pow": -1000},
        {"brk": -1}, {"brk": 9}, {"brk": 10}, {"brk": 1000},
        {"pow_n": 0, "pow": 0}, {"pow_n": 99, "pow": 99}, {"brk_n": 99, "eb_n": 100, "brk": 100},
    ):
        cases.append(case(vary(**kw)))
    return cases


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "cases":
        with open(sys.argv[2], "wb") as f:                      # a file, not a pipe: no console encoding or BOM in between
            f.write(json.dumps(all_cases(), ensure_ascii=False).encode("utf-8"))
    elif len(sys.argv) > 2 and sys.argv[1] == "matrix":
        with open(sys.argv[2], "wb") as f:
            f.write(json.dumps(matrix_rows(), ensure_ascii=False, indent=1).encode("utf-8"))
    else:
        sys.stderr.write("usage: legacy_input_reference.py cases|matrix <output file>\n")
        sys.exit(2)
