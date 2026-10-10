"""Phase SI-1 - the ground speed limit contract of the AtsEX Legacy sender, seen from the PYTHON side (standard library plus PyQt6 for the behaviour part).

    python -m unittest tests.test_ground_limits_si1 -v

(A) the vocabulary and the scope: the Python telemetry contract already names the two groups the Legacy sender now announces (trainlen: TRAINLEN,
    maplimit_ahead: MAPLIMITS + CLEARDIST), the C# contract names the same tokens, and NO Python production file was changed for SI-1.
(B) behaviour with the REAL, UNCHANGED Overlay and scoring_logic (tests/si1_flash_probe.py, UDP stubbed): datagrams in the shape the Legacy sender writes
    make the HUD flash RED for a ground limit (MAPLIMITS candidate) and BLUE for a tail wait (MAPTAIL < MAPHEAD); without MAPLIMITS there is no ground red,
    without a real MAPHEAD (MAPHEAD == MAPTAIL) there is no blue, the signal red is the same, and a new scenario instance forgets the old list.
The offline PowerShell test (Tests/Test-GroundLimitsSI1.ps1) drives the real DLL and feeds ITS datagrams to the same probe; this file pins the Python side alone.
"""
import importlib.util
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import telemetry_contract as tc  # noqa: E402

HAS_QT = importlib.util.find_spec("PyQt6") is not None
CONTRACT_CS = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Telemetry", "Shared", "TelemetryContract.cs")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class A_VocabularyAndScope(unittest.TestCase):
    def test_python_names_the_two_groups_with_the_keys_the_legacy_sender_writes(self):
        self.assertEqual(tc.TOKEN_KEYS["trainlen"], ("TRAINLEN",))
        self.assertEqual(tc.TOKEN_KEYS["maplimit_ahead"], ("MAPLIMITS", "CLEARDIST"))
        self.assertEqual(tc.TOKEN_KEYS["maplimit"], ("MAPHEAD", "MAPTAIL"))

    def test_the_csharp_contract_has_the_same_two_token_names(self):
        text = read(CONTRACT_CS)
        self.assertRegex(text, r'internal const string TokMapLimitAhead = "maplimit_ahead";')
        self.assertRegex(text, r'internal const string TokTrainLen = "trainlen";')
        cs_tokens = set(re.findall(r'internal const string Tok\w+ = "([a-z_]+)"', text))
        self.assertTrue(cs_tokens <= set(tc.KNOWN_TOKENS), cs_tokens - set(tc.KNOWN_TOKENS))
        self.assertEqual(set(tc.KNOWN_TOKENS) - cs_tokens, {"doortime", "jump"})      # what the Legacy sender still cannot provide

    def test_a_line_with_the_new_tokens_is_understood_by_the_availability_parser(self):
        parsed = tc.parse_telemetry(line(1000, 40, 50, 90, "1500.0=65.0"))
        self.assertTrue(parsed.valid)
        self.assertEqual(parsed.avail_status, tc.AVAIL_OK)
        self.assertTrue({"trainlen", "maplimit_ahead", "maplimit"} <= set(parsed.tokens))
        self.assertEqual((parsed.unknown_tokens, parsed.bad_tokens), (0, 0))

    def test_no_python_production_file_changed_for_si1(self):
        try:
            changed = subprocess.run(["git", "-C", ROOT, "diff", "--name-only", "HEAD"], capture_output=True, text=True, timeout=60).stdout.split()
            tracked = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, text=True, timeout=60).stdout.split()
        except Exception:
            self.skipTest("git is not available - INCONCLUSIVE")
        production = [p for p in tracked if p.endswith(".py") and not p.startswith("tests/")]
        self.assertGreater(len(production), 10)
        self.assertEqual([p for p in changed if p in production], [])


def line(loc, speed, tail, head, limits="", clear=0, train=100, sig=1000, fwd_limit=1000, fwd_loc=-1, sid=7, t=36000000, avail=None):
    avail = avail or "AVAIL:1:loc+maplimit+maplimit_ahead+siglimit+siglimit_ahead+speed+time+trainlen"
    return ("SCENARIO_ID:%d,%s,SPEED:%s,TIME:%d,LOCATION:%s,SIGLIMIT:%s,FWDSIGLIMIT:%s,FWDSIGLOC:%s,MAPHEAD:%s,MAPTAIL:%s,TRAINLEN:%s,MAPLIMITS:%s,CLEARDIST:%s"
            % (sid, avail, speed, t, loc, sig, fwd_limit, fwd_loc, head, tail, train, limits, clear))


def run_probe(sequences):
    import si1_flash_probe
    return si1_flash_probe.run(sequences)


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter (INCONCLUSIVE for the behaviour part)")
class B_RealPythonBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seqs = {}
        # ground red: 70 km/h now, a 60 km/h limit at 2500 m ahead (MAPLIMITS), the tail value is the host value 70
        seqs["red"] = [line(1500 + 25 * i, 70, 70, 70, "2500.0=60.0", t=36000000 + 1000 * i) for i in range(40)]
        # the same without MAPLIMITS (the sender could not read the list): the group is not announced and the keys are not there
        no_ahead = "AVAIL:1:loc+maplimit+siglimit+siglimit_ahead+speed+time"
        seqs["red-missing"] = [re.sub(r",TRAINLEN:[^,]*,MAPLIMITS:[^,]*,CLEARDIST:[^,]*", "", line(1500 + 25 * i, 70, 70, 70, "2500.0=60.0", t=36000000 + 1000 * i, avail=no_ahead)) for i in range(40)]
        # blue: the host limit (tail) is 50, the list head value is 90, the signal 100: tail wait
        seqs["blue"] = [line(1010 + i, 40, 50, 90, "", clear=90 - i, sig=100, t=36000000 + 1000 * i) for i in range(40)]
        # no real MAPHEAD (== MAPTAIL): no blue
        seqs["blue-missing"] = [line(1010 + i, 40, 50, 50, "", clear=0, sig=100, t=36000000 + 1000 * i) for i in range(40)]
        # the signal red (FWDSIGLIMIT 40 at 2400 m) with a ground list that has nothing lower
        seqs["signal"] = [line(2000 + 20 * i, 70, 100, 100, "", sig=100, fwd_limit=40, fwd_loc=2400, t=36000000 + 1000 * i) for i in range(20)]
        # a new scenario instance forgets the old list: list in 7, then 8 without any
        seqs["generation"] = (["@strict", "@gen=1"] + [line(1500 + 25 * i, 70, 70, 70, "2500.0=60.0", sid=7, t=36000000 + 1000 * i) for i in range(5)] + ["@gen=2"]
                              + [re.sub(r",TRAINLEN:[^,]*,MAPLIMITS:[^,]*,CLEARDIST:[^,]*", "", line(1500 + 25 * i, 70, 70, 70, "", sid=8, t=36000000 + 1000 * i, avail=no_ahead)) for i in range(5)])
        cls.res = run_probe(seqs)

    def test_ground_red_flashes_from_a_maplimits_candidate_lower_than_the_effective_limit(self):
        steps = self.res["red"]
        self.assertTrue(all(s["ahead"] == 1 for s in steps))
        flashing = [s for s in steps if s["blink"] and s["color"] == "red"]
        self.assertTrue(flashing)
        self.assertTrue(all(abs(s["disp"] - 60.0) < 0.001 for s in flashing))

    def test_without_maplimits_there_is_no_ground_red(self):
        steps = self.res["red-missing"]
        self.assertTrue(all(s["ahead"] == 0 and s["red"] == "None" and not s["blink"] for s in steps))

    def test_blue_flashes_while_the_tail_waits_for_a_higher_limit(self):
        steps = self.res["blue"]
        self.assertTrue(all(s["wait"] and s["blue"] == "90.0" and s["blink"] and s["color"] == "blue" and s["red"] == "None" for s in steps))
        self.assertTrue(all(abs(s["disp"] - 90.0) < 0.001 for s in steps))

    def test_without_a_real_maphead_there_is_no_blue(self):
        steps = self.res["blue-missing"]
        self.assertTrue(all((not s["wait"]) and s["blue"] == "None" and not s["blink"] for s in steps))

    def test_the_signal_red_is_what_it_was(self):
        flashing = [s for s in self.res["signal"] if s["blink"] and s["color"] == "red"]
        self.assertTrue(flashing)
        self.assertTrue(all(s["red"] == "40.0" for s in flashing))

    def test_a_new_scenario_instance_does_not_keep_the_old_candidate_list(self):
        """Managed mode (the strict, generation aware gate): the new SCENARIO_ID resets the telemetry state, so a group the new sender does not announce is the
        default, never the value of the previous scenario instance."""
        steps = self.res["generation"]
        self.assertTrue(all(s["ahead"] == 1 for s in steps[:5]))
        self.assertTrue(all(s["ahead"] == 0 and s["red"] == "None" and not s["blink"] for s in steps[5:]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
