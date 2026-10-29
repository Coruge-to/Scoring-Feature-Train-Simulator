"""Phase SI-R5.3 R53-04A fix design, Stage 0 - static RED / Guard of the "no message pump on the UI (STA) thread" contract of the observation log.

Background: R53-04A (NRE 2f48547f49ed5650): ObservationLog.Write -> Mutex.WaitOne(30) on the STA UI thread, inside lock(gate), dispatched WM_PAINT into BVE.
Naming: test_guard_* = must pass for ANY state (before and after the fix); test_red_* = must FAIL on the current sources and pass after the fix.
tests/red_observation_ui_contract.py runs these in-process together with the dynamic result file of Tests/Test-ObservationUiNonBlocking.ps1.
Sources are read from the repository; TS_UI_CONTRACT_SRC=<flat folder> reads a scratch prototype instead (Stage 0 validation of the tests themselves).
It starts no BVE and builds nothing. Python: python -B -m unittest tests.test_observation_ui_contract_static
"""
import hashlib
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HS = os.path.join(ROOT, "TsScoringPlugin", "Handshake")
PROTO = os.environ.get("TS_UI_CONTRACT_SRC", "")

REPO_PATHS = {
    "ObservationLog.cs": os.path.join(HS, "Shared", "ObservationLog.cs"),
    "ScenarioObserver.cs": os.path.join(HS, "Bridge", "src", "ScenarioObserver.cs"),
    "ScenarioReadyTracker.cs": os.path.join(HS, "Bridge", "src", "ScenarioReadyTracker.cs"),
    "TsScoringBridgePrototype.cs": os.path.join(HS, "Bridge", "src", "TsScoringBridgePrototype.cs"),
    "TsScoringLegacyBridge.cs": os.path.join(HS, "Bridge", "Legacy", "src", "TsScoringLegacyBridge.cs"),
}

# a snapshot of the blocking primitives in the product sources on the commit this Stage started from (f375cf1):  file -> (WaitOne, Join, Sleep)
WAIT_SNAPSHOT = {
    os.path.join("Shared", "ObservationLog.cs"): (1, 0, 0),
    os.path.join("Bridge", "src", "ScenarioObserver.cs"): (0, 2, 0),
    os.path.join("Bridge", "src", "ScenarioReadyTracker.cs"): (0, 0, 0),
    os.path.join("Bridge", "src", "TsScoringBridgePrototype.cs"): (0, 0, 0),
    os.path.join("Bridge", "src", "HandshakeControlPlane.cs"): (5, 1, 0),
    os.path.join("Bridge", "Legacy", "src", "TsScoringLegacyBridge.cs"): (0, 0, 0),
    os.path.join("Caller", "src", "BveWindowMessageObserver.cs"): (2, 0, 0),
    os.path.join("Caller", "src", "HandshakeSession.cs"): (3, 0, 0),
    os.path.join("Caller", "src", "TsScoringCallerInputDevice.cs"): (0, 0, 0),
    os.path.join("Caller", "src", "AppProcessManager.cs"): (9, 1, 0),
    os.path.join("Shared", "HandshakeProtocol.cs"): (0, 0, 0),
}
# The files whose scratch prototype is allowed to differ in the primitives above: none (the fix must not ADD a wait/join/sleep to any of them).

# event vocabulary of the observation log on the commit this Stage started from (f375cf1): file -> event names
EVENT_VOCABULARY = {
    "ScenarioObserver.cs": ("ALL_EXT_LOADED", "CAND_D_NOT_MET", "CAND_E_PENDING", "CAND_F_PENDING", "FRAME_ORDER", "GEN_BEGIN", "GEN_SUMMARY", "IS_CREATED_CHANGED", "LATE_ATTACH", "OBSERVER_DISPOSE", "SCN_CLOSED", "SCN_CREATED", "SCN_OPENED", "SCN_PREVIEW_CREATED", "TICK_GAP", "TICK_OUTSIDE_GENERATION"),
    "ScenarioReadyTracker.cs": ("SR_CLEARED", "SR_CLOSED_NO_LEVEL", "SR_CREATED", "SR_CREATED_WITHOUT_OPEN", "SR_DISPOSED", "SR_E_STALLED", "SR_EPOCH", "SR_EPOCH_TICK", "SR_ESTABLISHED", "SR_F_DIAG", "SR_GENERATION_WRAPPED", "SR_OPENED", "SR_PENDING", "SR_PUBLISH_FAIL", "SR_PUBLISHED", "SR_WAIT", "SR_WITHDRAWN"),
    "TsScoringBridgePrototype.cs": ("BRIDGE_CTOR_BEGIN", "BRIDGE_CTOR_END", "BRIDGE_DISPOSE_BEGIN", "BRIDGE_DISPOSE_END", "BRIDGE_FIRST_TICK", "CURRENT_TICK_AFTER_HANDSHAKE_UP", "SUBSCRIBE_DONE", "SUBSCRIBE_FAIL"),
    "TsScoringLegacyBridge.cs": ("BRIDGE_CTOR_BEGIN", "BRIDGE_CTOR_END", "BRIDGE_DISPOSE_BEGIN", "BRIDGE_DISPOSE_END", "BRIDGE_FIRST_TICK", "LEGACY_TICK_AFTER_HANDSHAKE_UP", "SUBSCRIBE_DONE", "SUBSCRIBE_FAIL"),
    "HandshakeControlPlane.cs": ("AVAIL_CREATE_BEGIN", "AVAIL_CREATE_FAIL", "AVAIL_CREATE_OK", "AVAIL_DISPOSED", "READY_CREATE_BEGIN", "READY_CREATE_OK", "READY_DISPOSED"),
    "HandshakeSession.cs": ("APP_EXCEPTION", "APP_LAUNCH_SUPPRESSED_EPOCH", "APP_START_REQUEST", "APP_START_REQUEST_EPOCH", "APP_START_SUPPRESSED", "APP_START_SUPPRESSED_EPOCH", "APP_STOP_NOT_REQUIRED", "APP_STOP_REQUEST", "AVAIL_FIRST_CHECK", "AVAIL_FIRST_PRESENT", "AVAIL_LOST", "AVAIL_SEEN", "CALLER_DISPOSE_BEGIN", "CALLER_DISPOSE_END", "CALLER_ENABLED_CREATED", "CALLER_TICK_STATE", "DRIVING_ACTIVE_OFF", "DRIVING_ACTIVE_ON", "DRIVING_EXCEPTION", "EPOCH_OBSERVED", "EPOCH_SESSION_WITHOUT_TICK", "EPOCH_TICK_SEEN", "EPOCH_WITHDRAWN", "FIRST_TICK_JUDGE", "FIRST_TICK_SEEN", "MONITOR_LOOP_BEGIN", "NOTICE_DIALOG_CLOSED", "NOTICE_JUDGE_BEGIN", "NOTICE_PRESHOW", "NOTICE_SHOW_CALL", "NOTICE_SUPPRESSED", "READY_CONNECTED", "READY_FIRST_PRESENT", "READY_LOST", "SCN_GENERATION_CHANGED", "SCN_READY_OFF", "SCN_READY_ON", "STARTUP_BRIDGE_DELAY", "TIMEOUT_REACHED"),
    "BveWindowMessageObserver.cs": ("F11_A2_ATTACH_FAILED", "F11_A2_ATTACH_SKIPPED", "F11_A2_ATTACHED", "F11_A2_CLOSE_ALLOWED", "F11_A2_CLOSE_PASSTHROUGH", "F11_A2_CLOSE_REPOSTED", "F11_A2_CLOSE_SUPPRESSED", "F11_A2_MSG_ENTER", "F11_A2_MSG_RETURN", "F11_A2_OBSERVER_DISPOSED", "F11_A2_REPOST_FAILED", "F11_A2_RESTORE_COMPLETED", "F11_A2_RESTORE_REQUESTED", "F11_A2_RESTORE_TIMEOUT", "F11_A2_WAIT_FAILED"),
    "TsScoringCallerInputDevice.cs": ("CALLER_CTOR_BEGIN", "CALLER_CTOR_END", "CALLER_LOAD_BEGIN", "CONFIGURE_CLOSED", "CONFIGURE_OPENED", "F11_A2_INPUT_DISPOSE_BEGIN", "F11_A2_INPUT_DISPOSE_END"),
    "ObservationLog.cs": ("LOG_CAP_REACHED",),
}
THREAD_SNAPSHOT = {"HandshakeControlPlane.cs": 1, "AppProcessManager.cs": 1, "BveWindowMessageObserver.cs": 1, "HandshakeSession.cs": 2, "LegacyJumpControlPlane.cs": 1}

PROTECTED_DLLS = (
    # (path, sha256 prefix, why)
    (r"C:\Users\Public\Documents\BveEx\2.0\Extensions\TsScoringPlugin.dll", "1C2D6896", "Current telemetry DLL: contains no ObservationLog"),
    (r"C:\Users\Public\Documents\BveEx\Legacy\Extensions\TSScoringPlugin.AtsExLegacy.Telemetry.dll", "B87C1AC9", "Legacy telemetry DLL: contains no ObservationLog"),
    (r"C:\Users\Public\Documents\BveEx\2.0\Extensions\TSScoring.FirstChanceDiagnostic.dll", "04378DDC", "First-Chance diagnostic DLL: separate responsibility"),
)


def _src(name):
    if PROTO:
        return os.path.join(PROTO, name)
    return REPO_PATHS[name]


def _read(path):
    with open(path, encoding="utf-8-sig") as fh:
        return fh.read()


def _strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _match_brace(text, open_index):
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _method_regions(text):
    """(name, start, end) of every member body at class level (brace depth 2 = inside namespace + class)."""
    regions = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            if depth == 2:
                head = text[max(0, text.rfind(";", 0, i), text.rfind("}", 0, i), text.rfind("{", 0, i)) + 1:i]
                m = re.search(r"([A-Za-z_]\w*)\s*\([^()]*\)\s*$", head.strip())
                end = _match_brace(text, i)
                if m and end > 0:
                    regions.append((m.group(1), i, end))
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return regions


def _enclosing(regions, pos):
    best = None
    for name, start, end in regions:
        if start < pos < end:
            best = name
    return best


def _lock_gate_blocks(text, gate="gate"):
    blocks = []
    for m in re.finditer(r"\block\s*\(\s*" + gate + r"\s*\)\s*\{", text):
        start = m.end() - 1
        end = _match_brace(text, start)
        if end > 0:
            blocks.append((start, end))
    return blocks


def _handler_body(text, name):
    m = re.search(r"\bvoid\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", text)
    if not m:
        return None
    start = m.end() - 1
    end = _match_brace(text, start)
    return text[start:end + 1]


def _call_positions(body, receiver, method):
    """Index of the first call `receiver.method(` in a handler body (None if absent)."""
    m = re.search(r"\b" + receiver + r"\.(?:" + method + r")\(", body)
    return m.start() if m else None


class UiContractStatic(unittest.TestCase):
    # ------------------------------------------------------------------ RED
    def _order_check(self, file_key):
        text = _strip_comments(_read(_src(file_key)))
        problems = []
        for handler, method in (("OnHackerScenarioOpened", "OnScenarioOpened"), ("OnHackerScenarioClosed", "OnScenarioClosed"), ("OnHackerScenarioCreated", "OnScenarioCreated")):
            body = _handler_body(text, handler)
            self.assertIsNotNone(body, handler + " not found in " + file_key)
            o = _call_positions(body, "observer", method)
            t = _call_positions(body, "tracker", method)
            if t is None:
                t = _call_positions(body, "t", method)  # Legacy: ScenarioReadyTracker t = tracker; t.OnX()
            self.assertIsNotNone(o, handler + ": observer call missing")
            self.assertIsNotNone(t, handler + ": tracker call missing")
            if not t < o:
                problems.append(handler + " calls the observer (diagnostic log) before the tracker")
        self.assertEqual([], problems, "; ".join(problems))

    def test_red_r2b_tracker_before_observer_current(self):
        self._order_check("TsScoringBridgePrototype.cs")

    def test_red_r2b_tracker_before_observer_legacy(self):
        self._order_check("TsScoringLegacyBridge.cs")

    def _log_calls_outside_gate(self, file_key):
        raw = _strip_comments(_read(_src(file_key)))
        regions = _method_regions(raw)
        gates = _lock_gate_blocks(raw)
        problems = []
        for m in re.finditer(r"(?<![\w.])log\s*\(", raw):
            # the constructor parameter / field declarations are not calls
            line_start = raw.rfind("\n", 0, m.start()) + 1
            line = raw[line_start:raw.find("\n", m.start())]
            if re.search(r"(Action<|this\.log|readonly)", line):
                continue
            where = _enclosing(regions, m.start())
            if where != "Deliver":
                problems.append("log(...) called in " + str(where))
            for s, e in gates:
                if s < m.start() < e:
                    problems.append("log(...) inside lock (gate)")
        for m in re.finditer(r"\bDeliver\s*\(", raw):
            for s, e in gates:
                if s < m.start() < e:
                    problems.append("Deliver(...) inside lock (gate)")
        self.assertEqual([], sorted(set(problems)), file_key + ": " + "; ".join(sorted(set(problems))))

    def test_red_r3b_observer_logs_outside_its_gate(self):
        self._log_calls_outside_gate("ScenarioObserver.cs")

    def test_red_r3b_tracker_logs_outside_its_gate(self):
        self._log_calls_outside_gate("ScenarioReadyTracker.cs")

    def test_red_r4_observation_log_has_an_sta_branch_without_blocking_waits(self):
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        self.assertRegex(raw, r"GetApartmentState\(\)\s*==\s*ApartmentState\.STA", "no STA decision in ObservationLog.cs")
        # every Monitor.TryEnter has the literal timeout 0
        for m in re.finditer(r"Monitor\.TryEnter\(([^;]*?)\)", raw):
            self.assertRegex(m.group(1), r",\s*0\s*$", "Monitor.TryEnter with a positive timeout: " + m.group(0))
        # E2: the managed Mutex.WaitOne(0) DISPATCHES messages on STA (200 of 200 trials) - it is not a way to avoid the pump
        self.assertNotRegex(raw, r"\.WaitOne\(\s*0\s*\)", "Mutex.WaitOne(0) pumps on STA (experiment E2); use a non-pumping acquire")
        # the only remaining managed wait is the old, bounded one for non-STA threads
        for m in re.finditer(r"\.WaitOne\(([^)]*)\)", raw):
            self.assertEqual("LockWaitMs", m.group(1).strip(), "unexpected wait: " + m.group(0))

    def test_red_p_pinvoke_helper_contract(self):
        """The Owner-approved non-pumping acquire: ONE kernel32 WaitForSingleObject declaration, WAIT_* mapping, SafeHandle lifetime, release only after a successful acquire."""
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        decls = re.findall(r"\[DllImport\(\"kernel32\.dll\"[^\]]*\)\]\s*(?:private|internal)\s+static\s+extern\s+uint\s+(\w+)\(", raw)
        self.assertEqual(["WaitForSingleObject"], decls, "exactly one P/Invoke declaration, WaitForSingleObject: " + repr(decls))
        self.assertEqual(1, len(re.findall(r"\bDllImport\b", raw)), "DllImport duplicated")
        for token in ("0x00000102", "0x00000080", "0xFFFFFFFF", "NoWaitResult.Busy", "NoWaitResult.Abandoned", "NoWaitResult.Failed", "NoWaitResult.Acquired"):
            self.assertIn(token, raw, "WAIT_* mapping token " + token)
        self.assertIn("DangerousAddRef", raw)
        self.assertIn("DangerousRelease", raw)
        self.assertRegex(raw, r"WaitForSingleObject\([^;]*,\s*0\)", "the wait timeout must be the literal 0")
        # the mutex is released only when it was acquired (the `locked` flag)
        for m in re.finditer(r"ReleaseMutex\(\)", raw):
            before = raw[max(0, m.start() - 160):m.start()]
            self.assertRegex(before, r"if\s*\(\s*locked\b", "ReleaseMutex outside the `locked` guard")

    def test_red_sta_busy_is_dropped_not_waited(self):
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        self.assertRegex(raw, r"Monitor\.TryEnter\(\s*sync\s*,\s*0\s*\)", "the STA path must try the in-process lock without waiting")
        self.assertRegex(raw, r"TryAcquireNoWait\(\s*fileLock\s*\)", "the STA path must use the non-pumping acquire")
        self.assertRegex(raw, r"Interlocked\.Increment\(ref dropped\)", "a skipped STA line is counted as dropped")
    # ---------------------------------------------------------------- GUARD
    def test_guard_no_pending_ring_in_the_minimal_design(self):
        """Owner decision: the 64-line pending ring is NOT part of the minimal implementation (pending_unflushed_at_exit cannot be identified in a real log)."""
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        self.assertNotRegex(raw, r"RingCapacity|\bring\b|\bpending\b|Park\(|TakePending|flushed", "a pending buffer appeared in ObservationLog.cs")

    def test_guard_dllimport_allowlist(self):
        """Bridge/Shared product sources have no P/Invoke except the one limited helper (checked by test_red_p_pinvoke_helper_contract); the Caller keeps its existing ones."""
        existing_caller = {"BveWindowMessageObserver.cs": 2, "HandshakeSession.cs": 1, "TsScoringCallerInputDevice.cs": 1}
        bridge_shared = []
        for base, _dirs, names in os.walk(HS):
            if re.search(r"[\\/](obj|out|Probes|Tests|dist|logs)([\\/]|$)", base):
                continue
            for n in names:
                if not n.endswith(".cs"):
                    continue
                count = len(re.findall(r"\[DllImport", _read(os.path.join(base, n))))
                if "Caller" in base.split(os.sep):
                    self.assertLessEqual(count, existing_caller.get(n, 0), "Caller " + n)
                elif count:
                    bridge_shared.append((n, count))
        if PROTO:
            return
        self.assertLessEqual(sum(c for _n, c in bridge_shared), 1, "Bridge/Shared P/Invokes: " + repr(bridge_shared))
        for n, _c in bridge_shared:
            self.assertEqual("ObservationLog.cs", n, "an unexpected P/Invoke location")
    def test_red_r2_sta_path_does_not_wait_on_mutex(self):
        """R2: the STA path uses neither Mutex.WaitOne(30) nor Mutex.WaitOne(0); the bounded wait exists only in the non-STA branch."""
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        self.assertRegex(raw, r"GetApartmentState\(\)\s*==\s*ApartmentState\.STA", "no STA decision")
        m = re.search(r"\.WaitOne\(\s*LockWaitMs\s*\)", raw)
        self.assertIsNotNone(m, "the bounded wait of the non-STA threads must remain")
        before = raw[max(0, m.start() - 700):m.start()]
        self.assertRegex(before, r"else\s*\{", "WaitOne(LockWaitMs) must sit in the non-STA (else) branch")
        self.assertRegex(before, r"if\s*\(\s*ui\s*\)", "the wait must be selected by the STA flag")
        self.assertNotRegex(raw, r"\.WaitOne\(\s*0\s*\)")

    def test_guard_station_jump_retry_resync_sources_match_manifest(self):
        """StationIndex / Jump / Retry / F5 resync (Python product + Telemetry C# compile inputs) are byte-identical to the manifest blobs (LF-normalised where the manifest says so)."""
        with open(os.path.join(ROOT, "package", "source-package-manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        for entry in manifest["files"]:
            path = os.path.join(ROOT, entry["path"].replace("/", os.sep))
            with open(path, "rb") as fh:
                data = fh.read()
            if entry.get("blob_eol") == "lf":
                data = data.replace(b"\r\n", b"\n")
            self.assertEqual(entry["blob_sha256"].upper(), hashlib.sha256(data).hexdigest().upper(), entry["path"])

    def test_guard_current_and_legacy_share_the_same_core_sources(self):
        for rel in (os.path.join("Bridge", "TSScoringPlugin.BveEx.Bridge.Prototype.csproj"), os.path.join("Bridge", "Legacy", "TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj")):
            text = _read(os.path.join(HS, rel))
            for name in ("ScenarioObserver.cs", "ScenarioReadyTracker.cs", "ObservationLog.cs", "HandshakeControlPlane.cs"):
                self.assertIn(name, text, rel + " lost " + name)
        self.assertIn("ObservationLog.cs", _read(os.path.join(HS, "Caller", "TSScoringPlugin.Caller.InputDevice.csproj")))

    def test_guard_event_vocabulary_is_preserved(self):
        for name, expected in EVENT_VOCABULARY.items():
            path = os.path.join(PROTO, name) if PROTO else None
            if PROTO and not os.path.exists(path):
                continue
            if not PROTO:
                found_path = None
                for base, _dirs, names in os.walk(HS):
                    if name in names and not re.search(r"[\\/](obj|out|Probes|Tests|dist|logs)([\\/]|$)", base):
                        found_path = os.path.join(base, name)
                path = found_path
            self.assertIsNotNone(path, name)
            raw = _strip_comments(_read(path))
            found = set(m.group(1) for m in re.finditer(r'"([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?=[" ])', raw))
            self.assertEqual(set(), set(expected) - found, name + " lost event names")

    def test_guard_no_new_worker_thread_or_unbounded_queue(self):
        for base, _dirs, names in os.walk(HS):
            if re.search(r"[\\/](obj|out|Probes|Tests|dist|logs)([\\/]|$)", base):
                continue
            for n in names:
                if not n.endswith(".cs"):
                    continue
                raw = _strip_comments(_read(os.path.join(base, n)))
                self.assertLessEqual(len(re.findall(r"new\s+Thread\(", raw)), THREAD_SNAPSHOT.get(n, 0), "new worker thread in " + n)
                self.assertNotRegex(raw, r"ConcurrentQueue|Queue<|ThreadPool|Task\.Run|Task\.Factory|BlockingCollection", "queue / pool token in " + n)
        if PROTO:
            for n in os.listdir(PROTO):
                if n.endswith(".cs"):
                    raw = _strip_comments(_read(os.path.join(PROTO, n)))
                    self.assertLessEqual(len(re.findall(r"new\s+Thread\(", raw)), THREAD_SNAPSHOT.get(n, 0), "prototype: new worker thread in " + n)
                    self.assertNotRegex(raw, r"ConcurrentQueue|Queue<|ThreadPool|Task\.Run|BlockingCollection", "prototype: queue token in " + n)
    def test_guard_external_log_contract_tokens(self):
        raw = _read(_src("ObservationLog.cs"))
        for token in ("LockWaitMs = 30", "WaitOne(LockWaitMs)", "droppedBefore=", "LOG_CAP_REACHED", "DefaultMaxBytes = 4L * 1024 * 1024", "ResetForTests", "TestPath", "TestPid", "TestMaxBytes"):
            self.assertIn(token, raw, token)

    def test_guard_no_new_event_name_or_key_in_observation_log(self):
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        events = set(re.findall(r'"([A-Z][A-Z0-9_]{3,})', raw))
        self.assertEqual({"LOG_CAP_REACHED"}, {e for e in events if "_" in e and e != "TSScoringPlugin"}, "event-like literals: " + repr(sorted(events)))
        keys = set(re.findall(r'"\s?([A-Za-z]+=)"', raw))
        self.assertTrue(keys <= {"droppedBefore=", "limitBytes=", "initializedBy=", "ver=", "P=", "S=", "T=", "q=", "th="}, "keys: " + repr(sorted(keys)))

    def test_guard_log_failure_never_throws(self):
        raw = _strip_comments(_read(_src("ObservationLog.cs")))
        m = re.search(r"internal static void WriteStamped\(|internal static void Write\(", raw)
        self.assertIsNotNone(m)
        body = raw[raw.find("{", m.end()):]
        self.assertRegex(body[:1800], r"catch\s*\{")

    def test_guard_no_blocking_primitive_added_to_product_sources(self):
        root = HS if not PROTO else None
        for rel, expected in WAIT_SNAPSHOT.items():
            if PROTO:
                name = os.path.basename(rel)
                path = os.path.join(PROTO, name)
                if not os.path.exists(path):
                    continue
            else:
                path = os.path.join(root, rel)
            raw = _strip_comments(_read(path))
            got = (len(re.findall(r"\.WaitOne\(", raw)), len(re.findall(r"\.Join\(", raw)), len(re.findall(r"\.Sleep\(", raw)))
            self.assertLessEqual(got[1], expected[1], rel + " Join")
            self.assertLessEqual(got[2], expected[2], rel + " Sleep")
            self.assertLessEqual(got[0], expected[0], rel + " WaitOne")

    def test_guard_first_chance_diagnostic_is_independent_of_the_observation_log(self):
        diag = os.path.join(HS, "Probes", "FirstChanceDiag")
        if not os.path.isdir(diag):
            self.skipTest("Probes/FirstChanceDiag not present")
        for base, _dirs, names in os.walk(diag):
            for n in names:
                if n.lower().endswith((".cs", ".csproj")):
                    self.assertNotIn("ObservationLog", _read(os.path.join(base, n)), n)
        for key in ("ObservationLog.cs", "ScenarioObserver.cs", "ScenarioReadyTracker.cs", "TsScoringBridgePrototype.cs", "TsScoringLegacyBridge.cs"):
            raw = _strip_comments(_read(_src(key)))
            self.assertNotRegex(raw, r"FirstChance|\bFc[A-Z]\w+|Probes[\\/]", key)

    def test_guard_source_package_manifest_does_not_list_handshake_log_sources(self):
        path = os.path.join(ROOT, "package", "source-package-manifest.json")
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        listed = [f["path"] for f in manifest["files"]]
        for p in listed:
            self.assertFalse(re.search(r"Handshake/(Bridge|Caller|Shared/ObservationLog)", p.replace("\\", "/")), p)

    def test_guard_protected_dlls_are_byte_identical(self):
        checked = 0
        for path, prefix, why in PROTECTED_DLLS:
            if not os.path.exists(path):
                continue
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest().upper()
            self.assertTrue(digest.startswith(prefix), why + ": " + path + " " + digest[:8])
            checked += 1
        if checked == 0:
            self.skipTest("deployed DLLs not present on this machine")

    def test_guard_only_the_three_dlls_carry_the_observation_log(self):
        carriers = (
            (r"C:\Users\Public\Documents\BveEx\2.0\Extensions\TSScoringPlugin.BveEx.Bridge.Prototype.dll", True),
            (r"C:\Users\Public\Documents\BveEx\Legacy\Extensions\TSScoringPlugin.AtsExLegacy.Bridge.Prototype.dll", True),
            (r"C:\Program Files\mackoy\BveTs6\Input Devices\TSScoringPlugin.Caller.InputDevice.dll", True),
            (r"C:\Users\Public\Documents\BveEx\2.0\Extensions\TsScoringPlugin.dll", False),
            (r"C:\Users\Public\Documents\BveEx\Legacy\Extensions\TSScoringPlugin.AtsExLegacy.Telemetry.dll", False),
            (r"C:\Users\Public\Documents\BveEx\2.0\Extensions\TSScoring.FirstChanceDiagnostic.dll", False),
        )
        seen = 0
        for path, expected in carriers:
            if not os.path.exists(path):
                continue
            with open(path, "rb") as fh:
                data = fh.read()
            has = "ObsLogLock".encode("utf-16-le") in data
            self.assertEqual(expected, has, path)
            seen += 1
        if seen == 0:
            self.skipTest("deployed DLLs not present on this machine")


if __name__ == "__main__":
    unittest.main()
