"""Phase SI-R5.3 R53-04A fix design, Stage 0 - the RED / GREEN ledger of the "no message pump on the UI (STA) thread" contract (an executable specification index; NOT a discoverable unit test: the file name does not start with test_).

Usage (Python):   python -B tests/red_observation_ui_contract.py [--results-file <Test-ObservationUiNonBlocking.ps1 -ResultsFile output>] [--expect red|green]

One row per static test of tests/test_observation_ui_contract_static.py (test_red_* / test_guard_*), run in this process, plus one row per dynamic row
(RESULT <id> RED|GUARD PASS|FAIL) of the PowerShell result file when given.
  --expect red    (the current sources / DLLs): every RED row is FAIL and every GUARD row is PASS      -> exit 0
  --expect green  (after the fix):              every row is PASS                                       -> exit 0
TS_UI_CONTRACT_SRC=<flat folder> points the static rows at a scratch prototype (Stage 0 validation of the tests). It starts no BVE and builds nothing.
"""
import argparse
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RES = re.compile(r"^RESULT (\S+) (RED|GUARD) (PASS|FAIL)\b")


def static_rows():
    sys.path.insert(0, HERE)
    import test_observation_ui_contract_static as mod

    class Collect(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.outcome = {}

        def addSuccess(self, test):
            super().addSuccess(test)
            self.outcome.setdefault(test.id().split(".")[-1], "PASS")

        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.outcome[test.id().split(".")[-1]] = "PASS"

        def addFailure(self, test, err):
            super().addFailure(test, err)
            self.outcome[test.id().split(".")[-1]] = "FAIL"

        def addError(self, test, err):
            super().addError(test, err)
            self.outcome[test.id().split(".")[-1]] = "FAIL"

    result = Collect()
    unittest.defaultTestLoader.loadTestsFromModule(mod).run(result)
    rows = []
    for name, outcome in sorted(result.outcome.items()):
        kind = "RED" if name.startswith("test_red_") else "GUARD"
        rows.append(("static:" + name, kind, outcome))
    return rows


def dynamic_rows(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = RES.match(line)
            if m:
                rows.append(("dynamic:" + m.group(1), m.group(2), m.group(3)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-file", default="")
    ap.add_argument("--expect", choices=("red", "green"), default="red")
    args = ap.parse_args()
    rows = static_rows()
    if args.results_file:
        rows += dynamic_rows(args.results_file)
    bad = []
    for name, kind, outcome in rows:
        if args.expect == "red":
            ok = (kind == "RED" and outcome == "FAIL") or (kind == "GUARD" and outcome == "PASS")
        else:
            ok = outcome == "PASS"
        print("%-6s %-5s %-4s  %s" % ("OK" if ok else "UNEXPECTED", kind, outcome, name))
        if not ok:
            bad.append(name)
    reds = sum(1 for _n, k, _o in rows if k == "RED")
    guards = len(rows) - reds
    print("SUMMARY expect=%s rows=%d (RED %d, GUARD %d) unexpected=%d" % (args.expect, len(rows), reds, guards, len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
