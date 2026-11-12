"""INITIAL-DEFAULTS Commit 2 (Owner contract 2026-11-10): static facts of the Caller's Properties entry. RED = fails on 98e4698; messages start with 'ID2C-RED'.

  * the Caller starts the 'initial defaults' window ONLY through the existing launcher.json contract (LauncherConfigLoader): python / script / working directory, argument --initial-defaults; no public DLL file name, no registry, no
    WinForms window of its own (the window is the Python process), no WaitForExit in the Properties path (the callback returns at once).
  * Configure keeps the status MessageBox only as the fallback of a failed start; it never lets an exception reach BVE.
  * the file is part of the project (explicit Compile list) and the sources stay ASCII-only (the Japanese notice is written with \\u escapes)."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CALLER = os.path.join(ROOT, "TsScoringPlugin", "Handshake", "Caller")


def read(*parts):
    p = os.path.join(*parts)
    if not os.path.exists(p):
        raise AssertionError("ID2C-RED: %s does not exist" % os.path.relpath(p, ROOT))
    with open(p, encoding="utf-8") as f:
        return f.read()


class CallerStatic(unittest.TestCase):
    def test_the_launcher_uses_the_launcher_json_contract_only(self):
        src = read(CALLER, "src", "InitialDefaultsLauncher.cs")
        self.assertIn("LauncherConfigLoader", src)
        self.assertIn("--initial-defaults", src)
        for field in ("PythonExecutable", "ScriptPath", "WorkingDirectory"):
            self.assertIn(field, src, "ID2C-RED: the launcher does not use %s" % field)
        self.assertIn("psi.FileName = config.PythonExecutable;", src, "ID2C-RED: python is not the launcher.json pythonExecutable")
        self.assertIn("psi.WorkingDirectory = config.WorkingDirectory;", src)

    def test_no_public_dll_name_registry_or_form_in_the_launcher(self):
        src = read(CALLER, "src", "InitialDefaultsLauncher.cs")
        for bad in (r"Microsoft\.Win32", r"\bRegistry", r"\bnew\s+Form\b", r":\s*Form\b", r"WaitForExit", r"ShowDialog"):
            self.assertIsNone(re.search(bad, src, re.I), "ID2C-RED: the launcher must not contain %r" % bad)
        for literal in re.findall(r'"(?:[^"\\]|\\.)*"', src):                  # no string literal may name a product file (the namespace is a technical identifier, not a literal)
            self.assertIsNone(re.search(r"plugin|\.dll|caller", literal, re.I), "ID2C-RED: the string literal %s names a product file" % literal)

    def test_the_child_is_not_redirected_and_has_no_window(self):
        src = read(CALLER, "src", "InitialDefaultsLauncher.cs")
        self.assertIn("UseShellExecute = false", src)
        self.assertIn("CreateNoWindow = true", src)
        self.assertNotIn("RedirectStandardOutput = true", src)
        self.assertNotIn("RedirectStandardError = true", src)

    def test_configure_starts_the_window_and_keeps_the_status_notice_as_the_fallback(self):
        src = read(CALLER, "src", "TsScoringCallerInputDevice.cs")
        body = src[src.index("public void Configure("):]
        body = body[:body.index("// This device never produces input")]
        self.assertIn("InitialDefaultsLauncher.TryLaunch", body, "ID2C-RED: Configure does not start the window")
        self.assertIn("BuildStatusText", body, "the status text must stay as the fallback")
        self.assertIn("catch", body)
        self.assertNotIn("WaitForExit", body)

    def test_the_project_compiles_the_launcher_and_the_sources_are_ascii(self):
        proj = read(CALLER, "TSScoringPlugin.Caller.InputDevice.csproj")
        self.assertIn('<Compile Include="src\\InitialDefaultsLauncher.cs" />', proj, "ID2C-RED: the launcher is not in the project")
        self.assertIn('<Compile Include="src\\InitialDefaultsWindow.cs" />', proj, "IO1-RED: the window helper is not in the project")
        for name in ("InitialDefaultsLauncher.cs", "InitialDefaultsWindow.cs", "TsScoringCallerInputDevice.cs"):
            data = open(os.path.join(CALLER, "src", name), "rb").read()
            bad = [b for b in data if b > 127]
            self.assertFalse(bad, "ID2C-RED: %s contains non-ASCII bytes (use \\u escapes)" % name)

    def test_the_caller_test_script_exists(self):
        read(ROOT, "TsScoringPlugin", "Handshake", "Tests", "Test-InitialDefaultsLauncher.ps1")

    # ---- Stage IO-1 (window ownership): static facts of the Caller side -------------------------------------------------------------------------------------------------
    def test_the_owner_information_travels_in_the_environment_and_argv_stays_the_flag(self):
        src = read(CALLER, "src", "InitialDefaultsLauncher.cs")
        for name in ("TSSCORING_INITDEF_BVE_PID", "TSSCORING_INITDEF_OWNER_HWND", "TSSCORING_INITDEF_BVE_MAIN_HWND"):
            self.assertIn(name, src, "IO1-RED: the launcher does not pass %s" % name)
        self.assertIn("psi.EnvironmentVariables[", src)
        self.assertIn('return "\\"" + scriptPath + "\\" " + Argument;', src, "IO1-GUARD: the command line must stay the quoted script path and --initial-defaults only")

    def test_the_owner_is_checked_against_the_pid_before_it_is_passed(self):
        src = read(CALLER, "src", "InitialDefaultsLauncher.cs")
        self.assertIn("BelongsTo(ownerCandidate, bvePid)", src, "IO1-RED: the owner candidate is not checked against the pid")
        self.assertIn("BelongsTo(mainCandidate, bvePid)", src, "IO1-RED: the main window is not checked against the pid")
        self.assertIn("INITDEF_FOREIGN_BVE_REJECTED", src, "IO1-RED: a second BVE is not refused with a diagnostic")
        self.assertIn("AnyWindowOfTheNamedMutexExists", src, "IO1-RED: no check for a window of another BVE")

    def test_configure_passes_the_owner_of_the_properties_button(self):
        src = read(CALLER, "src", "TsScoringCallerInputDevice.cs")
        body = src[src.index("public void Configure("):]
        body = body[:body.index("// This device never produces input")]
        self.assertIn("TryLaunchOwned(InitialDefaultsLauncher.ResolveOwner(", body, "IO1-RED: Configure does not pass the owner")
        self.assertIn("owner.Handle", body)
        self.assertNotIn("WaitForExit", body)

    def test_the_window_helper_has_no_key_injection_no_topmost_and_no_waiting_for_the_child(self):
        src = read(CALLER, "src", "InitialDefaultsWindow.cs")
        for bad in (r"keybd_event", r"SendKeys", r"SendInput", r"VK_MENU", r"0x12\b", r"HWND_TOPMOST", r"WS_EX_TOPMOST", r"WaitForExit", r"WaitForInputIdle", r"MessageBox", r"Registry"):
            self.assertIsNone(re.search(bad, src), "IO1-RED: the window helper must not contain %r (no blind Alt tap, no key injection, no top-most, no waiting)" % bad)
        for needed in ("SW_RESTORE", "SetForegroundWindow", "FlashWindowEx", "AttachThreadInput", "GWLP_HWNDPARENT", "INITDEF_RESTORED", "INITDEF_REACTIVATED", "INITDEF_FLASHED", "INITDEF_OWNER_REBOUND", "INITDEF_NO_WINDOW"):
            self.assertIn(needed, src, "IO1-RED: the window helper has no %s" % needed)
        attach = src.index("AttachThreadInput(me, fgThread, true)")
        self.assertIn("finally", src[attach:attach + 600], "IO1-RED: AttachThreadInput must be detached in a finally block")
        self.assertIn("AttachThreadInput(me, fgThread, false)", src[attach:attach + 900], "IO1-RED: the AttachThreadInput attachment is never detached")
        self.assertIn("FindWindowOf(running.Id)", src, "IO1-RED: only windows of the child's own pid may be looked at")

if __name__ == "__main__":
    unittest.main()
