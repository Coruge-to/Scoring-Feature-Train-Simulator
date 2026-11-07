"""Legacy sway SOURCE lookup (SHD-L-01 failure, Owner ruling LSR-D1..D3) - an executable contract (RED / GUARD), static checks of the product sources.

THE FINDING (reproduced offline with the real Legacy BveTypes wrappers, Test-SwaySourceLegacyRealL3.ps1 RW02/RW03)
  The Legacy lookup was  foreach (AssistantBase item in ...Items) { SwayGauge gauge = item as SwayGauge; if (gauge != null) ... }  inside  catch { figure = null; }.
  ClassWrapperBase.operator != is left.Equals(right): a NULL left operand throws NullReferenceException. `item as SwayGauge` is null for the first item (the time table), so the lookup threw
  on its first item, the catch hid it and the figure was never found: pending:no-source for ever (SHD-L-01).
THE CONTRACT
  * Legacy only: the Current sender, the shared SwayStateReader, the Legacy session/API/contract, the Python side, the Caller cap (192) and the official score path are NOT touched.
  * The wrapper path first (no wrapper operator ==/!=), the bounded raw-list fallback only when the wrapper path failed, never mixed; both failed = unavailable (never a 0).
  * A failure is never swallowed: its stage and the exception TYPE NAME (never message / stack) are recorded once per scenario; an unresolved source is looked for again on every 30th Tick.
  * The behaviours are tested by Test-SwaySourceLegacyL3.ps1 (fake hosts, 41 checks) and Test-SwaySourceLegacyRealL3.ps1 (real wrappers, 7 checks); this file checks the SOURCES.
Naming: test_LS* = RED on the baseline e2e2de6 (each fails with a reason code "CODE: ..."); test_LG* = GUARD (passes before and after)."""
import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HS = os.path.join(ROOT, "TsScoringPlugin", "Handshake")
LEG = os.path.join(HS, "Telemetry", "Legacy")
SRC = os.path.join(LEG, "src", "LegacySwaySource.cs")
EXT = os.path.join(LEG, "src", "LegacyTelemetryExtension.cs")
CSPROJ = os.path.join(LEG, "TSScoringPlugin.AtsExLegacy.Telemetry.csproj")
CUR_CSPROJ = os.path.join(ROOT, "TsScoringPlugin", "TsScoringPlugin", "TsScoringPlugin.csproj")
PS_FAKE = os.path.join(HS, "Tests", "Test-SwaySourceLegacyL3.ps1")
PS_REAL = os.path.join(HS, "Tests", "Test-SwaySourceLegacyRealL3.ps1")


def read(path):
    with open(path, encoding="utf-8", newline="") as h:
        return h.read()


def lf_sha(path):
    data = open(path, "rb").read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()


def region(text, start, end):
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


# the baseline (commit e2e2de6, LF) fingerprints of everything this change must NOT touch
UNTOUCHED = {
    "TsScoringPlugin/TsScoringPlugin/Class1.cs": "5C0AE0E6C27F9D61D5012F1B2BC383DF012A9941472150863497D37210BA17C2",
    "TsScoringPlugin/Handshake/Telemetry/Shared/SwayStateReader.cs": "C0F9F76DCD75B12A4D843D81C2BA1E8AB90618ABDC176175A46BD3346AD958B6",
    "TsScoringPlugin/TsScoringPlugin/TsScoringPlugin.csproj": "4B043231853AB201B084362C43498E340704F12DFD1FA51F22636903D9DE83D3",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs": "8D463E506A372C18A8C6C24F3563909C19943D3D63FEB6C2B03ABAFB47A9958A",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs": "DF608B0DCB9A1B7296926CEC1F400DC617CF353D664CBFBB3790D877BB96BBD9",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs": "94D1E803232011C3B899F1712C385CC46BAF93DCC289C84E7CF43596D6D79FE4",
    "TsScoringPlugin/Handshake/Caller/src/AppProcessManager.cs": "3C6B23EF471DE544B6E1EB3EA7A3CB4ECB59470F6E2917474856CBEA7307CAE1",
    "scoring_logic.py": "383A1C9558720C79DD4FF41F77576E9DB0AB2FC30BDC384FAEC7F7964C322ABA",
    "telemetry_contract.py": "50F6B82C17FADECB8AFEF3F5E8C4AFFFAA5DE3FE183810D75F3DD5B6C848783B",
    "sway_shadow.py": "F23887197AE5E499DE630FE1F300F1272551B5E664D38C9AB7BE71124F382E9F",   # intended change of the reverse-stop stage (Owner ruling 2026-11-08): the stop-window peak is the largest |state| of either sign
    "managed_input.py": "55E91B46A96DE2CD7563B4970BCB00407C9E506FD762BB5B3453C7A0DFCE4B2C",
    "hud_ui.py": "22277462231E19BF4E1E8C0149AAA58128F0CE61767B2851DDEBADEFB3B9221A",
    "main.py": "06FEDA7CFAAED1CB8D16BE73BC7D1D1B98774266B3A793DB1F83E3A4CB557F46",
    "managed_hud.py": "FBA17C9C755C3250DA179EB04B51D2AAAEDA91B373729D01DFC066A61A0B57E4",
}


def has(needle, text, msg):
    if needle not in text:
        raise AssertionError(msg)


def regex(text, pattern, msg):
    if re.search(pattern, text) is None:
        raise AssertionError(msg)


def is_none(match, msg):
    if match is not None:
        raise AssertionError(msg)


def eq(want, got, msg):
    if want != got:
        raise AssertionError("%s (want %r, got %r)" % (msg, want, got))


def less(a, b, msg):
    if not a < b:
        raise AssertionError(msg)


def at_least(a, b, msg):
    if not a >= b:
        raise AssertionError(msg)


def need(path, code):
    if not os.path.exists(path):
        raise AssertionError("%s: %s does not exist" % (code, os.path.relpath(path, ROOT)))
    return read(path)


class LS_Red(unittest.TestCase):
    def test_LS01_the_finder_source_exists_and_is_linked_into_the_legacy_project_only(self):
        src = need(SRC, "NO-FINDER-SRC")
        has("class LegacySwaySourceFinder", src, "NO-FINDER-SRC: the finder class is missing")
        has("class LegacySwayProvider", src, "NO-FINDER-SRC: the provider class is missing")
        has('<Compile Include="src\\LegacySwaySource.cs" />', read(CSPROJ), "NO-FINDER-SRC: the Legacy project does not compile it")
        self.assertTrue("LegacySwaySource" not in read(CUR_CSPROJ), "NO-FINDER-SRC: the Current project must not compile the Legacy finder")

    def test_LS02_a_failure_of_the_lookup_is_never_swallowed(self):
        ext = read(EXT)
        is_none(re.search(r"catch\s*\{\s*figure\s*=\s*null\s*;\s*\}", ext), "SWALLOWED-FAILURE: the lookup is still 'catch { figure = null; }'")
        has("class AtsExSwayHostAccess", ext, "SWALLOWED-FAILURE: no host access class")

    def test_LS03_the_host_access_never_uses_a_wrapper_operator(self):
        ext = read(EXT)
        has("class AtsExSwayHostAccess", ext, "NULL-UNSAFE-WRAPPER-OPERATOR: no host access class")
        body = region(ext, "internal sealed class AtsExSwayHostAccess", "/// <summary>The Legacy API read into ILegacyApi.")
        has("is SwayGauge", body, "NULL-UNSAFE-WRAPPER-OPERATOR: the figure is not tested with 'is'")
        self.assertTrue("as SwayGauge" not in body, "NULL-UNSAFE-WRAPPER-OPERATOR: 'as SwayGauge' followed by a wrapper comparison is the SHD-L-01 failure")
        code = re.sub(r"//[^\n]*", "", re.sub(r"/// [^\n]*", "", body))
        is_none(re.search(r"\b(gauge|item|wrapperItem|form|drawer|wrapperMainForm|wrapperAssistantDrawer|mainForm|val)\s*(==|!=)\s*null", code), "NULL-UNSAFE-WRAPPER-OPERATOR: a '== null' / '!= null' test in the host access (wrapper operator)")

    def test_LS04_wrapper_first_raw_only_after_the_wrapper_failed(self):
        src = need(SRC, "NO-RAW-FALLBACK")
        find = region(src, "internal LegacySwaySourceResult Find()", "internal static LegacySwaySourceResult VersionMismatchResult()")
        less(find.index("ProbeWrapper()"), find.index("ProbeRaw()"), "NO-RAW-FALLBACK: the wrapper path is not tried first")
        regex(find, r"SelectedPath = \"wrapper\";\s*result\.Figure = result\.Wrapper\.Figure;\s*return result;", "NO-RAW-FALLBACK: a wrapper success does not return before the raw path")
        has('SelectedPath = "raw-list"', find, "NO-RAW-FALLBACK: no raw-list selection")
        for token in ('"l"', '"ar"', '"a"', '"b4"'):
            has(token, src, "NO-RAW-FALLBACK: the fixed raw member name %s is missing" % token)

    def test_LS05_only_the_type_name_of_an_exception_is_recorded(self):
        src = need(SRC, "LEAKS-MESSAGE")
        code = re.sub(r"//[^\n]*", "", src)
        for bad in (".Message", ".StackTrace", ".Source", ".TargetSite", ".Data"):
            self.assertTrue(bad not in code, "LEAKS-MESSAGE: the finder uses '%s' (an exception message / stack / free text)" % bad)
        is_none(re.search(r"\b(ex|e|exception|tie)\.ToString\(", code), "LEAKS-MESSAGE: an exception is turned into text with ToString()")
        has("FullName", code, "LEAKS-MESSAGE: the exception type name is not recorded")

    def test_LS06_the_failure_stage_vocabulary(self):
        src = need(SRC, "NO-STAGES")
        for stage in ("mainform-null", "assistantdrawer-null", "items-null", "items-enumeration-failure", "type-cast-failure", "no-sway-item", "version-mismatch",
                      "field-signature-mismatch", "reflection-exception", "unexpected-exception"):
            has('"%s"' % stage, src, "NO-STAGES: the failure stage '%s' is missing" % stage)

    def test_LS07_retry_cache_boundary_and_once_per_scenario(self):
        src = need(SRC, "NO-ONCE")
        regex(src, r"RetryEveryTicks\s*=\s*30", "NO-ONCE: the 30-Tick retry contract is not kept")
        has("MaxDiagnosticsPerScenario", src, "NO-ONCE: the per-scenario diagnostic limit is missing")
        has("signature == lastSignature", src, "NO-ONCE: the same outcome is not suppressed")
        has("reader.Reset();", src, "NO-ONCE: no reset at a scenario boundary")
        has("reader.Status == SwayStatus.Pending", src, "NO-ONCE: the cache (only a pending source is looked up) is missing")

    def test_LS08_dispose_releases_the_sway_state(self):
        ext = read(EXT)
        has("ReleaseSway()", ext, "NO-RELEASE: no release method")
        dispose = region(ext, "public override void Dispose()", "private void OnHeartbeat")
        has("hostApi.ReleaseSway()", dispose, "NO-RELEASE: Dispose does not release the sway state")

    def test_LS09_the_diagnostic_goes_to_the_per_process_log_in_roles_under_the_cap(self):
        src = need(SRC, "NO-DIAG")
        for role in ("summary", "exception", "wrapper", "raw", "reader"):
            has("role=" + role, src, "NO-DIAG: the diagnostic role '%s' is missing" % role)
        regex(src, r"MaxDetailChars\s*=\s*150", "NO-DIAG: the line cap constant is missing")
        has("names_cut=", src, "NO-DIAG: what is left out is not counted")
        has('diag("TEL_SWAY_SRC"', src, "NO-DIAG: the diagnostic event name")
        for field in ("selected_path=", "failure_stage=", "exception_type=", "bve_version=", "entry=legacy", "items_count=", "sway_found=", "mainform_null=", "assistantdrawer_null=", "items_null="):
            has(field, src, "NO-DIAG: the field '%s' is missing" % field)

    def test_LS13_the_host_adapter_has_no_reflection_and_the_host_reader_is_in_the_finder_source(self):
        ext = re.sub(r"//[^\n]*", "", read(EXT))
        for bad in ("PropertyInfo", "GetProperty(", "GetField(", "GetMethod(", "BindingFlags", "MainFormSource;"):
            self.assertTrue(bad not in ext, "NO-HOST-READER: the host adapter contains '%s' (reflection / a compile-time Forms reference)" % bad)
        has("LegacySwayHostReader.ReadMainFormSource(hacker)", ext, "NO-HOST-READER: the adapter does not read MainFormSource through the host reader")
        src = need(SRC, "NO-HOST-READER")
        has("class LegacySwayHostReader", src, "NO-HOST-READER: no host reader class")

    def test_LS11_the_unknown_version_touches_nothing_before_the_find(self):
        src = need(SRC, "NO-VERSION-GUARD")
        attempt = region(src, "private void Attempt()", "private void Emit(")
        less(attempt.index("SwayStatus.VersionUnsupported"), attempt.index("finder.Find()"), "NO-VERSION-GUARD: the version is not checked before the find")
        has("VersionMismatchResult()", attempt, "NO-VERSION-GUARD: no version-mismatch result")


    def test_LS12_the_project_has_exactly_one_new_compile_line_and_no_new_reference(self):
        proj = read(CSPROJ)
        eq(1, proj.count("src\\LegacySwaySource.cs"), "NO-FINDER-SRC: the project does not list the finder exactly once")
        self.assertTrue('System.Windows.Forms' not in proj, "NO-FINDER-SRC: the product DLL must not get a new assembly reference (MainFormSource is read by reflection on the interface)")


class LG_Guard(unittest.TestCase):
    def test_LG01_everything_that_must_not_change_is_byte_identical_to_the_baseline(self):
        for rel, want in UNTOUCHED.items():
            self.assertEqual(want, lf_sha(os.path.join(ROOT, rel.replace("/", os.sep))), "the baseline file changed: " + rel)

    def test_LG02_the_finder_has_no_coupling_to_the_score(self):
        if not os.path.exists(SRC):
            return      # a guard: nothing to couple yet (the baseline)
        src = re.sub(r"//[^\n]*", "", read(SRC))
        for word in ("penalty", "score", "history", "checkpoint", "CalcG", "BveG", "result.json", "jerk"):
            self.assertTrue(word.lower() not in src.lower(), "the finder mentions '%s'" % word)

    def test_LG03_the_caller_cap_is_still_192(self):
        self.assertIn("MaxStderrLineChars = 192", read(os.path.join(HS, "Caller", "src", "AppProcessManager.cs")))

    def test_LG04_the_finder_writes_nothing_and_calls_no_host_method_but_getters(self):
        if not os.path.exists(SRC):
            return
        src = re.sub(r"//[^\n]*", "", read(SRC))
        for bad in ("SetValue(", "File.", "Stream", "Process.", "Thread", "Timer", "Socket", "Invoke(drawer, new object"):
            self.assertTrue(bad not in src, "the finder contains '%s'" % bad)

    def test_LG05_the_offline_behaviour_tests_exist(self):
        fake = need(PS_FAKE, "NO-PS-TESTS")
        real = need(PS_REAL, "NO-PS-TESTS")
        at_least(len(re.findall(r"Check 'LS\d+", fake)), 40, "NO-PS-TESTS: too few fake-host checks")
        at_least(len(re.findall(r"Check 'RW\d+", real)), 7, "NO-PS-TESTS: too few real-wrapper checks")


if __name__ == "__main__":
    unittest.main()
