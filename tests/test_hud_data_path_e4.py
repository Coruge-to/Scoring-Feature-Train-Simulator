"""Phase E4 completion - the DATA path of the existing HUD (not the state link): who sends the telemetry, what the HUD reads, and what a host
without a sender looks like. Standard library only (the integration part needs PyQt6 and a free UDP port 54321).

    C:\\Python314\\python.exe -m unittest tests.test_hud_data_path_e4 -v

(A) static audit of the repository: the only source that sends on UDP 54321 is the BveEX (Current API) telemetry plugin; no AtsEX Legacy source
    sends anything; no Handshake component (Caller, Current Bridge, Legacy Bridge) touches a socket; the key vocabulary the plugin emits equals the
    vocabulary the Overlay parses; the audit document names every key.
(B) integration with the REAL Overlay (offscreen): without any sender (the Legacy situation) the HUD data stays at its start-up defaults for ever;
    with a datagram in the format of the existing sender the same HUD data path updates every value, so a sender of that format would be enough.
No BVE and no BveEX is started; a running TS Scoring (UDP 54321 busy) is never touched: part B is then skipped as INCONCLUSIVE.
"""
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_ROOT = os.path.join(ROOT, "TsScoringPlugin")
HANDSHAKE = os.path.join(PLUGIN_ROOT, "Handshake")
TELEMETRY_SOURCE = os.path.join(PLUGIN_ROOT, "TsScoringPlugin", "Class1.cs")
AUDIT_DOC = os.path.join(HANDSHAKE, "Docs", "Handshake-PhaseE4-LegacyTelemetryAudit.md")
HAS_QT = importlib.util.find_spec("PyQt6") is not None

_SKIP_DIRS = {"obj", "bin", "packages", ".git", "out", "dist", "logs"}
# datagram kinds that are not part of the per-Tick "key:value," telemetry line
_OTHER_PACKETS = {"STALIST", "META", "JUMP_COMPLETE", "STATUS"}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def cs_sources():
    found = []
    for base, dirs, files in os.walk(PLUGIN_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(".cs"):
                found.append(os.path.join(base, name))
    return sorted(found)


def code_only(text):
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    return re.sub(r"//.*", "", text)


def emitted_keys():
    """Keys of the per-Tick telemetry line the BveEX plugin builds (`string data = $"KEY:{..},KEY:{..}"`)."""
    src = read(TELEMETRY_SOURCE)
    m = re.search(r'string data = \$"((?:[^"\\]|\\.)*)";', src)
    assert m, "telemetry line not found in the sender source"
    keys = []
    for piece in m.group(1).split(","):
        key = piece.split(":", 1)[0]
        keys.append(key)
    return keys


def parsed_keys():
    """Keys the Overlay's read_udp_data accepts in the telemetry line (everything after the `latest_telemetry` split)."""
    src = read(os.path.join(ROOT, "main.py"))
    body = src[src.index("def read_udp_data"):src.index("def is_station_timing")]
    tail = body[body.index("parts = latest_telemetry.split"):]
    return re.findall(r'part\.startswith\("([A-Z_]+):"\)', tail)


class A_StaticAudit(unittest.TestCase):
    def test_the_udp_54321_senders_are_the_bveex_current_plugin_and_the_l3_legacy_telemetry_sink(self):
        senders = []
        for path in cs_sources():
            code = code_only(read(path))
            if "54321" in code and "UdpClient" in code:
                senders.append(os.path.relpath(path, PLUGIN_ROOT).replace("\\", "/"))
        # Phase L3 added the AtsEX Legacy sender: its only network code is the sink in the shared telemetry contract file (the DATA plane)
        self.assertEqual(senders, ["Handshake/Telemetry/Shared/TelemetryContract.cs", "TsScoringPlugin/Class1.cs"])

    def test_the_sender_uses_the_current_host_api_only(self):
        code = code_only(read(TELEMETRY_SOURCE))
        self.assertIn("using BveEx.PluginHost;", code)
        self.assertNotIn("AtsEx", code)
        self.assertIn("[Plugin(PluginType.Extension)]", code)
        project = read(os.path.join(PLUGIN_ROOT, "TsScoringPlugin", "TsScoringPlugin.csproj"))
        self.assertIn("BveEx.PluginHost", project)
        self.assertNotIn("AtsEx.PluginHost", project)

    def test_no_legacy_source_sends_or_receives_telemetry(self):
        legacy_dir = os.path.join(HANDSHAKE, "Bridge", "Legacy")
        files = [p for p in cs_sources() if p.startswith(legacy_dir + os.sep)]
        self.assertTrue(files)
        for path in files:
            code = code_only(read(path))
            for token in ("UdpClient", "System.Net", "Socket", "54321", "54322", "QUdp"):
                self.assertNotIn(token, code, (os.path.basename(path), token))
        legacy_project = read(os.path.join(legacy_dir, "TSScoringPlugin.AtsExLegacy.Bridge.Prototype.csproj"))
        for token in ("Class1.cs", "AtsLoggerPlugin.cs", "TsScoringPlugin.csproj"):
            self.assertNotIn(token, legacy_project)
        self.assertIn("AtsEx.PluginHost", legacy_project)
        self.assertNotIn("BveEx.PluginHost", legacy_project)

    def test_no_handshake_component_touches_a_socket(self):
        for path in cs_sources():
            if not path.startswith(HANDSHAKE + os.sep) or path.startswith(os.path.join(HANDSHAKE, "Telemetry") + os.sep):
                continue          # Phase L3: the telemetry project is the DATA plane, not a Handshake (control plane) component; it links no Handshake source
            code = code_only(read(path))
            for token in ("UdpClient", "System.Net.Sockets", "TcpClient", "54321", "54322"):
                self.assertNotIn(token, code, (os.path.relpath(path, HANDSHAKE), token))

    def test_the_telemetry_plugin_is_not_linked_into_any_handshake_project(self):
        for base, dirs, files in os.walk(HANDSHAKE):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for name in files:
                if name.endswith(".csproj"):
                    text = read(os.path.join(base, name))
                    self.assertNotIn("Class1.cs", text, name)
                    self.assertNotIn("TsScoringPlugin\\TsScoringPlugin", text.replace("/", "\\"), name)

    def test_emitted_and_parsed_telemetry_vocabularies_are_the_same(self):
        emitted, parsed = emitted_keys(), parsed_keys()
        self.assertEqual(len(emitted), len(set(emitted)), "a key is emitted twice")
        self.assertEqual(set(emitted), set(parsed))

    def test_the_audit_document_names_every_key_and_every_packet_kind(self):
        text = read(AUDIT_DOC)
        for key in emitted_keys():
            self.assertRegex(text, r"(?m)^\|[^|\n]*`%s`[^|\n]*\|" % re.escape(key), key)
        for kind in sorted(_OTHER_PACKETS):
            self.assertRegex(text, r"(?m)^\|[^|\n]*`%s`[^|\n]*\|" % re.escape(kind), kind)

    def test_the_audit_document_states_the_functional_status_without_overclaiming(self):
        text = read(AUDIT_DOC)
        self.assertIn("Legacy HUD functional status", text)
        self.assertRegex(text, r"NOT live-updating|not live-updating")
        self.assertNotRegex(text, r"(?i)legacy[^.\n]{0,40}\b(is|are) (supported|handled|done|accepted)\b")


# ---------------------------------------------------------------------------------------------------------------------------------------
def port_54321_is_free():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 54321))
        return True
    except OSError:
        return False
    finally:
        s.close()


# a per-Tick line in the exact shape of the existing sender (same keys, same order, same separators), with recognisable values
SAMPLE_TELEMETRY = (
    "SCENARIO_ID:12345,SPEED:62.5,TIME:36000000,LOCATION:1234.5,GRADIENT:-12.5,NEXTLOC:2000.0,NEXTTIME:36120000,ISPASS:0,ISTIMING:1,"
    "MARGINB:5.0,MARGINF:5.0,REV:Fwd:1,POW:P3:3,BRK:B2:2:8,HTYPE:2,ALLTXT:Off_Fwd_Rev:N_P1_P2_P3:EB_B1_B2_B3:Hold,SIGLIMIT:75.0,TRAINLEN:80.0,"
    "MAPLIMITS:1500.0=65.0_2500.0=90.0,FWDSIGLIMIT:45.0,FWDSIGLOC:1800.0,DOOR:0,DOORDIR:1,TERM:0,MAPHEAD:75.0,MAPTAIL:75.0,CLEARDIST:0,"
    "CALCG:0.01000,BTYPE:Ecb,JUMP:0,CAB:8:0,BCP:120.0,PRATES:0_100_200:490.0,BPP:490.0:490.0,STATNAME:TestSta,DOORTIME:4630")

_CHILD = r'''
import json, os, socket, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, %(root)r)
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
import main, managed_hud

FIELDS = ["bve_speed", "bve_time_ms", "bve_location", "bve_gradient", "bve_next_loc", "bve_next_time", "bve_is_pass", "bve_is_timing",
          "bve_rev_text", "bve_rev_pos", "bve_pow_text", "bve_pow_notch", "bve_brk_text", "bve_brk_notch", "bve_brk_max", "bve_signal_limit",
          "bve_train_length", "bve_door", "bve_doordir", "bve_term", "bve_current_station_name", "current_scenario_id", "bve_map_limits"]

def snapshot(o):
    d = {k: getattr(o, k, None) for k in FIELDS}
    d["is_bve_loaded"] = bool(getattr(o, "is_bve_loaded", False))
    return d

def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)

o = main.Overlay()
o.timer.stop()
out = {"bound": bool(o.udp_bind_ok)}
pump(0.3)
out["start"] = snapshot(o)
for _ in range(40):                      # the HUD data step, as the managed controller runs it, with NO sender at all
    managed_hud.hud_update_step(o)
    pump(0.01)
out["no_sender_after_updates"] = snapshot(o)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
def send(text):
    sock.sendto(text.encode("utf-8"), ("127.0.0.1", 54321))
send("STATUS:LOADED:RUNNING")
send(%(sample)r)
pump(0.4)
managed_hud.hud_update_step(o)
out["with_sender"] = snapshot(o)
out["last_bve_time_ms"] = o.last_bve_time_ms
out["last_update_time"] = o.last_update_time
send(%(sample2)r)
pump(0.3)
managed_hud.hud_update_step(o)
out["second"] = snapshot(o)
sock.close()
o.udp_socket.close()
print("RESULT " + json.dumps(out))
'''


@unittest.skipUnless(HAS_QT, "PyQt6 is not importable by this interpreter (INCONCLUSIVE for the integration part)")
class B_RealOverlayDataPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = None
        cls.error = None
        if not port_54321_is_free():
            cls.error = "UDP 54321 is busy (a running TS Scoring is not touched)"
            return
        second = SAMPLE_TELEMETRY.replace("SPEED:62.5", "SPEED:71.0").replace("TIME:36000000", "TIME:36001000").replace("LOCATION:1234.5", "LOCATION:1260.0")
        code = _CHILD % {"root": ROOT, "sample": SAMPLE_TELEMETRY, "sample2": second}
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=180, cwd=ROOT, env=env, creationflags=0x08000000)
        text = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        line = [ln for ln in text.splitlines() if ln.startswith("RESULT ")]
        if r.returncode != 0 or not line:
            cls.error = "child failed: " + text[-1500:]
            cls.failed = True
            return
        cls.failed = False
        cls.result = json.loads(line[0][len("RESULT "):])

    def need(self):
        if self.result is None:
            if getattr(self, "failed", False):
                self.fail(self.error)
            self.skipTest(self.error + " - INCONCLUSIVE")
        return self.result

    def test_without_any_sender_the_hud_data_is_fixed_at_its_start_up_defaults(self):
        """The situation of a host that has no telemetry sender (BVE5 Legacy): nothing ever changes, however long the HUD runs."""
        r = self.need()
        self.assertTrue(r["bound"])
        start, later = r["start"], r["no_sender_after_updates"]
        self.assertEqual(start, later)
        self.assertEqual((start["bve_time_ms"], start["bve_speed"], start["bve_location"], start["bve_next_loc"]), (0, 0.0, 0.0, -1.0))
        self.assertEqual((start["bve_rev_text"], start["bve_pow_text"], start["bve_brk_text"]), ("切", "N", "N"))   # placeholders, not BVE values
        self.assertEqual((start["bve_signal_limit"], start["current_scenario_id"], start["is_bve_loaded"]), (1000.0, -1, False))

    def test_a_datagram_in_the_format_of_the_existing_sender_updates_the_whole_hud_data(self):
        r = self.need()["with_sender"]
        expected = {
            "bve_speed": 62.5, "bve_time_ms": 36000000, "bve_location": 1234.5, "bve_gradient": -12.5, "bve_next_loc": 2000.0,
            "bve_next_time": 36120000, "bve_is_pass": 0, "bve_is_timing": 1, "bve_rev_text": "Fwd", "bve_rev_pos": 1, "bve_pow_text": "P3",
            "bve_pow_notch": 3, "bve_brk_text": "B2", "bve_brk_notch": 2, "bve_brk_max": 8, "bve_signal_limit": 75.0, "bve_train_length": 80.0,
            "bve_door": 0, "bve_doordir": 1, "bve_term": 0, "bve_current_station_name": "TestSta", "current_scenario_id": 12345,
            "is_bve_loaded": True,
        }
        for key, value in expected.items():
            self.assertEqual(r[key], value, key)
        self.assertEqual(r["bve_map_limits"], [[1500.0, 65.0], [2500.0, 90.0]])

    def test_the_hud_data_step_carries_the_received_time_on(self):
        res = self.need()
        self.assertEqual(res["last_bve_time_ms"], 36000000)
        self.assertEqual(res["last_update_time"], 36000.0)

    def test_every_later_datagram_moves_the_values_again(self):
        second = self.need()["second"]
        self.assertEqual((second["bve_speed"], second["bve_time_ms"], second["bve_location"]), (71.0, 36001000, 1260.0))

    def test_the_data_path_does_not_know_the_host(self):
        """Nothing in the Overlay's reception names AtsEX, BveEX, Legacy or Current: a sender of the existing format is enough on any host."""
        src = read(os.path.join(ROOT, "main.py"))
        body = src[src.index("def read_udp_data"):src.index("def is_station_timing")]
        for token in ("Legacy", "AtsEx", "ATSEX", "BveEx", "BVEEX", "Current"):
            self.assertNotIn(token, body, token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
