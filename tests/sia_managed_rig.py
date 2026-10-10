"""Phase SI-A test rig for the MANAGED mode: the real Overlay (tests/sia_rig.py: every outside effect a recorder), the real strict TelemetryGate, the real
ManagedHudController with a fake state block and a fake HUD window API (the fixtures of the E4 tests), and the real ManagedInputController attached by the
production function main._attach_managed_hud. The Caller's state block is a byte buffer that the test publishes; the sender's UDP datagrams are pushed into the
stub socket.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import managed_hud as mh  # noqa: E402
import managed_state as ms  # noqa: E402
import sia_rig as R  # noqa: E402
import telemetry_gate  # noqa: E402
import test_managed_hud_e4 as E4  # noqa: E402  (its fixtures only: FakeSource, make_block, FakeWindowApi, FakeTimer, Clock, Log, args_for)

BVE_HWND = 5000
_KEEP = object()

STALIST = "STALIST:A=1=0.0=-1=-1=-1=15000=0=0,B=1=1000.0=-1=-1=-1=15000=0=0,C=0=2500.0=-1=-1=-1=15000=0=1"


def tele(sid, time_ms=36000000, speed=0.0, loc=0.0, avail=None, brk="N:0:8", btype="Ecb", **keys):
    """One telemetry line of the Current sender (no AVAIL unless given); keys are appended as KEY:value. brk = 'text:notch:max'."""
    parts = ["SCENARIO_ID:%d" % sid, "TIME:%d" % time_ms, "LOCATION:%s" % loc, "SPEED:%s" % speed, "BTYPE:%s" % keys.pop("BTYPE", btype), "BRK:%s" % brk,
             "NEXTLOC:1000.0", "NEXTTIME:%d" % (time_ms + 60000),
             "ISPASS:0", "ISTIMING:1", "DOORDIR:1", "DOOR:0", "TERM:0", "CAB:8:0", "PRATES:0_0.1_0.2_0.3_0.4_0.5_0.6_0.7_0.8:440.0", "JUMP:0"]
    for k, v in keys.items():
        parts.append("%s:%s" % (k, v))
    if avail is not None:
        parts.append("AVAIL:1:" + "+".join(avail))
    return ",".join(parts)


class RigKeys(object):
    """The physical keys and the foreground window as pause_recovery sees them (Phase SI-A6): a set of virtual-key codes held down and the process id of the
    window in front. Not the `keyboard` module of the Overlay: a test presses F5 / P for the recovery without the Overlay's own key handling reacting."""

    def __init__(self, foreground_pid):
        self.down = set()
        self.foreground = foreground_pid
        self.queries = 0

    def is_down(self, vk):
        self.queries += 1
        return vk in self.down

    def foreground_pid(self):
        return self.foreground


class ManagedRig(object):
    def __init__(self, m, capture_log=True):
        self.m = m
        self.rig = R.Rig(m, hwnd=BVE_HWND, capture_log=capture_log)
        self.o = self.rig.o
        self.kb, self.gui, self.api_win32, self.clock32 = self.rig.kb, self.rig.gui, self.rig.api, self.rig.clock
        self.args = E4.args_for()
        self.log = E4.Log()
        self.source = E4.FakeSource(E4.make_block(self.args.bve_pid, self.args.instance))
        reader = ms.StateReader(self.args, self.source, self.log)
        self.win = E4.FakeWindowApi()
        self.win.hwnd = BVE_HWND
        self.win.z = [BVE_HWND]
        self.timer = E4.FakeTimer()
        self.clock = E4.Clock()
        self.gate = telemetry_gate.TelemetryGate(strict=True)
        self.o.telemetry_gate = self.gate
        self.hud = mh.ManagedHudController(self.o, reader, self.win, self.args, self.log, timer=self.timer, clock=self.clock, telemetry=self.gate)
        self.gate.log = self.hud.emit_event
        self.keys = RigKeys(self.args.bve_pid)
        self.load = None                    # Phase SI-A6: None = a Bridge / Caller from before the load marker; otherwise the LoadInfo bits every publish() carries
        self.attached = m._attach_managed_hud(self.o, self.hud, recovery_keys=self.keys)
        self.recovery = self.hud.recovery
        self.input = self.hud._input
        self.count = 0
        self.generation = 0
        # a real file-less state: nothing published yet (Session OFF, Driving OFF)

    def close(self):
        try:
            self.hud.shutdown()
        except Exception:
            pass
        self.rig.close()

    # -- the Caller's state block -------------------------------------------------------------------------------------------------------------
    def publish(self, session=False, driving=False, generation=None, closed=False, load=_KEEP):
        if generation is not None:
            self.generation = generation
        if load is not _KEEP:
            self.load = load
        self.count += 1
        self.source.data = E4.make_block(self.args.bve_pid, self.args.instance, session, driving, closed, self.generation, self.count,
                                         load_info=0 if self.load is None else self.load, load_magic=0 if self.load is None else ms.LOAD_MAGIC)

    def tick(self, n=1, seconds=0.02):
        for _ in range(n):
            self.clock.t += seconds
            self.rig.advance(seconds)
            self.hud.tick()

    # -- the sender's datagrams -----------------------------------------------------------------------------------------------------------------
    def send(self, *texts):
        """Pushes datagrams into the stub socket and lets the Overlay read them (the way readyRead does)."""
        self.o.udp_socket.incoming.extend(t.encode("utf-8") for t in texts)
        self.o.read_udp_data()

    def events(self, name):
        return self.log.events(name)

    def go_active(self, sid=1, generation=1, with_stations=True, **kw):
        """Session ON, Driving ON, the first telemetry (and the station list) of a generation: the HUD shows, the input is live."""
        self.publish(True, True, generation)
        self.tick(2)
        if with_stations:
            self.send(STALIST, tele(sid, **kw))
        else:
            self.send(tele(sid, **kw))
        self.tick(2)
        return self

    # -- the user ---------------------------------------------------------------------------------------------------------------------------------
    def tap(self, key):
        self.kb.pressed.discard(key)
        self.tick()
        self.kb.pressed.add(key)
        self.tick()
        self.kb.pressed.discard(key)

    def press(self, vk, ticks=2):
        """A physical key (virtual-key code) for a few slots: the edge is seen once."""
        self.keys.down.add(vk)
        self.tick(ticks)
        self.keys.down.discard(vk)
        self.tick()

    def start_scoring_via_menu(self):
        o = self.o
        self.tap("f1")
        assert o.menu_state == 1, o.menu_state
        self.tap("down")
        self.tap("enter")
        for _ in range(5):
            self.tap("down")
        self.tap("enter")
        for _ in range(6):
            self.tap("down")
        self.tap("enter")
        assert o.menu_state == 10, o.menu_state
        self.tap("down")
        self.tap("enter")
