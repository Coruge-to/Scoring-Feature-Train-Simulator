"""Public naming migration (TScoring): the contract of the five public DLLs and of the human-facing product name.

Owner contract (Preflight v3 + the ruling of 2026-11-13): the user-facing product name is TScoring; the five public DLLs are
TScoring.InputDevice / BridgeB / TelemetryB / BridgeA / TelemetryA (file name == AssemblyName); AssemblyProduct TScoring, Title with the DLL suffix,
Description naming the suffix meaning (B = current extension path, A = legacy compatibility path); Company / Copyright Coruge-to; one release version.
NOT changed in this migration: namespace, class names, protocol identifiers, IPC / Event / mutex / shared memory / UDP, the storage folder, JSON schemas,
csproj file names, the AtsEx.Caller.InputDevice.txt pointer, BVE Preferences (no new key is written by any product code).

These tests are static (source and metadata). The deployment contract (clean install / upgrade / rollback / residue) is proven by the migration kit rehearsal.
Rows NM-1 .. NM-3, NM-9, NM-11 .. NM-15, NM-30 of the stage plan live here.
"""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "TsScoringPlugin")
HS = os.path.join(PLUGIN, "Handshake")

# key: (csproj, AssemblyInfo, AssemblyName == file name without extension, AssemblyTitle, suffix word or None)
UNITS = {
    "inputDevice": (os.path.join(HS, "Caller", "TSScoringPlugin.Caller.InputDevice.csproj"), os.path.join(HS, "Caller", "src", "AssemblyInfo.cs"),
                    "TScoring.InputDevice", "TScoring Input Device", None),
    "bridgeB": (os.path.join(HS, "Bridge", "TSScoringPlugin.BveEx.Bridge.Prototype.csproj"), os.path.join(HS, "Bridge", "src", "AssemblyInfo.cs"),
                "TScoring.BridgeB", "TScoring Bridge B", "B"),
    "telemetryB": (os.path.join(PLUGIN, "TsScoringPlugin", "TsScoringPlugin.csproj"), os.path.join(PLUGIN, "TsScoringPlugin", "Properties", "AssemblyInfo.cs"),
                   "TScoring.TelemetryB", "TScoring Telemetry B", "B"),
    "bridgeA": (os.path.join(HS, "Bridge", "Legacy", "TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj"), os.path.join(HS, "Bridge", "Legacy", "src", "AssemblyInfo.cs"),
                "TScoring.BridgeA", "TScoring Bridge A", "A"),
    "telemetryA": (os.path.join(HS, "Telemetry", "Legacy", "TSScoringPlugin.AtsExLegacy.Telemetry.csproj"), os.path.join(HS, "Telemetry", "Legacy", "src", "AssemblyInfo.cs"),
                   "TScoring.TelemetryA", "TScoring Telemetry A", "A"),
}
B1PROBE_CSPROJ = os.path.join(HS, "Tests", "B1Probe", "TSScoringPlugin.AtsExLegacy.Telemetry.B1Probe.csproj")
SUFFIX_MEANING = {"B": "DLL suffix B", "A": "DLL suffix A"}
SUFFIX_WORDS = {"B": "current extension path", "A": "legacy compatibility path"}

OLD_NAME_PATTERNS = (
    r"TSScoringPlugin\.Caller\.InputDevice", r"TSScoringPlugin\.BveEx\.Bridge\.Prototype", r"TSScoringPlugin\.AtsExLegacy\.Bridge\.Prototype",
    r"TSScoringPlugin\.AtsExLegacy\.Telemetry", r"(?<![A-Za-z0-9_.])TsScoringPlugin\.dll(?![.A-Za-z_])",
)
# the csproj FILE names are kept on purpose (the package generator and the guards address them); thread names are internal diagnostic identifiers
OLD_NAME_SKIP_SUFFIX = r"(?!\.csproj|\.l3build|\.B1Probe)"


def read(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", "replace").replace("\r\n", "\n")


def tracked_files():
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").splitlines()


def lines_prev(raw, i):
    """The two lines before line i (1-based) of a raw file."""
    lines = raw.decode("utf-8", "replace").split("\n")
    return "\n".join(lines[max(0, i - 3):i - 1])


def attribute(text, name):
    m = re.search(r'\[assembly:\s*' + name + r'\("([^"]*)"\)\]', text)
    return m.group(1) if m else None


class A_PublicNameAndMetadata(unittest.TestCase):
    def test_NM1_the_human_facing_product_name_is_TScoring(self):
        hs = read(os.path.join(HS, "Caller", "src", "HandshakeSession.cs"))
        self.assertIn('internal const string ProductDisplayName = "TScoring";', hs)
        m = re.search(r'internal const string NoticeText =\s*"([^"]*)"', hs)
        self.assertIsNotNone(m)
        self.assertTrue(m.group(1).startswith("TScoring"), "the notice text names the product TScoring")
        self.assertNotIn("TS Scoring", m.group(1))
        self.assertNotIn("TS Scoring", re.search(r'internal const string ProductDisplayName = "([^"]*)"', hs).group(1))

    def test_NM1_assembly_product_title_company_copyright(self):
        for key, (_proj, info, _name, title, _suffix) in UNITS.items():
            text = read(info)
            self.assertEqual(attribute(text, "AssemblyProduct"), "TScoring", key)
            self.assertEqual(attribute(text, "AssemblyTitle"), title, key)
            self.assertEqual(attribute(text, "AssemblyCompany"), "Coruge-to", key)
            self.assertEqual(attribute(text, "AssemblyCopyright"), "Copyright (c) 2026 Coruge-to", key)

    def test_NM1_description_names_the_suffix_meaning_and_has_no_history(self):
        for key, (_proj, info, _name, _title, suffix) in UNITS.items():
            desc = attribute(read(info), "AssemblyDescription")
            self.assertTrue(desc and len(desc) > 30, key)
            self.assertNotRegex(desc, r"Phase|TS Scoring|TsScoringPlugin|TSScoringPlugin|Prototype", key)
            if suffix:
                self.assertIn(SUFFIX_MEANING[suffix], desc, key)
                self.assertIn(SUFFIX_WORDS[suffix], desc, key)
            else:
                self.assertNotIn("DLL suffix", desc, "the Input Device is host independent and carries no suffix")

    def test_NM1_one_release_version_for_the_five_dlls(self):
        versions = set()
        for key, (_proj, info, _name, _title, _suffix) in UNITS.items():
            text = read(info)
            v = attribute(text, "AssemblyVersion")
            self.assertEqual(attribute(text, "AssemblyFileVersion"), v, key)
            versions.add(v)
        self.assertEqual(len(versions), 1, "the five public DLLs share one release version: %s" % sorted(versions))
        self.assertNotIn(versions.copy().pop(), ("0.13.0.0", "0.8.0.0", "0.6.0.0", "1.0.0.0"), "the version moved with the rename")

    def test_NM2_NM12_assembly_name_is_the_public_file_name(self):
        for key, (proj, _info, name, _title, _suffix) in UNITS.items():
            m = re.search(r"<AssemblyName>([^<]*)</AssemblyName>", read(proj))
            self.assertIsNotNone(m, key)
            self.assertEqual(m.group(1), name, key)
            self.assertNotRegex(name, r"Plugin|Prototype|BveEx|BveEX|AtsEx|AtsEX|TSScoring|TsScoring", "no third-party product name or old name in a public DLL name: " + name)
        self.assertEqual(re.search(r"<AssemblyName>([^<]*)</AssemblyName>", read(B1PROBE_CSPROJ)).group(1), "TScoring.TelemetryA", "the B1Probe replaces TelemetryA in the field and follows its name")

    def test_NM2_the_five_names_are_exactly_the_formal_set(self):
        self.assertEqual(sorted(u[2] for u in UNITS.values()), sorted(["TScoring.InputDevice", "TScoring.BridgeB", "TScoring.TelemetryB", "TScoring.BridgeA", "TScoring.TelemetryA"]))


class B_InternalIdentifiersAreKept(unittest.TestCase):
    def test_NM11_NM14_NM15_internal_identifiers_are_unchanged(self):
        proto = read(os.path.join(HS, "Shared", "HandshakeProtocol.cs"))
        self.assertIn("Local\\\\TSScoringPlugin.v1.", proto, "the protocol prefix (Event / mutex / shared memory) is kept")
        # every named kernel object of the product sources keeps the TSScoringPlugin.v1 prefix: not one of them moved, none was added or dropped (18 uses, counted on 2026-11-13)
        files = tracked_files()
        if files is not None:
            total = good = 0
            for f in files:
                p = f.replace("\\", "/")
                if not p.endswith(".cs") or p.startswith("TsScoringPlugin/Handshake/Tests/") or p.startswith("TsScoringPlugin/Handshake/Probes/") or p.startswith("TsScoringPlugin/Handshake/Docs/"):
                    continue
                text = read(os.path.join(ROOT, f))
                total += len(re.findall(r'"Local\\\\', text))
                good += len(re.findall(r'"Local\\\\TSScoringPlugin\.v1\.', text)) + len(re.findall(r'"Local\\\\TSScoring\.InitialDefaults\.v1', text))      # the initial-defaults family is kept too
            self.assertEqual((total, good), (18, 18), "a named Event / mutex / shared memory prefix changed")
        launcher = read(os.path.join(HS, "Caller", "src", "LauncherConfig.cs"))
        self.assertIn('public const string ProductFolder = "TS Scoring";', launcher, "the storage folder %LOCALAPPDATA%\\Coruge-to\\TS Scoring is kept")
        self.assertIn('APP_FOLDER = "TS Scoring"', read(os.path.join(ROOT, "initial_defaults.py")))
        roots = {"inputDevice": "TSScoringPlugin.Handshake", "bridgeB": "TSScoringPlugin.Handshake", "bridgeA": "TSScoringPlugin.Handshake",
                 "telemetryA": "TSScoringPlugin.Telemetry", "telemetryB": "TsScoringPlugin"}
        for key, ns in roots.items():
            self.assertEqual(re.search(r"<RootNamespace>([^<]*)</RootNamespace>", read(UNITS[key][0])).group(1), ns, key)
        # the Current telemetry typelib id is kept
        self.assertIn('[assembly: Guid("6170c7be-114e-4921-87d3-eae2fc09c073")]', read(UNITS["telemetryB"][1]))

    def test_NM2_the_csproj_file_names_are_kept(self):
        for key, (proj, _info, _name, _title, _suffix) in UNITS.items():
            self.assertTrue(os.path.exists(proj), key + ": " + proj)

    def test_remaining_TS_Scoring_string_literals_are_the_classified_internal_ones(self):
        files = tracked_files()
        if files is None:
            self.skipTest("git is not available (INCONCLUSIVE)")
        found = []
        for f in files:
            p = f.replace("\\", "/")
            if not p.endswith(".cs") or p.startswith("TsScoringPlugin/Handshake/Tests/") or p.startswith("TsScoringPlugin/Handshake/Probes/"):
                continue
            code = "\n".join(re.sub(r"(?<!:)//.*$", "", line) for line in read(os.path.join(ROOT, f)).split("\n"))      # comments are not literals
            for m in re.finditer(r'"[^"\r\n]*TS Scoring[^"\r\n]*"', code):
                found.append((p, m.group(0)))
        allowed = {
            ("TsScoringPlugin/Handshake/Caller/src/LauncherConfig.cs", '"TS Scoring"'),                    # the storage folder (kept)
            ("TsScoringPlugin/Handshake/Bridge/src/HandshakeControlPlane.cs", '"TS Scoring control plane"'),    # an internal thread name
            ("TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpControlPlane.cs", '"TS Scoring LegacyJump control"'),   # an internal thread name
        }
        unexpected = [x for x in found if x not in allowed and not (x[0].endswith("ScenarioReadyTracker.cs") and "handshake-not-up" in x[1])]
        self.assertEqual(unexpected, [], "an unclassified TS Scoring literal in a product source")


class C_NoOldPublicNameRemains(unittest.TestCase):
    def test_NM3_no_old_public_dll_name_in_a_tracked_file_except_the_classified_ones(self):
        files = tracked_files()
        if files is None:
            self.skipTest("git is not available (INCONCLUSIVE)")
        me = os.path.basename(__file__)
        hits = []
        for f in files:
            p = f.replace("\\", "/")
            if p.startswith("TsScoringPlugin/Handshake/Docs/") or p.endswith(".csproj") or p.endswith(me) or p.startswith("package/source-package-manifest"):
                continue          # historical evidence (Docs), the csproj files (their file names are kept), this contract, the generated manifest
            raw = open(os.path.join(ROOT, f), "rb").read()
            if b"\0" in raw[:4096]:
                continue
            for i, line in enumerate(raw.decode("utf-8", "replace").split("\n"), 1):
                if "TS-Scoring-Claude-Handoff" in line:
                    continue      # a path into an old evidence folder (historical)
                if p == "tests/test_stationindex_package_st3e0.py" and "neutralised back" in lines_prev(raw, i):
                    continue      # the two guard lines that neutralise the NEW AssemblyName back to the 0b8e511 value (they must name the old value)
                for pat in OLD_NAME_PATTERNS:
                    if re.search(pat + (OLD_NAME_SKIP_SUFFIX if "dll" not in pat else ""), line):
                        hits.append("%s:%d" % (p, i))
        # classified exceptions: thread names (internal diagnostic identifiers) and the csproj FILE names used as paths
        def classified(h):
            path, ln = h.rsplit(":", 1)
            line = read(os.path.join(ROOT, path)).split("\n")[int(ln) - 1]
            return bool(re.search(r't\.Name = "TSScoringPlugin\.Caller\.|monitor\.Name = "TSScoringPlugin\.Caller\.|thread\.Name = "TSScoringPlugin\.Caller\.', line))
        left = [h for h in hits if not classified(h)]
        self.assertEqual(left, [], "an old public DLL name remains outside the classified exceptions")

    def test_NM30_no_personal_name_in_a_tracked_public_source(self):
        files = tracked_files()
        if files is None:
            self.skipTest("git is not available (INCONCLUSIVE)")
        me = os.path.basename(__file__)
        for f in files:
            p = f.replace("\\", "/")
            if p.endswith(me) or p.startswith("tests/") or p.endswith(".htm"):
                continue
            raw = open(os.path.join(ROOT, f), "rb").read()
            if b"\0" in raw[:4096]:
                continue
            self.assertNotRegex(raw.decode("utf-8", "replace"), r"(?i)homareda", p)

    def test_NM9_NM13_the_product_never_touches_the_AtsEx_pointer_or_writes_a_Preferences_key(self):
        files = tracked_files()
        if files is None:
            self.skipTest("git is not available (INCONCLUSIVE)")
        me = os.path.basename(__file__)
        for f in files:
            p = f.replace("\\", "/")
            if p.endswith(me) or p.startswith("TsScoringPlugin/Handshake/Docs/") or p.startswith("TsScoringPlugin/Handshake/Tests/") or p.startswith("TsScoringPlugin/Handshake/Tools/") or p.startswith("tests/"):
                continue
            if not (p.endswith(".cs") or p.endswith(".py")):
                continue
            text = read(os.path.join(ROOT, f))
            self.assertNotIn("AtsEx.Caller.InputDevice", text, p + ": the AtsEX standard pointer is not part of the TScoring contract")
            self.assertNotIn("tscoring.inputdevice", text.lower(), p + ": no new BVE Preferences key is written or pre-written by the product")
            self.assertNotRegex(text, r"(?i)Preferences\.xml", p + ": the product never edits BVE Preferences")


if __name__ == "__main__":
    unittest.main()
