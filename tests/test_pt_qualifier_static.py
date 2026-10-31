"""PR-1a / PR-1b (clone): static A->B recognition and the PTPAIR key, Python side.
The product Python module only DECODES and VALIDATES (PQ-P4). The qualification oracle lives in tests/pt_oracle.py and is test-only.
The C# twin of these vectors is TsScoringPlugin/Handshake/Tests/Test-PseudoTurnbackQualifier.ps1 (same tests/pt_vectors.json)."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, 'tests')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
VEC = json.load(open(os.path.join(ROOT, 'tests', 'pt_vectors.json'), encoding='utf-8'))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def _code(rel):
    text = re.sub(r'"""[\s\S]*?"""', '', _read(rel))
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith(('#', '//')))


class OracleVsVectors(unittest.TestCase):
    """The oracle is the independent reference of the vectors (PR-R1, R2, R26, R27)."""

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, 'tests'))
        import pt_oracle
        self.O = pt_oracle

    def test_every_qualifier_vector(self):
        for c in VEC['qualifier']:
            got = [list(x) for x in self.O.qualify([tuple(r) for r in c['records']])]
            self.assertEqual(got, c['expect'], c['id'])

    def test_fifteen_strict_candidates_are_qualified(self):
        real = [c for c in VEC['qualifier'] if c['group'] == 'strict-candidate']
        self.assertEqual(len(real), 15)
        for c in real:
            self.assertEqual(len(c['expect']), 1, c['id'])
            a, b, _ = c['expect'][0]
            self.assertGreaterEqual(a, 1)
            self.assertEqual(b, a + 1)

    def test_rejected_first_station_pairs_are_excluded(self):
        rej = [c for c in VEC['qualifier'] if c['group'] == 'rejected-first-station']
        self.assertEqual(len(rej), 3)
        for c in rej:
            self.assertTrue(all(a >= 1 for a, b, m in c['expect']), c['id'])
            # the raw data DOES contain the A index 0 / B index 1 shape: it is excluded by the A >= 1 rule alone
            r = c['records']
            self.assertTrue(r[0][0] and not r[0][1] and not r[1][0] and r[1][1], c['id'])

    def test_iida_variants_differ_by_file(self):
        by = {c['id']: c['expect'] for c in VEC['qualifier'] if c['group'] == 'iida-variant'}
        self.assertEqual(by['S-IIDA-stations'], [[1, 2, 1]])               # the 3-station list audited as Test02 -> Test03: B is the LAST record and no t exists -> CompleteAfterJump
        self.assertEqual(by['S-IIDA-stations_diag_o3_t'], [])              # the 6-station Season 2 list: Pair 0
        self.assertEqual(by['S-IIDA-stations_diag_o3_d0'], [])
        self.assertEqual(by['S-IIDA-stations_r53_close330_v1'], [])
        self.assertEqual(by['S-IIDA-stations_b3zero_v1'], [[2, 3, 1]])     # post-audit variant: Test02c -> Test03, also a final pair

    def test_comments_blank_and_empty_records_removed_before_index(self):
        c = VEC['text_cases'][0]
        recs = self.O.records_from_station_text(c['text'])
        self.assertEqual([list(x) for x in self.O.qualify(recs)], c['expect'])
        self.assertEqual(c['expect'], [[2, 3, 0]])

    def test_no_door_signal_distance_name_or_location_input(self):
        import inspect
        sig = inspect.signature(self.O.qualify)
        self.assertEqual(list(sig.parameters), ['records'])
        self.assertTrue(all(len(r) == 4 for c in VEC['qualifier'] for r in c['records']))

    def test_unresolved_is_not_pair_zero_is_a_python_contract_not_a_qualifier_input(self):
        # a station list that could not be read is NOT a list with zero pairs: the oracle has no way to express "unknown"; callers must pass None -> the product treats it as key absent
        self.assertEqual(self.O.qualify([]), [])


class ProductDecode(unittest.TestCase):
    """The product module (RED on cab7dce: it does not exist)."""

    def setUp(self):
        import importlib
        self.M = importlib.import_module('pseudo_turnback_contract')

    def test_valid_keys(self):
        for c in VEC['codec_valid']:
            ps, why = self.M.decode_ptpair(c['text'], c['expect_count'])
            self.assertIsNone(why, c['text'])
            self.assertEqual(ps.list_id, c['list_id'])
            self.assertEqual([list(p) for p in ps.pairs], c['pairs'])

    def test_invalid_keys_are_rejected_whole_with_the_fixed_word(self):
        for c in VEC['codec_invalid']:
            ps, why = self.M.decode_ptpair(c['text'], c['expect_count'])
            self.assertIsNone(ps, c['text'])
            self.assertEqual(why, c['reason'], c['text'])

    def test_zero_pairs_is_valid_and_not_absent(self):
        ps, why = self.M.decode_ptpair('PTPAIR:1:A1B2C3D4:12:0:', 12)
        self.assertIsNone(why)
        self.assertEqual(ps.pairs, ())

    def test_every_vector_ptpair_string_decodes_to_the_expected_pairs(self):
        for c in VEC['qualifier']:
            n = len(c['records'])
            ps, why = self.M.decode_ptpair(c['ptpair'], n)
            self.assertIsNone(why, c['id'])
            self.assertEqual([list(p) for p in ps.pairs], c['expect'], c['id'])

    def test_no_partial_adoption(self):
        ps, why = self.M.decode_ptpair('PTPAIR:1:A1B2C3D4:12:2:3-4-0;4-5-0', 12)
        self.assertIsNone(ps)
        self.assertEqual(why, 'overlap')

    def test_malformed_never_raises(self):
        for bad in (None, 5, b'x', '', ':', 'PTPAIR', 'PTPAIR:1:A1B2C3D4:12:1:' + 'x' * 5000):
            ps, why = self.M.decode_ptpair(bad, -1)
            self.assertIsNone(ps)
            self.assertIsInstance(why, str)


class StaticPins(unittest.TestCase):
    """PR-R28: no distance search; PR-R3/R4/R29/R30/R-names: no door, signal flag, name or location input anywhere in the recognition sources."""
    SOURCES = ('pseudo_turnback_contract.py', 'TsScoringPlugin/Handshake/Telemetry/PseudoTurnbackStaging/PseudoTurnbackQualifier.cs',
               'TsScoringPlugin/Handshake/Telemetry/PseudoTurnbackStaging/PseudoTurnbackPairCodec.cs')
    FORBIDDEN = (r'door', r'signal', r'distance', r'location', r'\bspeed\b', r'Math\.Abs', r'\babs\(', r'\bnames?\b', r'station_list', r'\bloc\b')

    def test_forbidden_identifiers_absent(self):
        for rel in self.SOURCES:
            code = _code(rel)
            for pat in self.FORBIDDEN:
                self.assertIsNone(re.search(pat, code, re.IGNORECASE), '%s has %s' % (rel, pat))

    def test_python_product_module_has_no_qualifying_function(self):
        code = _code('pseudo_turnback_contract.py')
        self.assertIsNone(re.search(r'def\s+(qualify|recognize|recognise|build_pair|find_pair|derive)', code))
        self.assertNotIn('pt_oracle', code)

    def test_no_product_python_imports_the_oracle(self):
        for fn in os.listdir(ROOT):
            if fn.endswith('.py'):
                self.assertNotIn('pt_oracle', _read(fn), fn)

    def test_qualifier_is_called_from_exactly_the_shared_files_only(self):
        # PQ-5: the qualifier is not duplicated into an adapter in this stage
        hits = [rel for rel in ('main.py', 'scoring_logic.py') if 'PseudoTurnbackQualifier' in _read(rel)]
        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
