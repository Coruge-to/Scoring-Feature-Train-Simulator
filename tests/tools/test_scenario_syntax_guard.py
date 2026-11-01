"""Tests of the scenario line-grammar guard (test equipment; run from the Stage 1 tool folder).
usage: python -m unittest test_scenario_syntax_guard   (env TBG_SCENARIOS = the Scenarios folder, TBG_DEFECTIVE = the defective evidence file)"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_syntax_guard as G  # noqa: E402

ROOT = os.environ.get("TBG_SCENARIOS", r"C:\Users\tsuru\Documents\Bvets\Scenarios")
DEFECTIVE = os.environ.get("TBG_DEFECTIVE", r"C:\Users\tsuru\Documents\TS-Scoring-Claude-Handoff\pseudo-turnback-live-route-load-smoke-v1-20261101-092419\scenario-fix\evidence\iida_sanmpe_tbg_pt4_v1.defective.txt")
TARGET = os.path.join(ROOT, "iida_sanmpe_tbg_pt4_v1.txt")
REFERENCE = os.path.join(ROOT, "iida_sanmpe_b3zero_v1.txt")
OTHER_NORMAL = ("iida_sanmpe_b3zero_v1.txt", "iida_sanmpe_diag_o3_t.txt", "iida_sanmpe_r53_close330_v1.txt")
FORBID = (G.SHA_SUPERSEDED_SCENARIO,)


def read(path):
    with open(path, "rb") as fh:
        return fh.read()


def ids(findings):
    return {i for i, _ in findings}


class A_PositiveControls(unittest.TestCase):
    def test_SG_the_live_canonical_scenario_passes_every_check(self):
        self.assertEqual(G.check_scenario(TARGET, REFERENCE, ROOT, G.SHA_LIVE_SCENARIO, FORBID), [])
        self.assertEqual(G.sha256_bytes(read(TARGET)), G.SHA_LIVE_SCENARIO)

    def test_SG_the_existing_normal_scenarios_have_the_same_structure(self):
        """The reference itself is clean. The two other normal scenarios of the live folder have the same line structure; they differ ONLY in two conventions that the guard deliberately ties to the
        reference (b3zero): they have no BOM (SG-10) and another Author text (SG-06). Nothing structural (SG-01..05, 07, 08, 09) fires for them."""
        self.assertEqual(G.check_scenario(REFERENCE, REFERENCE, ROOT), [])
        for name in OTHER_NORMAL[1:]:
            with self.subTest(name=name):
                found = G.check_scenario(os.path.join(ROOT, name), REFERENCE, ROOT)
                self.assertEqual({i for i, _ in found} - {"SG-10", "SG-06"}, set(), found)
                self.assertEqual([m for i, m in found if i == "SG-10"], ["no UTF-8 BOM"])

    def test_SG_the_author_line_is_one_line_and_equals_the_reference(self):
        text = read(TARGET).decode("utf-8-sig").split("\r\n")
        authors = [l for l in text if l.startswith("Author = ")]
        ref = [l for l in read(REFERENCE).decode("utf-8-sig").split("\r\n") if l.startswith("Author = ")]
        self.assertEqual(len(authors), 1)
        self.assertEqual(authors, ref)

    def test_SG_the_superseded_scenario_is_nowhere_below_the_live_scenarios(self):
        self.assertEqual(G.scan_for_forbidden_sha(ROOT, FORBID), [])


class B_NegativeControls(unittest.TestCase):
    """Each control starts from the canonical bytes and damages ONE thing; the expected check must fire (a guard that cannot fail is no guard)."""

    def check(self, raw, **kw):
        return G.check_scenario_bytes(raw, read(REFERENCE), ROOT, kw.get("expected", None), FORBID)

    def lines(self):
        return read(TARGET).decode("utf-8-sig").split("\r\n")

    def build(self, lines, bom=True, eol="\r\n"):
        return (b"\xef\xbb\xbf" if bom else b"") + eol.join(lines).encode("utf-8")

    def test_SG_the_real_defect_the_author_split_into_one_character_lines_is_caught(self):
        found = self.check(read(DEFECTIVE))
        self.assertTrue({"SG-01", "SG-03", "SG-06", "SG-07"} <= ids(found), found)
        self.assertGreaterEqual(sum(1 for i, m in found if i == "SG-07" and "invalid single CJK line" in m), 4)

    def test_SG_author_split_in_my_own_way_is_caught(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Author = "))
        value = lines[k][len("Author = "):]
        lines[k:k + 1] = ["Author = " + value[:1]] + list(value[1:])
        self.assertTrue({"SG-07", "SG-06"} <= ids(self.check(self.build(lines))))

    def test_SG_keys_in_a_different_order_are_caught(self):
        lines = self.lines()
        i, j = 2, 3
        lines[i], lines[j] = lines[j], lines[i]
        self.assertIn("SG-05", ids(self.check(self.build(lines))))

    def test_SG_an_unknown_key_is_caught(self):
        lines = self.lines()
        lines.insert(len(lines) - 1, "Foo = bar")
        self.assertTrue({"SG-04", "SG-01"} <= ids(self.check(self.build(lines))))

    def test_SG_a_duplicate_key_is_caught(self):
        lines = self.lines()
        lines.insert(len(lines) - 1, "Title = twice")
        self.assertIn("SG-04", ids(self.check(self.build(lines))))

    def test_SG_a_missing_key_is_caught(self):
        lines = [l for l in self.lines() if not l.startswith("Comment = ")]
        self.assertTrue({"SG-04", "SG-01"} <= ids(self.check(self.build(lines))))

    def test_SG_a_stray_japanese_line_is_caught(self):
        lines = self.lines()
        lines.insert(len(lines) - 1, "\u98ef")
        found = self.check(self.build(lines))
        self.assertIn("SG-07", ids(found))

    def test_SG_a_stray_ascii_line_is_caught(self):
        lines = self.lines()
        lines.insert(len(lines) - 1, "x")
        self.assertIn("SG-07", ids(self.check(self.build(lines))))

    def test_SG_a_separator_without_spaces_is_caught(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Title = "))
        lines[k] = lines[k].replace(" = ", "=", 1)
        found = self.check(self.build(lines))
        self.assertTrue({"SG-03", "SG-08"} <= ids(found) or "SG-07" in ids(found), found)

    def test_SG_the_header_must_be_exact(self):
        lines = self.lines()
        lines[0] = "Bvets Scenario 2.01"
        self.assertIn("SG-02", ids(self.check(self.build(lines))))
        lines = self.lines()
        lines[1] = " "
        self.assertIn("SG-02", ids(self.check(self.build(lines))))

    def test_SG_lf_only_cr_only_and_no_bom_are_caught(self):
        lines = self.lines()
        self.assertIn("SG-10", ids(self.check(self.build(lines, eol="\n"))))
        self.assertIn("SG-10", ids(self.check(self.build(lines, eol="\r"))))
        self.assertIn("SG-10", ids(self.check(self.build(lines, bom=False))))

    def test_SG_a_missing_final_crlf_and_an_extra_blank_line_are_caught(self):
        lines = self.lines()
        self.assertIn("SG-10", ids(self.check(self.build(lines[:-1]))))
        self.assertIn("SG-10", ids(self.check(self.build(lines + [""]))))

    def test_SG_invalid_utf8_nul_and_the_replacement_character_are_caught(self):
        raw = read(TARGET)
        self.assertIn("SG-10", ids(self.check(raw[:40] + b"\xff\xfe" + raw[42:])))
        self.assertIn("SG-10", ids(self.check(raw[:40] + b"\x00" + raw[41:])))
        self.assertIn("SG-10", ids(self.check(raw.replace(b"Title = ", "Title = \ufffd".encode("utf-8"), 1))))

    def test_SG_an_unresolved_route_and_vehicle_are_caught(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Route = "))
        lines[k] = "Route = iida_hosenku\\no_such_route.txt"
        self.assertIn("SG-09", ids(self.check(self.build(lines))))
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Vehicle = "))
        lines[k] = "Vehicle = Uchibo20\\E217r\\no_such_vehicle.txt"
        found = self.check(self.build(lines))
        self.assertTrue({"SG-09", "SG-08"} <= ids(found), found)

    def test_SG_another_vehicle_or_image_is_caught_by_the_structure_match(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Image = "))
        lines[k] = "Image = something.png"
        self.assertIn("SG-08", ids(self.check(self.build(lines))))

    def test_SG_a_changed_author_is_caught(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Author = "))
        lines[k] = "Author = someone"
        self.assertIn("SG-06", ids(self.check(self.build(lines))))
        lines[k] = "Author = "
        self.assertIn("SG-06", ids(self.check(self.build(lines))))

    def test_SG_a_changed_comment_is_a_sha_difference_not_a_syntax_error(self):
        lines = self.lines()
        k = next(i for i, l in enumerate(lines) if l.startswith("Comment = "))
        lines[k] = "Comment = edited"
        raw = self.build(lines)
        self.assertEqual(self.check(raw), [], "the grammar is fine")
        found = G.check_scenario_bytes(raw, read(REFERENCE), ROOT, G.SHA_LIVE_SCENARIO, FORBID)
        self.assertEqual(ids(found), {"SG-11"}, "but the file is no longer the live canonical one")

    def test_SG_the_superseded_scenario_is_rejected_by_sha(self):
        found = G.check_scenario_bytes(read(DEFECTIVE), read(REFERENCE), ROOT, G.SHA_LIVE_SCENARIO, FORBID)
        self.assertEqual(G.sha256_bytes(read(DEFECTIVE)), G.SHA_SUPERSEDED_SCENARIO, "the evidence file is the superseded scenario")
        self.assertTrue({"SG-11", "SG-12"} <= ids(found), found)

    def test_SG_the_directory_scan_finds_a_copy_of_the_superseded_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = os.path.join(tmp, "a", "b")
            os.makedirs(sub)
            with open(os.path.join(sub, "copy.txt"), "wb") as fh:
                fh.write(read(DEFECTIVE))
            with open(os.path.join(tmp, "innocent.txt"), "wb") as fh:
                fh.write(read(TARGET))
            self.assertEqual(G.scan_for_forbidden_sha(tmp, FORBID), [os.path.join(sub, "copy.txt")])


if __name__ == "__main__":
    unittest.main()
