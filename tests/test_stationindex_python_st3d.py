"""Phase PID-D4JA StationIndex ST-3d - the CONTRACT tests of the PYTHON side of the Jump transaction: the Python writes the official Jump as the Jump wire v2 only (retry and scoring
start), reads the completion v2 of Current and Legacy through the shared codec, settles the transaction (RequestId, kind, selected index, scope, requested position, actual position, scenario)
and releases everything on every way out. Python only: the managed Overlay of tests/d6_rig.py (a byte-buffer jump directory, a fake clock, a stub UDP socket) and the normal-mode rig of
tests/sia_rig.py; nothing here compiles, builds, starts a process, opens a socket or writes a file. The C# senders are held by their own compiled tests (ST-3b / ST-3c).

The ids are the ones of the Start Audit (13-Red-Test-Plan.md), of the ST-3b / ST-3c handoffs and the ones that ST-3d fixed before it wrote a line of product (artifact 04-Red-Baseline.md):
  N-21b  WRITER-IS-WIRED                the call sites of execute_retry and handle_menu_enter build the request through ONE builder (the v2 formatter of the codec)
  N-21c  NO-V1-STRING-ASSEMBLY          no hand assembled "JUMP_STA_TIME:" / "JUMP_LOC_TIME:" text is left in the application modules
  N-39   SETTLE-SUCCESS-CUTS-BEFORE-RELEASE        at the moment is_official_jumping falls the history is already cut and the pending retry is already gone
  N-40   SETTLE-FAILURE-KEEPS-HISTORY-AND-RELEASES per failure reason: same history object and content, no resolve_retry_history, pending / expectation / jump released, one diagnostic
  N-41   STUCK-PATHS-ARE-GONE           a completion that the RequestId accepted but the transaction does not (position, negative expected position, malformed number) never leaves the jump on
  N-42   EVERY-RELEASE-PATH-CLEARS      timeout, refused send, session end, generation boundary, shutdown: pending retry, expectation and jump are all released, once
  N-43   RETRY-COUNT-IS-NOT-TOUCHED-BY-SETTLEMENT  (GUARD)
  N-44   ONE-DIAGNOSTIC-LINE-PER-TRANSACTION       jump-settled: one line, 160 characters, the G-RC-1b items, no raw body / path / token
  N-45   FIRST-ARRIVAL-AFTER-A-RETRY-MAKES-NO-DUPLICATE  the cut happens before the first arrival (also in the same datagram batch)
  N-46   RESOLVE-RETRY-HISTORY-HAS-ONE-CALL-SITE    (static)
  N-47   NORMAL-MODE-IS-NOT-FORMAL      no history cut, no formal settlement, deadline release, v1 not accepted
  N-48   START-JUMP-IS-JUDGED-WITH-THE-SAME-CHECKS  the scoring start has its own expectation; a mismatch aborts; the history is never cut
  N-49   NO-COMPLETION-RELEASES-BY-DEADLINE        contract rejection / breaker / discard / reinit-not-applied of a C# sender look like a lost completion: released at the deadline, history kept
  N-50   STALE-AND-DUPLICATE-COMPLETIONS-CHANGE-NOTHING
  N-51   V1-COMPLETION-IS-NOT-A-FORMAL-SUCCESS
  N-52   LEGACY-DIRECTORY-WRITES-AND-SETTLES-THE-SAME  (the Legacy host differs from Current by the Directory name only)
  N-53   A REQUEST THE WIRE CAN NOT CARRY IS REFUSED BEFORE ANYTHING CHANGES  (start and retry: a position beyond the codec range)
  N-54   AN EXCEPTION INSIDE THE SETTLEMENT STILL RELEASES THE OPEN JUMP (the client has finished the request: no timeout would)
  N-56   A DUPLICATE OF A FINISHED REQUEST CHANGES NOTHING WHILE THE NEXT TRANSACTION IS OPEN (and is recorded on it)
  N-55   THE SETTLEMENT ASKS THE ADOPTED LIST AND THE SCENARIO, NOT THE PUBLISHED IDENTITY (which can be unusable for a moment after a jump)
  N-70   PURE-BUILDER   N-71 PURE-JUDGE   N-72 PURE-DIAGNOSTIC
  N-75   ST3D-DOES-NOT-TOUCH-CSHARP-OR-CODEC  (GUARD)
  T07    COMPLETION-INDEX-MISMATCH-ACCEPTED   (migrated here from tests/red_st0_stationindex_contract.py, same id and code)

Each RED fails against the tree BEFORE this phase with ContractViolation whose .code is the declared one (the preconditions are plain assertions that come first, so a broken fixture or a
moved source is RED-INVALID and never a RED); the same tests pass against the tree of ST-3d. N-43 and N-75 are GUARDs: they pass before and after.
"""
import ast
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import PyQt6.QtWidgets  # noqa: F401
    HAS_QT = True
except Exception:  # pragma: no cover
    HAS_QT = False

import dataplane_contract as contract_dp  # noqa: E402
import jump_wire  # noqa: E402
import sia_rig as R  # noqa: E402
import station_identity  # noqa: E402
try:
    import jump_transaction as JT  # noqa: E402  (the pure layer of the Jump transaction; absent in the tree before ST-3d: the pure tests then fail with ContractViolation, never with an ImportError)
except ImportError:
    JT = None
import test_jf1_jump_completion_and_chain_current as F2  # noqa: E402  (the managed jump rig: Base.start, r.complete, deterministic RequestIds)

T0 = 36000000
ZERO = {"time": 0, "stop": 0, "base_brake": 0, "roll": 0, "jerk": 0, "init_brake": 0, "rel_brake": 0, "eb": 0, "limit": 0, "ats": 0, "bonus": 0}
STALIST3 = "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1"
STALIST5 = ("STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=1=2000.0=-1=-1=-1=15000=0=0,D=1=3000.0=-1=-1=-1=15000=0=0,"
            "E=0=4000.0=-1=-1=-1=15000=0=1")
STALIST_NEG = ("STALIST:A=1=-5.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1")
STALIST_FAR = ("STALIST:A=1=2000000000.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1")           # station A is further than the wire can carry (1e9)

# the files ST-3d does not touch (the C# products of Current and Legacy, the shared codec, the vector table, the Python client and the contract): git blob ids at ea0a3fb
FROZEN = {
    # Phase ST-3e0 changes both projects on purpose (exactly one Compile item of Shared\PackageContract.cs each; the blobs moved from defbe148... / 61092229...): their rows are gone; they are held by
    # tests/test_stationindex_package_st3e0.py (E0-25: each differs from the blob of 0b8e511 by that one item only)
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/AssemblyInfo.cs": "d601dec6a3a0feff0e7e6ed54c610ecb0d53bd51",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyApi.cs": "890208dd6a69d9e2b1fd2f3a8a4d3a4907f0bbb7",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyDataPlaneSink.cs": "f5e11a9579ea5ba12544b9f00c0a48693f638819",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyGroundLimits.cs": "b6cf818399ca8ed83499f2cbf1f40669b40c487f",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyHandleContract.cs": "86596694a6dfd14124acc61514f8f70ff018dca9",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputProbe.cs": "30b23a457376cfd67c4bdd1ea98ddb863e1b438c",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyInputTelemetry.cs": "dd128ed0fe90bcd4082602cf291e5c9f60294ed7",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpCommandQueue.cs": "c9517db9074f45ef447991cd52280ef512047070",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpControlPlane.cs": "04d3104d1005fca4a8fe4a9c3da835bd79d61309",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpEndpoint.cs": "eb3a0233d799e8abbeea47e7d01b46034ee68584",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyJumpExecutor.cs": "b95754144e06ae9eb85b98bf04ea3731eab98600",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyScoringProbe.cs": "1f0be23bc1c911e4bf83933a22016613834c2f48",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyStationTimeline.cs": "1bae94a187e8ef689bda513c2e478fcf2ac7b9f2",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetryExtension.cs": "12a0f84ad865443ad64c76e308907f5b7bcfdcf9",
    "TsScoringPlugin/Handshake/Telemetry/Legacy/src/LegacyTelemetrySession.cs": "5dd33902438d358f038a03a8900976816d589af0",
    "TsScoringPlugin/Handshake/Telemetry/Shared/DataPlaneProtocol.cs": "bed2ed8585b502578d4d4e17f64307206d0920fc",
    "TsScoringPlugin/Handshake/Telemetry/Shared/GenericHandleTextContract.cs": "94746abf0d4395b0ddbfa351df3adadb1aa70132",
    "TsScoringPlugin/Handshake/Telemetry/Shared/JumpWire.cs": "dff2a85a25ff22f76892b3d19209b1da9c089387",
    "TsScoringPlugin/Handshake/Telemetry/Shared/StationListIdentity.cs": "bfa15b21eb2d815e1bd158aa890ddb168475898f",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryContract.cs": "c7be611e9b1d704a17014b9294a532cf82abc0b9",
    "TsScoringPlugin/Handshake/Telemetry/Shared/TelemetryDirectoryReader.cs": "cde81d8f5411df680cb17b10288a3c8d9b01f561",
    "TsScoringPlugin/TsScoringPlugin/AtsLoggerPlugin.cs": "22209df3e50762dd17c68c9bb788af6f8faf98b7",
    # Phase U10 changed Class1.cs on purpose (tests\test_stationindex_station_range_u10.py): the blob moved from a1c34ae7... (ST-3b); ST-3d itself still does not touch it
    "TsScoringPlugin/TsScoringPlugin/Class1.cs": "a9b420a0e0da76bac286815f697cf0010144bd72",
    "TsScoringPlugin/TsScoringPlugin/CurrentDataPlane.cs": "71b0ebaa6f52871ceb2a59456a2b527041241c46",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpEndpoint.cs": "3e0d3bffbb74e4a2ecc6d10d378a8b6e2788ae6f",
    "TsScoringPlugin/TsScoringPlugin/CurrentJumpExecution.cs": "8a54d6a14100e0021ca248d28369c335f965fafe",
    "TsScoringPlugin/TsScoringPlugin/Properties/AssemblyInfo.cs": "e704abd24867f658d3a0391e231395dff85ad5d2",
    "TsScoringPlugin/TsScoringPlugin/packages.config": "9941b75a35df1b68f9e504da7bc4c9238d41ccb9",
    "current_jump_client.py": "bfcee44c0a0f79a76a8a6e950c738084523f1cf9",
    "dataplane_contract.py": "56da8579207ae7f6d866f17ce4aafe6d0553c23f",
    "jump_wire.py": "00579f8031221333f2f6e471d7e30ab3f8b1a365",
    "tests/jump_wire_vectors.json": "a9fc787a99853961eaecf33e22aac4eba6308029",
}


class ContractViolation(AssertionError):
    """The tree does not meet the contract; `code` names the violated clause (a RED run compares it with the declared one)."""

    def __init__(self, tid, code, detail=""):
        super().__init__("ST3D-RED[%s] %s: %s" % (tid, code, detail))
        self.tid, self.code, self.detail = tid, code, detail


def red(tid, code):
    def deco(fn):
        fn.st3d = {"kind": "RED", "id": tid, "code": code}
        return fn
    return deco


def guard(tid):
    def deco(fn):
        fn.st3d = {"kind": "GUARD", "id": tid, "code": ""}
        return fn
    return deco


def contract(ok, tid, code, detail=""):
    if not ok:
        raise ContractViolation(tid, code, detail)


_TMP_HOME = {}


def setUpModule():
    _TMP_HOME["dir"] = tempfile.TemporaryDirectory(prefix="ts-st3d-")
    _TMP_HOME["saved"] = {k: os.environ.get(k) for k in ("USERPROFILE", "HOME")}
    os.environ["USERPROFILE"] = _TMP_HOME["dir"].name
    os.environ["HOME"] = _TMP_HOME["dir"].name


def tearDownModule():
    try:
        left = os.listdir(_TMP_HOME["dir"].name)
    finally:
        for k, v in _TMP_HOME["saved"].items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _TMP_HOME["dir"].cleanup()
    if left:
        raise AssertionError("the ST-3d module wrote into the redirected profile: %r" % (left,))


def read(name):
    with open(os.path.join(ROOT, name), "rb") as f:
        return f.read().decode("utf-8-sig")


def parse_settled(line):
    d = {}
    for part in line.split():
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
    return d


def completion_v2(kind, idx, loc, scope, t=T0, count=1):
    text, why = jump_wire.format_completion_v2(kind, idx, loc, t, count, tuple(scope))
    assert why is None, why
    return text


def functions_of(source, name):
    return [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name]


# ==============================================================================================================================================
# A - static
# ==============================================================================================================================================
class A_Static(unittest.TestCase):
    @red("N-21b", "writer-not-wired")
    def test_N21b_execute_retry_and_the_scoring_start_build_their_request_through_the_one_builder(self):
        retry = functions_of(read("scoring_logic.py"), "execute_retry")
        start_src = read("main.py")
        starts = functions_of(start_src, "handle_menu_enter")
        self.assertEqual((len(retry), len(starts)), (1, 1))                                       # the call sites exist (a moved source is RED-INVALID)

        def calls(fn, names):
            return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and ((isinstance(n.func, ast.Attribute) and n.func.attr in names) or (isinstance(n.func, ast.Name) and n.func.id in names))]
        builder = ("build_jump_request", "format_request_v2")
        retry_calls = calls(retry[0], builder)
        # the scoring start may build through a helper of the Overlay; that helper must itself call the builder
        helper_names = {n.func.attr for n in ast.walk(starts[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("_scoring_start")}
        start_calls = calls(starts[0], builder)
        for name in helper_names:
            for fn in functions_of(start_src, name):
                start_calls += calls(fn, builder)
        contract(retry_calls and start_calls, "N-21b", "writer-not-wired",
                 "execute_retry builder calls %d, scoring start builder calls %d (both must build the request through build_jump_request)" % (len(retry_calls), len(start_calls)))

    @red("N-21c", "v1-literal-remains")
    def test_N21c_no_hand_assembled_v1_command_text_is_left_in_the_application_modules(self):
        left = []
        for name in ("main.py", "scoring_logic.py", "managed_input.py", "jump_transaction.py"):
            if not os.path.exists(os.path.join(ROOT, name)):
                continue
            for node in ast.walk(ast.parse(read(name))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"JUMP_(STA|LOC)_TIME", node.value):
                    left.append("%s:%d" % (name, node.lineno))
        contract(not left, "N-21c", "v1-literal-remains", "hand assembled command text at %s" % (left,))

    @red("N-46", "resolve-not-wired-once")
    def test_N46_resolve_retry_history_is_called_from_exactly_one_place_and_that_place_is_the_success_settlement(self):
        sites = []
        for name in ("main.py", "scoring_logic.py", "managed_input.py", "station_identity.py", "jump_transaction.py"):
            if not os.path.exists(os.path.join(ROOT, name)):
                continue
            tree = ast.parse(read(name))
            for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef,))]:
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Attribute) and node.func.attr == "resolve_retry_history")
                                                       or (isinstance(node.func, ast.Name) and node.func.id == "resolve_retry_history")):
                        sites.append((name, fn.name))
        sites = sorted(set(sites))
        self.assertEqual(len(functions_of(read("main.py"), "_settle_jump_complete")), 1)         # the settlement exists (a moved source is RED-INVALID)
        contract(sites == [("main.py", "_settle_jump_complete")], "N-46", "resolve-not-wired-once", "call sites: %r" % (sites,))

    @guard("N-75")
    def test_N75_the_csharp_products_the_shared_codec_and_the_client_are_byte_identical_to_ST3c(self):
        for rel, blob in sorted(FROZEN.items()):
            path = os.path.join(ROOT, *rel.split("/"))
            self.assertTrue(os.path.exists(path), rel)
            try:
                out = subprocess.run(["git", "hash-object", path], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            except (OSError, subprocess.SubprocessError):
                self.skipTest("git is not available")
            self.assertEqual(out.returncode, 0, rel)
            self.assertEqual(out.stdout.decode("ascii").strip(), blob, rel)


# ==============================================================================================================================================
# B - the pure layer
# ==============================================================================================================================================
SCOPE = station_identity.StationScope(7, "A1B2C3D4", 5)
RID = b"\x11" * 16


def have(name):
    return JT is not None and hasattr(JT, name)


class B_Pure(unittest.TestCase):
    @red("N-70", "builder-absent")
    def test_N70_the_builder_writes_the_v2_text_of_the_codec_and_refuses_in_words(self):
        contract(have("build_jump_request"), "N-70", "builder-absent", "jump_transaction.build_jump_request does not exist")
        for command, idx, loc in (("STA", 1, 1000.0), ("LOC", 3, 3000.5), ("STA", 0, -0.0)):
            planned, why = JT.build_jump_request(command, idx, T0 + 5, SCOPE, loc)
            self.assertIsNone(why)
            expected, expected_why = jump_wire.format_request_v2(command, idx, T0 + 5, tuple(SCOPE), loc)
            self.assertIsNone(expected_why)
            self.assertEqual(planned.text, expected)
            self.assertEqual((planned.command, planned.station_index, planned.time_ms, planned.scope), (command, idx, T0 + 5, SCOPE))
            self.assertEqual(planned.location, jump_wire.normalize_location(loc)[0])             # the value that will be judged is the value that is written (-0.0 is 0.0)
            self.assertEqual(jump_wire.parse_request(planned.text)[0].location, planned.location)
        for label, args, word in (("NaN", ("STA", 1, T0, SCOPE, float("nan")), "location-invalid"), ("Infinity", ("STA", 1, T0, SCOPE, float("inf")), "location-invalid"),
                                  ("too far", ("STA", 1, T0, SCOPE, 2.0e9), "location-invalid"), ("negative time", ("STA", 1, -1, SCOPE, 1.0), "time-invalid"),
                                  ("float time", ("STA", 1, 1.5, SCOPE, 1.0), "time-invalid"), ("index out of the scope", ("STA", 5, T0, SCOPE, 1.0), "index-out-of-range"),
                                  ("no scope", ("STA", 1, T0, None, 1.0), "scope-incomplete"), ("unknown command", ("XXX", 1, T0, SCOPE, 1.0), "internal-error")):
            with self.subTest(label=label):
                planned, why = JT.build_jump_request(*args)
                self.assertIsNone(planned)
                self.assertEqual(why, word)

    def exp(self, **override):
        planned, why = JT.build_jump_request("STA", 1, T0 + 60000, SCOPE, 1000.0)
        self.assertIsNone(why)
        e = JT.make_expectation("retry", planned, RID, 100.0)
        return e._replace(**override) if override else e

    def comp(self, **override):
        fields = dict(kind="STA", idx=1, loc=1000.0, scope=SCOPE, t=T0, count=1)
        fields.update(override)
        return jump_wire.parse_completion(completion_v2(fields["kind"], fields["idx"], fields["loc"], fields["scope"], fields["t"], fields["count"]))[0]

    NONE = object()

    def judge(self, exp="default", completion="default", request_id=RID, scope=SCOPE, listed=1000.0):
        return JT.judge_completion(self.exp() if exp == "default" else exp, self.comp() if completion == "default" else completion, request_id, scope, listed)

    @red("N-71", "judge-absent")
    def test_N71_the_success_is_the_AND_of_every_check_and_the_first_failing_check_names_the_reason(self):
        contract(have("judge_completion") and have("make_expectation"), "N-71", "judge-absent", "jump_transaction.judge_completion does not exist")
        ok = self.judge()
        self.assertEqual((ok.ok, ok.reason, ok.formal, ok.selected_idx, ok.actual_location), (True, "ok", True, 1, 1000.0))
        other_scope = station_identity.StationScope(7, "A1B2C3D4", 4)
        cases = (
            ("no expectation", dict(exp=None), "unsolicited"),
            ("unparsed", dict(completion=None), "malformed-completion"),
            ("v1", dict(completion=jump_wire.parse_completion("JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0)[0]), "unsupported-completion-version"),
            ("request id", dict(request_id=b"\x22" * 16), "request-id-mismatch"),
            ("no request id although one is expected", dict(request_id=None), "request-id-mismatch"),
            ("command kind", dict(completion=self.comp(kind="LOC")), "command-kind-mismatch"),
            ("selected index", dict(completion=self.comp(idx=2)), "selected-index-mismatch"),
            ("scope (count)", dict(completion=self.comp(scope=other_scope, idx=1)), "scope-mismatch"),
            ("scope (list id)", dict(completion=self.comp(scope=station_identity.StationScope(7, "00000000", 5))), "scope-mismatch"),
            ("scope (scenario)", dict(completion=self.comp(scope=station_identity.StationScope(8, "A1B2C3D4", 5))), "scope-mismatch"),
            ("requested position", dict(listed=1000.5), "requested-location-mismatch"),
            ("requested position unknown", dict(listed=None), "requested-location-mismatch"),
            ("actual position (0.001 m)", dict(completion=self.comp(loc=1000.001)), "actual-location-mismatch"),
            ("actual position (1 ulp)", dict(completion=self.comp(loc=1000.0000000000001)), "actual-location-mismatch"),
            ("scenario moved on", dict(scope=other_scope), "scenario-changed"),
            ("no scope now", dict(scope=None), "scenario-changed"),
        )
        for label, kw, reason in cases:
            with self.subTest(label=label):
                v = self.judge(**kw)
                self.assertEqual((v.ok, v.reason), (False, reason))
        # the order of the checks: the first failing one is named (selected index before scope before positions)
        both = self.judge(completion=self.comp(idx=2, loc=999.0))
        self.assertEqual(both.reason, "selected-index-mismatch")
        # the normal mode cannot prove a RequestId: it is not formal, whatever the RequestId says
        plain = self.judge(exp=self.exp(request_id=None), request_id=None)
        self.assertEqual((plain.ok, plain.reason, plain.formal), (True, "ok-plain", False))
        # a signed zero is a zero
        zero = self.exp()._replace(location=0.0, station_index=0)
        self.assertTrue(self.judge(exp=zero, completion=self.comp(idx=0, loc=-0.0), listed=0.0).ok)
        # nothing here raises for a foreign object
        for junk in (object(), 5, "x"):
            self.assertFalse(JT.judge_completion(junk, junk, junk, junk, junk).ok)

    @red("N-72", "diagnostic-absent")
    def test_N72_the_settled_event_fits_160_characters_with_the_worst_prefix_and_names_the_G_RC_1b_items(self):
        contract(have("settled_event"), "N-72", "diagnostic-absent", "jump_transaction.settled_event does not exist")
        # the worst REALISTIC case (a scenario number of five digits, a list of 9999 stations, a position of 5+3 digits) and the longest fixed reason words; the pid is the longest too
        worst_scope = station_identity.StationScope(99999, "FFFFFFFF", 9999)
        worst = JT.make_expectation("retry", JT.build_jump_request("LOC", 9998, 2147483647, worst_scope, -12345.678)[0], b"\xaa\xbb\xcc\xdd" + bytes(12),
                                                  0.0)._replace(received=1, last="dup")
        for end, keys in (("requested-location-mismatch", ("end", "id", "ri", "sc", "rl", "cmd")), ("unsupported-completion-version", ("end", "id", "ri", "sc", "rl", "cmd")),
                          ("timeout", ("end", "id", "ri", "sc", "rl", "cmd", "age", "comp", "lv", "kind")), ("ok", ("end", "id", "ri", "sc", "rl", "cmd", "age", "comp", "lv", "kind"))):
            with self.subTest(end=end):
                event, fields = JT.settled_event(worst, end, 123.456, 9998, -12345.678, (9999, 2), 99999)
                line = "[MANAGED] event=%s pid=%d" % (event, 4294967295)
                for key in sorted(fields):
                    line += " %s=%s" % (key, fields[key])
                self.assertEqual(event, "jump-settled")
                self.assertLessEqual(len(line), 160, line)
                self.assertEqual(fields["end"], end)
                for key in keys:
                    self.assertIn(key, fields, key)
        event, fields = JT.settled_event(self.exp(), "timeout", 110.0, None, None, (4, 4), 2)
        self.assertEqual((fields["id"], fields["ri"], fields["sc"], fields["rl"], fields["cmd"], fields["age"], fields["comp"], fields["lv"], fields["kind"]),
                         ("11111111", "1", "7:A1B2C3D4:5", "1000", "STA", "10.0", "0", "none", "retry"))
        for hostile in ("a\\b", "x" * 80, "C:\\Users\\x", "tok=1"):                               # a reason that is not one of the fixed words never reaches the line
            e, f = JT.settled_event(self.exp(), hostile, 101.0, None, None, (4, 4), 2)
            self.assertNotIn(hostile, " ".join(str(v) for v in f.values()))
        self.assertEqual(JT.settled_event(None, "timeout", 1.0, None, None, (0, 0), 0)[0], "jump-settled")        # never raises


# ==============================================================================================================================================
# C - the managed Overlay
# ==============================================================================================================================================
@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class MBase(F2.Base):
    def stub_menu(self):
        self.o.toggle_menu = lambda adv: None

    def tearDown_rig(self):
        """Another scene inside one test (a subTest): the rig of the previous one is closed and a new one is built."""
        if getattr(self, "_scene_used", False):
            self.r.close()
            self.setUp()
        self._scene_used = True

    def scope_now(self):
        o = self.o
        return station_identity.scope_of(o.current_scenario_id, o.bve_list_id, o.station_list)

    def go(self, stalist=None, nextloc_index=1):
        r, o = self.r, self.o
        if stalist is None:
            r.go_active()
        else:
            r.go_active(with_stations=False)
            r.send(stalist, self.MR.tele(1, time_ms=T0, STIDX=self.MR.stidx(stalist, nextloc_index)))
            r.tick(2)
        self.assertTrue(o.bve_list_id and len(o.station_list) >= 3, "the scene is not established")
        o.setting_end_idx = len(o.station_list) - 1
        return self

    def history(self, count):
        o = self.o
        scope = tuple(self.scope_now())
        out = []
        for i in range(count):
            s = o.station_list[i]
            out.append({"loc": s["location"], "time_ms": T0 + 60000 * i, "score": 10 * i, "target_loc": s["location"], "station_name": s["name"], "stop_error": 0.0,
                        "score_details": dict(ZERO), "station_index": i, "scope": scope, "station_location": s["location"], "role": "scoring_start" if i == 0 else "arrived_station"})
        return out

    def begin_retry(self, position=1, count=4, stalist=STALIST5):
        """A scoring run with the history [A, B, C, D] of the five stations; the retry to `position`. Returns (hist, result, command dict)."""
        self.go(stalist)
        r, o = self.r, self.o
        self.stub_menu()
        o.is_scoring_mode = True
        o.save_data = hist = self.history(count)
        o.total_retry_count = 2
        o.score = 77
        result = self.S.execute_retry(o, position, True)
        self.assertTrue(result.accepted, result)
        self.assertTrue(o.is_official_jumping)
        cmd = r.last_command()
        self.assertIsNotNone(cmd)
        return hist, result, cmd

    def deliver(self, text, rid, ticks=0):
        self.r.send_raw(self.r.wrap(text, request_id=rid))
        if ticks:
            self.r.tick(ticks)

    def settled(self):
        out = []
        for line in self.r.events("jump-settled"):
            d = parse_settled(line)
            d["_line"], d["_len"] = line, len(line)
            out.append(d)
        return out

    def released(self):
        o = self.o
        return (not o.is_official_jumping) and o.retry_pending is None and getattr(o, "jump_expectation", None) is None and o.pending_jump_complete is None

    def aborted(self):
        o = self.o
        return (not o.is_scoring_mode) and o.jump_lock and (not o.is_official_jumping)


class C_Writers(MBase):
    @red("N-48a", "retry-writes-v1")
    def test_N48a_the_retry_request_is_the_v2_text_with_index_scope_position_and_time(self):
        hist, result, cmd = self.begin_retry(1)
        scope = self.scope_now()
        expected, why = jump_wire.format_request_v2("STA", 1, T0 + 60000, tuple(scope), 1000.0)
        self.assertIsNone(why)
        contract(cmd["text"] == expected, "N-48a", "retry-writes-v1", "sent %r, the v2 text is %r" % (cmd["text"], expected))
        parsed = jump_wire.parse_request(cmd["text"])[0]
        self.assertEqual((parsed.version, parsed.kind, parsed.station_index, parsed.location, parsed.time_ms, parsed.scope), (2, "STA", 1, 1000.0, T0 + 60000, scope))

    @red("N-48a", "retry-writes-v1")
    def test_N48a_the_loc_method_of_a_middle_station_is_written_as_v2_too(self):
        self.go(STALIST5)
        o = self.o
        o.station_list[1].update(def_time=T0 + 100000, raw_dep=T0 + 15000 + 60000)             # defined later than calculated, checkpoint earlier than defined: the LOC method
        self.stub_menu()
        o.is_scoring_mode = True
        o.save_data = self.history(4)
        self.assertTrue(self.S.execute_retry(o, 1, True).accepted)
        cmd = self.r.last_command()
        expected, why = jump_wire.format_request_v2("LOC", 1, T0 + 60000, tuple(self.scope_now()), 1000.0)
        self.assertIsNone(why)
        contract(cmd["text"] == expected, "N-48a", "retry-writes-v1", "sent %r, the v2 text is %r" % (cmd["text"], expected))

    @red("N-48b", "start-writes-v1")
    def test_N48b_the_scoring_start_request_is_the_v2_text(self):
        cmd = self.start(end_idx=2)
        scope = self.scope_now()
        expected, why = jump_wire.format_request_v2("STA", 0, T0, tuple(scope), 0.0)
        self.assertIsNone(why)
        contract(cmd["text"] == expected, "N-48b", "start-writes-v1", "sent %r, the v2 text is %r" % (cmd["text"], expected))

    @red("N-48b", "start-writes-v1")
    def test_N48b_a_start_at_a_middle_station_carries_its_index_and_position(self):
        self.go(STALIST5)
        o = self.o
        o.setting_start_idx = 2
        o.setting_end_idx = 4
        self.r.start_scoring_via_menu()
        cmd = self.r.last_command()
        expected, why = jump_wire.format_request_v2("STA", 2, T0, tuple(self.scope_now()), 2000.0)
        self.assertIsNone(why)
        contract(cmd["text"] == expected, "N-48b", "start-writes-v1", "sent %r, the v2 text is %r" % (cmd["text"], expected))

    @red("N-52", "legacy-directory-differs")
    def test_N52_the_legacy_host_is_written_to_and_settled_exactly_like_current(self):
        self.go(STALIST5)
        r, o = self.r, self.o
        r.jump_dir = self.D.FakeJumpDirectory(r.pid, name=contract_dp.legacy_jump_name(r.pid))
        r.client._source = r.jump_dir
        self.stub_menu()
        o.is_scoring_mode = True
        o.save_data = hist = self.history(4)
        self.assertTrue(self.S.execute_retry(o, 1, True).accepted)
        cmd = r.last_command()
        expected, why = jump_wire.format_request_v2("STA", 1, T0 + 60000, tuple(self.scope_now()), 1000.0)
        self.assertIsNone(why)
        self.assertEqual(r.jump_dir.requested[-1], contract_dp.legacy_jump_name(r.pid))
        contract(cmd["text"] == expected, "N-52", "legacy-directory-differs", "sent %r, the v2 text is %r" % (cmd["text"], expected))
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])
        contract(self.released() and len(o.save_data) == 2, "N-52", "legacy-directory-differs", "released %r, history %d" % (self.released(), len(o.save_data)))


class D_Settlement(MBase):
    @red("T07", "COMPLETION-INDEX-MISMATCH-ACCEPTED")
    def test_RED_T07_a_completion_with_another_station_index_aborts_the_scoring(self):
        r, o = self.r, self.o
        cmd = self.start()
        expected, why = jump_wire.format_request_v2("STA", 0, T0, tuple(self.scope_now()), 0.0)
        self.assertIsNone(why)
        self.assertTrue(o.is_scoring_mode and o.is_official_jumping)
        self.deliver(completion_v2("STA", 2, 0.0, self.scope_now()), cmd["request_id"])             # the sender says it ended at index 2 (the position still matches)
        aborted = (not o.is_scoring_mode) and o.jump_lock and (not o.is_official_jumping)
        contract(aborted, "T07", "COMPLETION-INDEX-MISMATCH-ACCEPTED", "scoring=%r jump_lock=%r official_jump=%r" % (o.is_scoring_mode, o.jump_lock, o.is_official_jumping))

    @red("N-73", "success-does-not-cut")
    def test_N73_a_matching_completion_cuts_the_history_to_the_chosen_checkpoint_and_resumes_the_scoring(self):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        before = list(hist)
        self.assertEqual(o.retry_pending.state, "sent")
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now(), count=7), cmd["request_id"])
        contract(self.released(), "N-73", "success-does-not-cut", "jump=%r pending=%r expectation=%r" % (o.is_official_jumping, o.retry_pending, getattr(o, "jump_expectation", "absent")))
        contract(len(o.save_data) == 2 and o.save_data[0] is before[0] and o.save_data[1] is before[1], "N-73", "success-does-not-cut",
                 "history of %d checkpoints: %r" % (len(o.save_data), [c["station_name"] for c in o.save_data]))
        self.assertEqual([c["station_name"] for c in hist], ["A", "B", "C", "D"])                   # the input history is never changed in place
        self.assertTrue(o.is_scoring_mode)
        self.assertEqual(o.total_retry_count, 2)
        self.assertEqual((o.bve_jump_count, o.last_jump_count), (7, 7))                              # the sender's counter is absorbed as before

    @red("N-39", "cut-not-before-release")
    def test_N39_at_the_moment_the_jump_state_falls_the_history_is_cut_and_the_pending_retry_is_gone(self):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        cls = type(o)
        original = cls.__setattr__
        seen = []

        def spy(obj, name, value):
            if obj is o and name == "is_official_jumping" and value is False:
                seen.append(([c["station_name"] for c in obj.save_data], obj.retry_pending, getattr(obj, "jump_expectation", None)))
            original(obj, name, value)
        cls.__setattr__ = spy
        try:
            self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])
        finally:
            cls.__setattr__ = original
        self.assertTrue(seen, "the jump state never fell (a broken fixture is RED-INVALID)")
        contract(seen[0] == (["A", "B"], None, None), "N-39", "cut-not-before-release", "at the release: %r" % (seen[0],))

    FAILURES = (
        ("selected-index-mismatch", lambda t: completion_v2("STA", 2, 1000.0, t.scope_now())),
        ("scope-mismatch", lambda t: completion_v2("STA", 1, 1000.0, (t.scope_now().scenario_id, "00000000", t.scope_now().count))),
        ("actual-location-mismatch", lambda t: completion_v2("STA", 1, 1000.5, t.scope_now())),
        ("command-kind-mismatch", lambda t: completion_v2("LOC", 1, 1000.0, t.scope_now())),
        ("malformed-completion", lambda t: "JUMP_COMPLETE:STA:x:1000.0:%d:1:%d:%s:%d" % (T0, t.scope_now().scenario_id, t.scope_now().list_id, t.scope_now().count)),
        ("malformed-completion", lambda t: "JUMP_COMPLETE:STA:1:1000.0"),
        ("unsupported-completion-version", lambda t: "JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0),
    )

    def failure_case(self, text_of, prepare=None):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        content = [dict(c) for c in hist]
        history_object = o.save_data
        if prepare is not None:
            prepare(self, cmd)
        with mock.patch.object(station_identity, "resolve_retry_history", side_effect=AssertionError("resolve_retry_history called on a failure")) as spy:
            self.deliver(text_of(self), cmd["request_id"])
            called = spy.called
        return hist, content, history_object, called

    @red("N-40", "failure-does-not-release-or-keep")
    def test_N40_every_failure_keeps_the_history_releases_everything_and_says_why_once(self):
        for reason, text_of in self.FAILURES:
            with self.subTest(reason=reason):
                self.tearDown_rig()
                hist, content, history_object, called = self.failure_case(text_of)
                o = self.o
                lines = self.settled()
                ok = (self.released() and self.aborted() and o.save_data is history_object and [dict(c) for c in o.save_data] == content and not called
                      and o.total_retry_count == 2 and len(lines) == 1 and lines[0].get("end") == reason)
                contract(ok, "N-40", "failure-does-not-release-or-keep",
                         "reason %s: released=%r aborted=%r history kept=%r resolve called=%r count=%r diagnostics=%r" % (
                             reason, self.released(), self.aborted(), o.save_data is history_object and [dict(c) for c in o.save_data] == content, called,
                             o.total_retry_count, [(l.get("end"), l.get("_len")) for l in lines]))

    def prepare_requested_location(self, cmd):
        self.o.station_list[1]["location"] = 1000.5                                                  # the list moved under the pending request

    def prepare_request_id(self, cmd):
        exp = getattr(self.o, "jump_expectation", None)
        contract(exp is not None, "N-40", "failure-does-not-release-or-keep", "the open transaction has no expectation to compare the RequestId with")
        self.o.jump_expectation = exp._replace(request_id=b"\x77" * 16)

    def prepare_scenario(self, cmd):
        self.o.current_scenario_id = 2                                                             # another scenario is current now (the request was made under scenario 1)

    def prepare_history_replaced(self, cmd):
        self.o.save_data = [dict(c) for c in self.o.save_data]                                       # another list with other objects: the pending retry no longer describes it

    @red("N-40", "failure-does-not-release-or-keep")
    def test_N40_the_checks_that_need_a_prepared_state(self):
        for reason, prepare in (("requested-location-mismatch", self.prepare_requested_location), ("request-id-mismatch", self.prepare_request_id),
                                ("scenario-changed", self.prepare_scenario), ("history-unresolvable", self.prepare_history_replaced)):
            with self.subTest(reason=reason):
                self.tearDown_rig()
                hist, result, cmd = self.begin_retry(1)
                o = self.o
                scope_of_the_request = self.scope_now()
                prepare(cmd)
                history_object = o.save_data
                content = [dict(c) for c in o.save_data]
                with mock.patch.object(station_identity, "resolve_retry_history", wraps=station_identity.resolve_retry_history) as spy:
                    self.deliver(completion_v2("STA", 1, 1000.0, scope_of_the_request), cmd["request_id"])
                lines = self.settled()
                ok = (self.released() and self.aborted() and o.save_data is history_object and [dict(c) for c in o.save_data] == content and len(lines) == 1 and lines[0].get("end") == reason
                      and (reason == "history-unresolvable" or not spy.called))
                contract(ok, "N-40", "failure-does-not-release-or-keep", "reason %s: released=%r aborted=%r diagnostics=%r" % (reason, self.released(), self.aborted(), [l.get("end") for l in lines]))

    @red("N-41", "stuck-after-accepted-request")
    def test_N41_a_completion_the_request_id_accepted_never_leaves_the_jump_on(self):
        for label, text_of in (("J03 position", lambda t: completion_v2("STA", 1, 500.0, t.scope_now())), ("J15 number", lambda t: "JUMP_COMPLETE:STA:x:1000.0:%d:1" % T0)):
            with self.subTest(label=label):
                self.tearDown_rig()
                hist, result, cmd = self.begin_retry(1)
                o = self.o
                self.deliver(text_of(self), cmd["request_id"])
                self.r.clock32.now += 3600.0                                                          # an hour later the timeout has nothing to do: the request was accepted
                contract(self.released() and not self.r.client.has_outstanding and self.aborted(), "N-41", "stuck-after-accepted-request",
                         "%s: jump=%r pending=%r aborted=%r" % (label, o.is_official_jumping, o.retry_pending, self.aborted()))

    @red("N-41", "stuck-after-accepted-request")
    def test_N41_a_negative_requested_position_is_an_ordinary_position(self):
        self.go(STALIST_NEG)
        r, o = self.r, self.o
        o.setting_end_idx = 2
        r.start_scoring_via_menu()
        cmd = r.last_command()
        self.assertEqual((o.station_list[0]["location"], o.setting_start_idx), (-5.0, 0))
        self.deliver(completion_v2("STA", 0, -5.0, self.scope_now()), cmd["request_id"])
        contract(self.released() and o.is_scoring_mode, "N-41", "stuck-after-accepted-request", "jump=%r scoring=%r" % (o.is_official_jumping, o.is_scoring_mode))


class E_Release(MBase):
    @red("N-49", "timeout-leaves-pending")
    def test_N49_a_completion_that_never_comes_releases_everything_at_the_deadline_and_keeps_the_history(self):
        """Contract rejection, breaker, discard and reinit-not-applied of a C# sender send no completion (J20): from here they are a lost completion."""
        hist, result, cmd = self.begin_retry(1)
        r, o = self.r, self.o
        content = [dict(c) for c in hist]
        history_object = o.save_data
        with mock.patch.object(station_identity, "resolve_retry_history", side_effect=AssertionError("called")) as spy:
            r.clock32.now += 5.0
            r.send("STATUS:LOADED:RUNNING")
            self.assertTrue(o.is_official_jumping)                                                    # not yet: the deadline is 10 s
            r.clock32.now += 6.0
            r.send("STATUS:LOADED:RUNNING")
            self.assertFalse(spy.called)
        lines = self.settled()
        ok = (self.released() and self.aborted() and o.save_data is history_object and [dict(c) for c in o.save_data] == content and o.total_retry_count == 2
              and len(lines) == 1 and lines[0].get("end") == "timeout" and lines[0].get("comp") == "0" and lines[0].get("lv") == "none")
        contract(ok, "N-49", "timeout-leaves-pending", "released=%r aborted=%r diagnostics=%r" % (self.released(), self.aborted(), [(l.get("end"), l.get("comp"), l.get("lv")) for l in lines]))

    @red("N-42", "pending-survives-release")
    def test_N42_a_refused_send_releases_the_pending_retry_too(self):
        r, o = self.r, self.o
        self.go(STALIST5)
        self.stub_menu()
        o.is_scoring_mode = True
        o.save_data = self.history(4)
        r.jump_dir.present = False                                                                    # no jump endpoint: the client refuses to send
        self.assertTrue(self.S.execute_retry(o, 1, True).accepted)
        self.assertEqual(r.client.last_failure, "send-refused:jump-directory-missing")
        r.send("STATUS:LOADED:RUNNING")
        lines = self.settled()
        contract(self.released() and self.aborted() and len(lines) == 1 and lines[0].get("end") == "send-refused", "N-42", "pending-survives-release",
                 "released=%r aborted=%r diagnostics=%r pending=%r" % (self.released(), self.aborted(), [l.get("end") for l in lines], o.retry_pending))

    @red("N-42", "pending-survives-release")
    def test_N42_the_end_of_the_session_and_a_generation_boundary_release_the_open_transaction_once(self):
        import managed_input
        for label, discard in (("session", managed_input.discard_scoring_session), ("generation", managed_input.discard_generation_state)):
            with self.subTest(label=label):
                self.tearDown_rig()
                hist, result, cmd = self.begin_retry(1)
                o = self.o
                discard(o)
                discard(o)                                                                            # idempotent
                lines = self.settled()
                contract(self.released() and getattr(o, "jump_expectation", None) is None and len(lines) == 1 and lines[0].get("end") in ("cleanup", "scenario-changed"), "N-42",
                         "pending-survives-release", "%s: released=%r diagnostics=%r" % (label, self.released(), [l.get("end") for l in lines]))

    @red("N-42", "pending-survives-release")
    def test_N42_the_shutdown_of_the_application_ends_the_open_transaction_once(self):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        contract(hasattr(o, "_jump_transaction_finish"), "N-42", "pending-survives-release", "no shutdown hook of the open transaction")
        for _ in range(2):
            o._jump_transaction_finish("shutdown")
        lines = self.settled()
        closed = o.retry_pending is None and getattr(o, "jump_expectation", None) is None
        contract(closed and len(lines) == 1 and lines[0].get("end") == "shutdown", "N-42", "pending-survives-release", "closed=%r diagnostics=%r" % (closed, [l.get("end") for l in lines]))
        source = read("main.py")
        run = functions_of(source, "run_managed")
        self.assertEqual(len(run), 1)
        text = ast.get_source_segment(source, run[0])
        call = 'transaction_finish("shutdown")'
        contract(call in text and text.index(call) < text.index("jump_client.close()"), "N-42", "pending-survives-release",
                 "run_managed does not end the transaction before it closes the client")

    @guard("N-43")
    def test_N43_the_retry_count_grows_with_the_sent_request_only(self):
        for label in ("success", "failure", "timeout"):
            with self.subTest(label=label):
                self.tearDown_rig()
                self.go(STALIST5)
                r, o = self.r, self.o
                self.stub_menu()
                o.is_scoring_mode = True
                o.save_data = self.history(4)
                o.total_retry_count = 2
                o.menu_state, o.menu_cursor, o.target_retry_idx = 3, 0, 1
                o.handle_menu_enter(True)
                self.assertEqual(o.total_retry_count, 3)                                              # +1 at the sent request
                cmd = r.last_command()
                if label == "success":
                    self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])
                    self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])      # the same RequestId again
                elif label == "failure":
                    self.deliver(completion_v2("STA", 2, 1000.0, self.scope_now()), cmd["request_id"])
                else:
                    r.clock32.now += 11.0
                    r.send("STATUS:LOADED:RUNNING")
                self.assertEqual(o.total_retry_count, 3, label)

    @red("N-44", "diagnostic-absent")
    def test_N44_one_line_per_transaction_160_characters_and_the_G_RC_1b_items(self):
        hist, result, cmd = self.begin_retry(1)
        r, o = self.r, self.o
        sent_id = [l for l in r.jump_lines if "event=command-sent" in l][-1].split("id=")[1].split()[0]
        r.clock32.now += 11.0
        r.send("STATUS:LOADED:RUNNING")
        r.send("STATUS:LOADED:RUNNING")
        r.tick(5)
        lines = self.settled()
        contract(len(lines) == 1, "N-44", "diagnostic-absent", "diagnostic lines: %d" % len(lines))
        d = lines[0]
        scope = self.scope_now()
        self.assertLessEqual(d["_len"], 160, d["_line"])
        expect = {"id": sent_id, "ri": "1", "sc": "%d:%s:%d" % (scope.scenario_id, scope.list_id, scope.count), "rl": "1000", "cmd": "STA", "comp": "0", "lv": "none", "kind": "retry", "end": "timeout"}
        for key, value in expect.items():
            contract(d.get(key) == value, "N-44", "diagnostic-absent", "%s=%r, expected %r in %r" % (key, d.get(key), value, d["_line"]))
        self.assertRegex(d["age"], r"^1[01]\.\d$")
        self.assertRegex(d["_line"], r"^[\[\]A-Za-z0-9=:._/\- ]+$")                                   # fixed characters only: no raw body, no path, no token

    @red("N-44", "diagnostic-absent")
    def test_N44_a_success_names_the_history_before_and_after_and_a_duplicate_adds_no_second_line(self):
        hist, result, cmd = self.begin_retry(1)
        text = completion_v2("STA", 1, 1000.0, self.scope_now())
        self.deliver(text, cmd["request_id"])
        self.deliver(text, cmd["request_id"])                                                         # the same RequestId again
        self.deliver(text, cmd["request_id"], ticks=3)
        lines = self.settled()
        contract(len(lines) == 1, "N-44", "diagnostic-absent", "diagnostic lines: %d" % len(lines))
        d = lines[0]
        self.assertEqual((d["end"], d["comp"], d["lv"], d.get("h"), d.get("c")), ("ok", "1", "ok", "4/2", "2"))

    @red("N-50", "stale-not-recorded")
    def test_N50_a_stale_completion_changes_nothing_is_recorded_and_the_real_one_still_settles(self):
        hist, result, cmd = self.begin_retry(1)
        r, o = self.r, self.o
        old = cmd["request_id"]
        # the open transaction ends with the session; its RequestId is stale from now on
        import managed_input
        managed_input.discard_scoring_session(o)
        hist2, result2, cmd2 = self.begin_retry(1)                                                    # a new transaction with a new RequestId (the same rig: the scene is built again)
        self.assertNotEqual(old, cmd2["request_id"])
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), old)
        self.assertTrue(o.is_official_jumping and o.retry_pending is not None and len(o.save_data) == 4)       # nothing was released by the stale completion
        exp = getattr(o, "jump_expectation", None)
        contract(exp is not None and exp.received == 1 and exp.last == "stale", "N-50", "stale-not-recorded", "expectation after the stale completion: %r" % (exp,))
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd2["request_id"])
        lines = self.settled()
        self.assertTrue(self.released())
        self.assertEqual(len(o.save_data), 2)
        self.assertEqual(len(lines), 2)                                                               # the first transaction ended with the session, the second with its completion
        self.assertEqual((lines[-1].get("end"), lines[-1].get("lv")), ("ok", "ok"))

    @red("N-55", "identity-flap-fails-the-settlement")
    def test_N55_an_identity_that_is_unusable_for_a_moment_does_not_fail_a_jump_that_proves_its_request(self):
        """The published identity (bve_list_id) can be empty for a moment after a jump while the adopted station list has not changed; the settlement asks the world of the request (scenario, the
        adopted list) and not the identity sync."""
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        scope = self.scope_now()
        o.bve_list_id = ""
        self.deliver(completion_v2("STA", 1, 1000.0, scope), cmd["request_id"])
        lines = self.settled()
        contract(self.released() and o.is_scoring_mode and [c["station_name"] for c in o.save_data] == ["A", "B"] and len(lines) == 1 and lines[0].get("end") == "ok", "N-55", "identity-flap-fails-the-settlement",
                 "released=%r scoring=%r history=%r diagnostics=%r" % (self.released(), o.is_scoring_mode, [c["station_name"] for c in o.save_data], [l.get("end") for l in lines]))

    @red("N-54", "settlement-exception-sticks")
    def test_N54_an_exception_inside_the_settlement_still_releases_the_open_jump_and_keeps_the_history(self):
        contract(have("judge_completion"), "N-54", "settlement-exception-sticks", "jump_transaction.judge_completion does not exist")
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        history_object = o.save_data
        content = [dict(c) for c in hist]
        with mock.patch.object(JT, "judge_completion", side_effect=RuntimeError("boom")):
            self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])
        lines = self.settled()
        ok = self.released() and self.aborted() and o.save_data is history_object and [dict(c) for c in o.save_data] == content and len(lines) == 1 and lines[0].get("end") == "internal-error"
        contract(ok, "N-54", "settlement-exception-sticks", "released=%r aborted=%r diagnostics=%r" % (self.released(), self.aborted(), [l.get("end") for l in lines]))

    @red("N-56", "duplicate-not-recorded")
    def test_N56_a_duplicate_of_a_finished_request_that_arrives_while_the_next_transaction_is_open_changes_nothing(self):
        hist, result, cmd = self.begin_retry(1)
        r, o = self.r, self.o
        first = cmd["request_id"]
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), first)                       # the first transaction ends in a success: the history is [A, B]
        self.assertFalse(o.is_official_jumping)
        result2 = self.S.execute_retry(o, 1, True)                                                    # the next retry opens the next transaction (a new RequestId)
        self.assertTrue(result2.accepted)
        second = r.last_command()["request_id"]
        self.assertNotEqual(first, second)
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), first)                       # the duplicate of the FIRST request
        exp = getattr(o, "jump_expectation", None)
        contract(exp is not None and exp.received == 1 and exp.last == "dup" and o.is_official_jumping and o.retry_pending is not None and o.is_scoring_mode, "N-56", "duplicate-not-recorded",
                 "expectation after the duplicate: %r (jump=%r scoring=%r)" % (exp, o.is_official_jumping, o.is_scoring_mode))
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), second)
        self.assertTrue(self.released())
        self.assertEqual(len(self.settled()), 2)                                                      # one final line per transaction, no more

    @red("N-51", "v1-completion-settles")
    def test_N51_a_v1_completion_is_never_a_formal_success(self):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        self.deliver("JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0, cmd["request_id"])                    # right RequestId, right index, right position - but no scope: nothing is proven
        lines = self.settled()
        contract(self.released() and self.aborted() and len(o.save_data) == 4 and len(lines) == 1 and lines[0].get("end") == "unsupported-completion-version", "N-51", "v1-completion-settles",
                 "released=%r aborted=%r history %d diagnostics=%r" % (self.released(), self.aborted(), len(o.save_data), [l.get("end") for l in lines]))


class F_Arrival(MBase):
    def arrive_at(self, index):
        o = self.o
        s = o.station_list[index]
        o.is_scoring_mode, o.is_scoring_finished = True, False
        o.bve_next_loc = o.prev_next_loc = s["location"]
        o.bve_location = s["location"] - 4.0
        o.bve_is_pass = 1
        o.bve_arr_idx = index
        o.bve_current_station_name = s["name"]
        self.S.create_save_data(o)

    @red("N-45", "duplicate-after-retry")
    def test_N45_the_first_arrival_after_a_successful_retry_makes_no_duplicate(self):
        hist, result, cmd = self.begin_retry(1)
        o = self.o
        self.deliver(completion_v2("STA", 1, 1000.0, self.scope_now()), cmd["request_id"])
        self.arrive_at(1)
        self.arrive_at(2)
        names = [c["station_name"] for c in o.save_data]
        contract(names == ["A", "B", "C"], "N-45", "duplicate-after-retry", "history after the first arrivals: %r" % (names,))

    @red("N-45", "duplicate-after-retry")
    def test_N45_the_cut_is_done_before_the_arrival_even_when_both_come_in_one_batch(self):
        hist, result, cmd = self.begin_retry(1)
        r, o = self.r, self.o
        arrival = self.MR.tele(1, time_ms=T0 + 90000, speed=0.0, loc=1996.0, STIDX=self.MR.stidx(STALIST5, 2)).replace("NEXTLOC:1000.0", "NEXTLOC:2000.0", 1).replace("ISPASS:0", "ISPASS:1", 1)       # (one NEXTLOC, as a sender writes it: the STIDX unit reads the first)
        r.send_raw(r.wrap(arrival), r.wrap(completion_v2("STA", 1, 1000.0, self.scope_now()), request_id=cmd["request_id"]))
        names = [c["station_name"] for c in o.save_data]
        contract(names == ["A", "B"] and not o.is_official_jumping, "N-45", "duplicate-after-retry", "history before any tick: %r jump=%r" % (names, o.is_official_jumping))


class G_StartJump(MBase):
    @red("N-48", "start-completion-not-judged")
    def test_N48_the_start_has_its_own_expectation_and_a_wrong_station_aborts_without_touching_the_history(self):
        cmd = self.start(end_idx=2)
        o = self.o
        exp = getattr(o, "jump_expectation", None)
        contract(exp is not None and exp.purpose == "start" and exp.station_index == 0 and exp.request_id == cmd["request_id"], "N-48", "start-completion-not-judged",
                 "expectation %r" % (exp,))
        first = o.save_data[0]
        self.assertEqual(len(o.save_data), 1)
        self.deliver(completion_v2("STA", 1, 0.0, self.scope_now()), cmd["request_id"])
        lines = self.settled()
        contract(self.released() and self.aborted() and len(o.save_data) == 1 and o.save_data[0] is first and len(lines) == 1 and lines[0].get("end") == "selected-index-mismatch"
                 and lines[0].get("kind") == "start", "N-48", "start-completion-not-judged", "released=%r aborted=%r diagnostics=%r" % (self.released(), self.aborted(), [l.get("end") for l in lines]))

    @red("N-48", "start-completion-not-judged")
    def test_N48_a_matching_completion_of_the_start_releases_and_never_cuts_the_history(self):
        cmd = self.start(end_idx=2)
        o = self.o
        first = o.save_data[0]
        with mock.patch.object(station_identity, "resolve_retry_history", side_effect=AssertionError("called")) as spy:
            self.deliver(completion_v2("STA", 0, 0.0, self.scope_now()), cmd["request_id"])
        lines = self.settled()
        contract(self.released() and o.is_scoring_mode and len(o.save_data) == 1 and o.save_data[0] is first and not spy.called and len(lines) == 1 and lines[0].get("end") == "ok"
                 and lines[0].get("kind") == "start", "N-48", "start-completion-not-judged", "released=%r scoring=%r diagnostics=%r" % (self.released(), o.is_scoring_mode, [l.get("end") for l in lines]))

    @red("N-48", "start-completion-not-judged")
    def test_N48_the_start_that_never_completes_is_released_at_the_deadline(self):
        cmd = self.start(end_idx=2)
        r, o = self.r, self.o
        r.clock32.now += 11.0
        r.send("STATUS:LOADED:RUNNING")
        lines = self.settled()
        contract(self.released() and self.aborted() and len(lines) == 1 and lines[0].get("end") == "timeout" and lines[0].get("kind") == "start", "N-48", "start-completion-not-judged",
                 "released=%r aborted=%r diagnostics=%r" % (self.released(), self.aborted(), [l.get("end") for l in lines]))


# ==============================================================================================================================================
# H - the normal mode (development / diagnostic compatibility, not a formal transaction)
# ==============================================================================================================================================
    @red("N-53", "unwritable-start-not-refused")
    def test_N53_a_start_whose_request_the_wire_can_not_carry_is_refused_before_anything_changes(self):
        self.go(STALIST_FAR)
        r, o = self.r, self.o
        o.setting_start_idx = 0
        o.setting_end_idx = 2
        before = len(r.jump_commands())
        r.start_scoring_via_menu()
        refused = [line for line in r.events("scoring-start-refused")]
        contract((not o.is_scoring_mode) and (not o.is_official_jumping) and o.save_data == [] and len(r.jump_commands()) == before and len(refused) == 1 and " why=location-invalid" in refused[0],
                 "N-53", "unwritable-start-not-refused",
                 "scoring=%r jump=%r history=%d commands %d->%d refusals=%r" % (o.is_scoring_mode, o.is_official_jumping, len(o.save_data), before, len(r.jump_commands()), refused))


class E2_UnwritableRetry(MBase):
    @red("N-53", "unwritable-retry-not-refused")
    def test_N53_a_retry_whose_request_the_wire_can_not_carry_is_refused_and_changes_nothing(self):
        self.go(STALIST5)
        r, o = self.r, self.o
        self.stub_menu()
        o.is_scoring_mode = True
        o.save_data = hist = self.history(4)
        o.total_retry_count = 2
        o.score = 77
        o.station_list[1]["location"] = 2.0e9                                                         # the station list holds a position the wire can not carry
        o.save_data[1]["station_location"] = 2.0e9
        before = (list(o.save_data), o.total_retry_count, o.score, o.is_official_jumping, len(r.jump_commands()))
        result = self.S.execute_retry(o, 1, True)
        after = (list(o.save_data), o.total_retry_count, o.score, o.is_official_jumping, len(r.jump_commands()))
        contract((not result.accepted) and result.reason == "location-invalid" and before == after and o.retry_pending is None and getattr(o, "jump_expectation", None) is None, "N-53",
                 "unwritable-retry-not-refused", "accepted=%r reason=%r unchanged=%r" % (result.accepted, result.reason, before == after))


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter")
class H_NormalMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["st3d-normal"])
        import main
        import scoring_logic
        cls.main, cls.S = main, scoring_logic

    def setUp(self):
        self.rig = R.Rig(self.main)
        self.addCleanup(self.rig.close)
        o = self.o = self.rig.o
        self.lines = []
        o.input_event_sink = lambda event, **fields: self.lines.append((event, fields))
        stations = station_identity.StationList([R.station("A", 0.0), R.station("B", 1000.0), R.station("C", 2000.0), R.station("D", 3000.0), R.station("E", 4000.0, terminal=True)],
                                                list_id=R.SCOPE_LIST_ID)
        o.station_list = stations
        o.current_scenario_id, o.bve_list_id = R.SCOPE_SID, R.SCOPE_LIST_ID
        o.bve_time_ms = T0
        o.toggle_menu = lambda adv: None
        o.is_scoring_mode = True
        scope = tuple(station_identity.scope_of(R.SCOPE_SID, R.SCOPE_LIST_ID, stations))
        o.save_data = [{"loc": s["location"], "time_ms": T0 + 60000 * i, "score": 0, "target_loc": s["location"], "station_name": s["name"], "stop_error": 0.0,
                        "score_details": dict(ZERO), "station_index": i, "scope": scope, "station_location": s["location"],
                        "role": "scoring_start" if i == 0 else "arrived_station"} for i, s in enumerate(list(stations)[:4])]
        self.scope = station_identity.StationScope(*scope)

    def begin(self):
        o = self.o
        self.assertTrue(self.S.execute_retry(o, 1, True).accepted)
        self.assertEqual(len(o.udp_socket.written), 1)
        text = o.udp_socket.written[-1][0].decode("utf-8")
        return text

    def plain(self, text):
        self.o.udp_socket.incoming = [text.encode("utf-8")]
        self.o.read_udp_data()

    def ends(self):
        return [f.get("end") for e, f in self.lines if e == "jump-settled"]

    @red("N-47", "normal-mode-writes-v1")
    def test_N47_the_normal_mode_writes_the_same_v2_text_to_the_plain_port(self):
        text = self.begin()
        expected, why = jump_wire.format_request_v2("STA", 1, T0 + 60000, tuple(self.scope), 1000.0)
        self.assertIsNone(why)
        contract(text == expected, "N-47", "normal-mode-writes-v1", "sent %r, the v2 text is %r" % (text, expected))
        self.assertEqual(self.o.udp_socket.written[-1][1], 54322)

    @red("N-47", "normal-mode-cuts-or-sticks")
    def test_N47_a_matching_completion_resumes_the_scoring_but_the_normal_mode_never_cuts_the_history(self):
        o = self.o
        self.begin()
        hist = o.save_data
        self.assertEqual(o.retry_pending.state, "sent")
        self.plain(completion_v2("STA", 1, 1000.0, self.scope))
        contract((not o.is_official_jumping) and o.retry_pending is None and o.save_data is hist and len(o.save_data) == 4 and self.ends() == ["ok-plain"], "N-47",
                 "normal-mode-cuts-or-sticks", "jump=%r pending=%r history %d ends=%r" % (o.is_official_jumping, o.retry_pending, len(o.save_data), self.ends()))

    @red("N-47", "normal-mode-cuts-or-sticks")
    def test_N47_a_v1_completion_or_a_mismatch_aborts_the_normal_mode_too(self):
        for label, text in (("v1", "JUMP_COMPLETE:STA:1:1000.0:%d:1" % T0), ("index", completion_v2("STA", 2, 1000.0, self.scope)), ("position", completion_v2("STA", 1, 999.0, self.scope))):
            with self.subTest(label=label):
                self.rig.close()
                self.setUp()
                o = self.o
                self.begin()
                hist = o.save_data
                self.plain(text)
                contract((not o.is_official_jumping) and o.retry_pending is None and o.save_data is hist and len(self.ends()) == 1 and (not o.is_scoring_mode) and o.jump_lock, "N-47",
                         "normal-mode-cuts-or-sticks", "%s: jump=%r pending=%r ends=%r scoring=%r" % (label, o.is_official_jumping, o.retry_pending, self.ends(), o.is_scoring_mode))

    @red("N-47", "normal-mode-never-released")
    def test_N47_without_any_completion_the_deadline_releases_the_normal_mode(self):
        o = self.o
        self.begin()
        self.rig.clock.now += 11.0
        self.plain("STATUS:LOADED:RUNNING")
        contract((not o.is_official_jumping) and o.retry_pending is None and self.ends() == ["timeout"] and not o.is_scoring_mode, "N-47", "normal-mode-never-released",
                 "jump=%r pending=%r ends=%r" % (o.is_official_jumping, o.retry_pending, self.ends()))

    @red("N-47", "normal-mode-never-released")
    def test_N47_a_scenario_change_releases_the_open_transaction_of_the_normal_mode(self):
        o = self.o
        self.begin()
        o.current_scenario_id = 3
        o.apply_telemetry_text("SCENARIO_ID:4,TIME:%d" % T0)
        contract((not o.is_official_jumping) and o.retry_pending is None and getattr(o, "jump_expectation", None) is None, "N-47", "normal-mode-never-released",
                 "jump=%r pending=%r" % (o.is_official_jumping, o.retry_pending))


class Z_Meta(unittest.TestCase):
    def test_every_st3d_test_has_a_declared_code_and_t07_is_executed_here_once(self):
        found = {}
        for cls in (A_Static, B_Pure, C_Writers, D_Settlement, E_Release, F_Arrival, G_StartJump, E2_UnwritableRetry, H_NormalMode):
            for name in sorted(n for n in dir(cls) if n.startswith("test_")):
                meta = getattr(getattr(cls, name), "st3d", None)
                if meta is None:
                    continue
                self.assertIn(meta["kind"], ("RED", "GUARD"), name)
                if meta["kind"] == "RED":
                    self.assertRegex(meta["code"], r"^[A-Za-z0-9\-]+$", name)
                found.setdefault(meta["id"], []).append(name)
        self.assertIn("T07", found)
        self.assertEqual(len(found["T07"]), 1)
        for tid in ("N-21b", "N-21c", "N-39", "N-40", "N-41", "N-42", "N-43", "N-44", "N-45", "N-46", "N-47", "N-48", "N-49", "N-50", "N-51", "N-52", "N-53", "N-54", "N-55", "N-56", "N-70", "N-71", "N-72", "N-75"):
            self.assertIn(tid, found, tid)

    def test_this_file_writes_nothing_and_reads_no_desktop(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            code = f.read()
        for word in ("os." "system", "expand" "user", "\\" "Desk" "top", "Down" "loads", "sock" "et.sock" "et", "QUdp" "Socket("):
            self.assertNotIn(word, code, word)


if __name__ == "__main__":
    unittest.main()
