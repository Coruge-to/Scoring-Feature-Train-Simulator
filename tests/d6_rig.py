"""PID-D6 test rig: the managed Overlay of tests/sia_managed_rig.py with the production DataPlane wiring of run_managed - a strict Telemetry receiver and the jump
client - and a stand-in for the Current plugin on the other side of the loopback:

  * every datagram the Overlay writes to the published jump port is decoded as the Current jump endpoint would (Envelope v1, RequestId),
  * the stand-in answers like Current: telemetry (type 1), heartbeat (type 2), station list (type 3) and JUMP_COMPLETE (type 5, RequestId echoed) as envelopes
    for the Overlay's Telemetry endpoint.

No socket, no named mapping, no clock of the machine: the jump directory is a byte buffer that the test edits, the clock is the rig's fake time.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import current_jump_client  # noqa: E402
import dataplane_contract as contract  # noqa: E402
import sia_managed_rig as MR  # noqa: E402
import telemetry_dataplane_receiver  # noqa: E402

TELEMETRY_GEN = 7
TELEMETRY_TOKEN = bytes(range(1, 17))
JUMP_PORT = 41000
JUMP_GEN = 11
JUMP_TOKEN = bytes(range(101, 117))
APP_PID = 55555


class FakeJumpDirectory(object):
    """The read-only mapping source of the jump client: a 128-byte Current Jump Receiver Directory block that the test publishes."""

    def __init__(self, bve_pid, port=JUMP_PORT, generation=JUMP_GEN, token=JUMP_TOKEN, caps=contract.JUMP_CAP_STATION_TIME | contract.JUMP_CAP_LOCATION_TIME | contract.JUMP_CAP_REQUEST_ID):
        self.bve_pid = bve_pid
        self.port, self.generation, self.token, self.caps = port, generation, token, caps
        self.state = contract.PUBLISHED | contract.READY
        self.sequence = 0
        self.change = 0
        self.present = True
        self.opened = False
        self.reads = 0
        self.publish()

    def publish(self, state=None, port=None, generation=None, token=None, caps=None):
        if state is not None:
            self.state = state
        if port is not None:
            self.port = port
        if generation is not None:
            self.generation = generation
        if token is not None:
            self.token = token
        if caps is not None:
            self.caps = caps
        self.sequence += 2
        self.change += 1
        if self.state == contract.CLOSED:
            self.block = contract.encode_jump_directory(self.bve_pid, self.sequence, self.state, 0, 0, 0, bytes(16), self.change, 0)
        else:
            self.block = contract.encode_jump_directory(self.bve_pid, self.sequence, self.state, self.bve_pid, self.port, self.generation, self.token,
                                                        self.change, self.caps)

    def withdraw(self):
        self.publish(contract.PUBLISHED | contract.READY | contract.WITHDRAWING)

    def close_directory(self):
        self.publish(contract.CLOSED)

    # the source interface of managed_app_directory.Win32DirectorySource
    def open(self, name):
        assert name == contract.jump_name(self.bve_pid), name
        if not self.present:
            return False
        self.opened = True
        return True

    def read(self):
        self.reads += 1
        return self.block if self.opened else None

    def close(self):
        self.opened = False


class D6Rig(MR.ManagedRig):
    def __init__(self, m, **kw):
        super().__init__(m, **kw)
        o = self.o
        self.instance = self.args.instance
        self.pid = self.args.bve_pid
        self.dataplane_lines = []
        self.receiver = telemetry_dataplane_receiver.TelemetryDataPlaneReceiver(self.pid, self.instance, TELEMETRY_GEN, TELEMETRY_TOKEN, self.dataplane_lines.append)
        self.jump_lines = []
        self.jump_dir = FakeJumpDirectory(self.pid)
        self.client = current_jump_client.CurrentJumpClient(
            self.pid, self.instance, APP_PID, lambda data, port: o._send_jump_datagram(data, port), source=self.jump_dir, log=self.jump_lines.append,
            clock=self.clock32.monotonic)
        # exactly the wiring of run_managed (Caller owner): strict, the receiver of the published Telemetry endpoint, the jump client
        o.dataplane_strict = True
        o.dataplane_receiver = self.receiver
        o.jump_client = self.client
        self.consumed = 0                      # how many of o.udp_socket.written the stand-in has looked at

    # -- the stand-in for Current: Telemetry side -----------------------------------------------------------------------------------------------
    def wrap(self, text, request_id=None):
        if text.startswith("STALIST:"):
            mtype = contract.MSG_STATION_LIST
        elif text.startswith("META:"):
            mtype = contract.MSG_METADATA
        elif text.startswith("STATUS:"):
            mtype = contract.MSG_HEARTBEAT
        elif text.startswith("JUMP_COMPLETE:"):
            mtype = contract.MSG_JUMP_COMPLETE
        else:
            mtype = contract.MSG_TELEMETRY
        rid = bytes(16) if request_id is None else request_id
        return contract.encode_envelope(mtype, self.pid, self.pid, TELEMETRY_GEN, self.instance, TELEMETRY_TOKEN, rid, text.encode("utf-8"))

    def send(self, *texts):
        """Telemetry / heartbeat / station list as Envelope v1 (the managed success path); read the way readyRead does."""
        self.o.udp_socket.incoming.extend(self.wrap(t) for t in texts)
        self.o.read_udp_data()

    def send_raw(self, *datagrams):
        self.o.udp_socket.incoming.extend(datagrams)
        self.o.read_udp_data()

    # -- the stand-in for Current: jump side ------------------------------------------------------------------------------------------------------
    def jump_commands(self):
        """Every datagram written to the published jump port so far, decoded (the other writes - none are expected - are returned as ('other', port, data))."""
        out = []
        for data, port in self.o.udp_socket.written:
            if port == self.jump_dir.port:
                env = contract.decode_envelope(data)
                out.append(dict(env, text=env["payload"].decode("utf-8"), data=data))
            else:
                out.append(dict(other=True, port=port, data=data))
        return out

    def last_command(self):
        commands = [c for c in self.jump_commands() if not c.get("other")]
        return commands[-1] if commands else None

    def complete(self, request_id, location=0.0, time_ms=36000000, count=1, kind="STA", index=0):
        """Current executed the command and answers: a type 5 envelope that echoes `request_id` (the text is the unchanged legacy JUMP_COMPLETE)."""
        text = "JUMP_COMPLETE:%s:%d:%s:%d:%d" % (kind, index, location, time_ms, count)
        self.send_raw(self.wrap(text, request_id=request_id))
