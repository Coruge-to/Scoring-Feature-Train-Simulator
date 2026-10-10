"""Phase E4 - the Session / Driving state of the Caller, as seen by the managed application (no Qt, no scoring, no main.py).

The Caller publishes ONE small named memory block per managed instance (TsScoringPlugin\\Handshake\\Caller\\src\\AppStatePublisher.cs defines the
layout; this module mirrors it byte for byte):

    Local\\TSScoringPlugin.v1.<BVE PID>.App.<INST>.State      (64 bytes, created by the Caller BEFORE it launches this process)

Session  = ScenarioReady is published for the current ScenarioGeneration.   Driving = the Caller's DrivingActive (only ever ON with Session).
Both are levels, not events: every read returns the CURRENT truth, so a missed change converges by itself and a process that starts late reads
the right value immediately. The block belongs to this instance of this BVE process only; a block with another PID / instance in its header is
rejected. Nothing here ever starts, stops or restarts anything: the lifetime of the process stays with the Stop event (managed_mode.py).

The block is a REQUIRED part of the managed contract. At start it must exist and be valid (else: no AppReady, exit code 4, one diagnostic).
After AppReady, a block that stops being valid is a LOSS: HUD hidden and stopped, one diagnostic, no new input, wait for the Stop request
(the process is neither killed nor restarted, the Overlay neither rebuilt nor destroyed). A withdrawal by the Caller (Closed flag) is NOT a
loss; it is the normal end, and it is logged under its own name.

Phase SI-A6 - the LOAD MARKER (bytes 48..55, formerly reserved zero; Version, Size and every earlier field are unchanged):
    48 uint32  LoadInfo   bit0 ScenarioCreated of THIS ScenarioGeneration was received (a BVE event, no Tick needed), bit1 the first Tick of it was received
    52 uint32  LoadMagic  0x4C4F4431 ("LOD1") when the Bridge provided the marker, else 0 = "no information"
Both are written in the same seqlock write as the generation, so one reading shows the generation and the marker of ONE write. A block with LoadMagic 0
(a Bridge or Caller from before SI-A6) is `load_supported = False`: nothing may be concluded from the marker (the automatic P-to-P recovery stays off).

HUD gate (HudGate, pure):
    Session ON  and Driving ON   -> MODE_ACTIVE   (the HUD is shown and updated)
    Session ON  and Driving OFF  -> MODE_WAITING  (soft OFF: the Overlay is kept, the HUD is hidden and not updated)
    Session OFF (or Closed, or no readable block) -> MODE_HIDDEN (hard OFF: the Overlay is kept, the HUD is hidden and not updated)
"""
import ctypes
import struct
import time
from ctypes import wintypes

STATE_MAGIC = 0x53415354  # "TSAS" as a little-endian uint32
STATE_VERSION = 1
STATE_SIZE = 64
INSTANCE_CHARS = 16

OFF_MAGIC, OFF_VERSION, OFF_SIZE, OFF_PID, OFF_INSTANCE = 0, 4, 8, 12, 16
OFF_HEAD, OFF_FLAGS, OFF_GENERATION, OFF_CHANGE_COUNT, OFF_TAIL = 32, 36, 40, 44, 60

FLAG_SESSION = 1
FLAG_DRIVING = 2
FLAG_CLOSED = 4
_KNOWN_FLAGS = FLAG_SESSION | FLAG_DRIVING | FLAG_CLOSED

OFF_LOAD_INFO, OFF_LOAD_MAGIC = 48, 52
LOAD_MAGIC = 0x4C4F4431                     # "LOD1"
LOAD_CREATED = 1                            # ScenarioCreated of the generation was received
LOAD_TICK_SEEN = 2                          # the first Tick of the generation was received
_KNOWN_LOAD_BITS = LOAD_CREATED | LOAD_TICK_SEEN

_HEADER = struct.Struct("<IIII16s")        # magic, version, size, pid, instance prefix  (offsets 0..31)
_BODY = struct.Struct("<IIiI")             # head, flags, generation, change count      (offsets 32..47)
_LOAD = struct.Struct("<II")               # load info, load magic                      (offsets 48..55)
_TAIL = struct.Struct("<I")                # offset 60

MODE_HIDDEN = "hidden"
MODE_WAITING = "waiting"
MODE_ACTIVE = "active"

_READ_ATTEMPTS = 3


def state_name(bve_pid, instance):
    return "Local\\TSScoringPlugin.v1.%d.App.%s.State" % (bve_pid, instance)


class StateSnapshot(object):
    """One consistent reading of the block. `session` / `driving` are the raw flags; use effective_* for the HUD."""
    __slots__ = ("session", "driving", "closed", "generation", "change_count", "head", "load_supported", "load_info")

    def __init__(self, session, driving, closed, generation, change_count, head, load_supported=False, load_info=0):
        self.session = session
        self.driving = driving
        self.closed = closed
        self.generation = generation
        self.change_count = change_count
        self.head = head
        self.load_supported = load_supported      # Phase SI-A6: the Bridge provided the load marker (LoadMagic valid); False = "no information"
        self.load_info = load_info if load_supported else 0

    @property
    def created_seen(self):
        """ScenarioCreated of THIS generation was received (needs load_supported)."""
        return self.load_supported and bool(self.load_info & LOAD_CREATED)

    @property
    def tick_seen(self):
        """The first Tick of THIS generation was received (needs load_supported)."""
        return self.load_supported and bool(self.load_info & LOAD_TICK_SEEN)

    @property
    def effective_session(self):
        return self.session and not self.closed

    @property
    def effective_driving(self):
        return self.effective_session and self.driving

    def __eq__(self, other):
        return isinstance(other, StateSnapshot) and all(getattr(self, k) == getattr(other, k) for k in self.__slots__)

    def __repr__(self):
        return "StateSnapshot(session=%s driving=%s closed=%s generation=%d changes=%d)" % (
            self.session, self.driving, self.closed, self.generation, self.change_count)


def parse_state(data, bve_pid, instance):
    """Validates one copy of the block. Returns (StateSnapshot, None) or (None, reason). The reason is a fixed word (never a value)."""
    if data is None or len(data) < STATE_SIZE:
        return None, "short"
    magic, version, size, pid, inst = _HEADER.unpack_from(data, 0)
    if magic != STATE_MAGIC:
        return None, "magic"
    if version != STATE_VERSION:
        return None, "version"
    if size != STATE_SIZE:
        return None, "size"
    if pid != bve_pid:
        return None, "pid"
    if inst != instance[:INSTANCE_CHARS].encode("ascii", "replace"):
        return None, "instance"
    head, flags, generation, count = _BODY.unpack_from(data, OFF_HEAD)
    (tail,) = _TAIL.unpack_from(data, OFF_TAIL)
    if head & 1 or head != tail:
        return None, "torn"
    if flags & ~_KNOWN_FLAGS or generation < 0:
        return None, "flags"
    load_info, load_magic = _LOAD.unpack_from(data, OFF_LOAD_INFO)
    load_supported = load_magic == LOAD_MAGIC       # any other magic (0 = an older Bridge / Caller) is "no information", never an error
    return StateSnapshot(bool(flags & FLAG_SESSION), bool(flags & FLAG_DRIVING), bool(flags & FLAG_CLOSED), generation, count, head,
                         load_supported, (load_info & _KNOWN_LOAD_BITS) if load_supported else 0), None


# ---------------------------------------------------------------------------------------------------------------------------------------
# Sources of the 64 bytes
# ---------------------------------------------------------------------------------------------------------------------------------------
_FILE_MAP_READ = 0x0004


class Win32StateSource(object):
    """Opens the named block read-only and copies its 64 bytes on demand (no wait, no lock, no allocation beyond the copy)."""

    def __init__(self):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k.OpenFileMappingW.restype = wintypes.HANDLE
        k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.UnmapViewOfFile.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        self._k = k
        self._handle = None
        self._view = None

    @property
    def is_open(self):
        return self._view is not None

    def open(self, name):
        """True when the block exists and is mapped. False when it does not exist (or cannot be opened)."""
        if self._view is not None:
            return True
        handle = self._k.OpenFileMappingW(_FILE_MAP_READ, False, name)
        if not handle:
            return False
        view = self._k.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, STATE_SIZE)
        if not view:
            self._k.CloseHandle(handle)
            return False
        self._handle = int(handle)
        self._view = int(view)
        return True

    def read(self):
        if self._view is None:
            return None
        return ctypes.string_at(self._view, STATE_SIZE)

    def close(self):
        view, handle = self._view, self._handle
        self._view = self._handle = None
        if view is not None:
            self._k.UnmapViewOfFile(view)
        if handle is not None:
            self._k.CloseHandle(handle)


_OPEN_TORN_ATTEMPTS = 5
_OPEN_TORN_PAUSE_S = 0.002


class StateReader(object):
    """The application's view of the block: open once, poll cheaply, converge to the current value, release at the end.

    The block is a REQUIRED part of the managed contract (the Caller creates it before it launches this process):
      * open() succeeds only when the block exists AND its first reading is valid (magic, version, size, BVE PID, instance, flags). Otherwise it
        returns False, `open_failure` names the reason and ONE `state-contract-failed phase=init` line is written. The owner of this reader
        then must not publish AppReady and must leave with the init-failure exit code.
      * once open, the first copy that is not valid (anything but a momentarily torn copy) means the block was LOST (`lost` = the reason, one
        `state-lost phase=run` line). The reader never recovers from it: the owner goes to its fail-safe and waits for the Stop request.
    poll() never blocks and never raises. A normal withdrawal by the Caller is not a loss: it arrives as a valid reading with the Closed flag."""

    def __init__(self, args, source, log, sleep=None):
        self._args = args
        self._source = source
        self._log = log
        self._sleep = sleep
        self._last = None
        self._attached = False
        self.reads = 0
        self.torn_retries = 0
        self.rejected_reads = 0
        self.open_failure = None
        self.lost = None

    @property
    def attached(self):
        return self._attached

    @property
    def last(self):
        return self._last

    @property
    def unavailable(self):
        """True when open() failed because the block could not be opened at all."""
        return self.open_failure in ("block-missing", "open-error")

    def _emit(self, event, **fields):
        text = "[MANAGED] event=%s inst=%s owner=%s pid=%d" % (event, self._args.instance, self._args.owner, self._args.bve_pid)
        for key in sorted(fields):
            text += " %s=%s" % (key, fields[key])
        try:
            self._log(text)
        except Exception:
            pass

    def open(self):
        """Attaches to the block and takes the first reading. True only for an existing block with a valid first reading.
        False = the managed contract is not met (reason in `open_failure`, one diagnostic line); nothing stays mapped."""
        try:
            ok = self._source.open(state_name(self._args.bve_pid, self._args.instance))
            reason = None if ok else "block-missing"
        except Exception:
            ok, reason = False, "open-error"
        if ok:
            snap, reason = self._first_valid_reading()
            if snap is not None:
                self._attached = True
                self._last = snap
                self._emit("state-attached", valid="yes")
                return True
        self.open_failure = reason
        try:
            self._source.close()
        except Exception:
            pass
        self._emit("state-contract-failed", phase="init", reason=reason, action="no-app-ready")
        return False

    def _first_valid_reading(self):
        """(snapshot, None) or (None, reason). Only a copy that stays torn for several short pauses is reported as torn."""
        reason = "torn"
        for attempt in range(_OPEN_TORN_ATTEMPTS):
            snap, reason = self._read_once()
            if snap is not None:
                return snap, None
            if reason != "torn":
                return None, reason
            (self._sleep or time.sleep)(_OPEN_TORN_PAUSE_S)
        return None, reason

    def _read_once(self):
        """One consistent copy: (snapshot, None) or (None, reason). A copy that two reads disagree on is `torn` after _READ_ATTEMPTS tries."""
        reason = "torn"
        for attempt in range(_READ_ATTEMPTS):
            try:
                first = self._source.read()
                second = self._source.read()
            except Exception as e:
                return None, "read-" + type(e).__name__
            if first is None or second is None:
                return None, "closed"
            if first != second:
                self.torn_retries += 1
                reason = "torn"
                continue
            snap, reason = parse_state(first, self._args.bve_pid, self._args.instance)
            if reason != "torn":
                return snap, reason
            self.torn_retries += 1
        return None, "torn"

    def poll(self):
        """Latest valid snapshot (or None). Safe to call every timer tick. After the block was lost it returns the last good snapshot and
        never reads again."""
        if not self._attached:
            return None
        if self.lost is not None:
            return self._last
        self.reads += 1
        snap, reason = self._read_once()
        if snap is not None:
            self._last = snap
        else:
            self.rejected_reads += 1
            if reason != "torn":            # a torn copy is normal for a moment; every other reason is a loss of the block
                self.lost = reason
                self._emit("state-lost", phase="run", reason=reason, action="hud-failsafe")
        return self._last

    def close(self):
        """Releases the mapping. Idempotent."""
        was = self._attached
        self._attached = False
        try:
            self._source.close()
        except Exception:
            pass
        if was:
            self._emit("state-detached", reads=self.reads, rejected=self.rejected_reads)


# ---------------------------------------------------------------------------------------------------------------------------------------
# HUD gate (pure)
# ---------------------------------------------------------------------------------------------------------------------------------------
class GateChange(object):
    """What changed in one HudGate.apply(): the new effective values and what differs from the previous ones."""
    __slots__ = ("session", "driving", "generation", "mode", "previous_mode", "session_changed", "driving_changed", "generation_changed",
                 "previous_generation", "skipped_changes", "closed")

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, None)


class HudGate(object):
    """Turns snapshots into the HUD mode and reports ONLY changes. An identical reading is counted as suppressed and returns None."""

    def __init__(self):
        self.session = False
        self.driving = False
        self.generation = 0
        self.mode = MODE_HIDDEN
        self.closed = False
        self._change_count = None
        self.applied = 0
        self.changes = 0
        self.suppressed = 0
        self.generation_changes = 0
        self.skipped_changes = 0

    def apply(self, snapshot):
        """snapshot=None means "no readable block": everything OFF. Returns a GateChange, or None when nothing changed."""
        if snapshot is None:
            session, driving, generation, closed = False, False, self.generation, self.closed
            count = self._change_count
        else:
            session, driving, generation, closed = snapshot.effective_session, snapshot.effective_driving, snapshot.generation, snapshot.closed
            count = snapshot.change_count
        self.applied += 1
        skipped = 0
        if count is not None and self._change_count is not None and count != self._change_count:
            skipped = max(0, ((count - self._change_count) & 0xFFFFFFFF) - 1)   # changes made between two reads that were never seen
        if (session, driving, generation, closed) == (self.session, self.driving, self.generation, self.closed):
            if count is not None:
                self._change_count = count
            self.skipped_changes += skipped
            self.suppressed += 1
            return None
        change = GateChange()
        change.previous_mode = self.mode
        change.previous_generation = self.generation
        change.session_changed = session != self.session
        change.driving_changed = driving != self.driving
        change.generation_changed = generation != self.generation
        change.skipped_changes = skipped
        change.closed = closed
        self.session, self.driving, self.generation, self.closed = session, driving, generation, closed
        self.mode = MODE_ACTIVE if driving else MODE_WAITING if session else MODE_HIDDEN
        if count is not None:
            self._change_count = count
        change.session, change.driving, change.generation, change.mode = session, driving, generation, self.mode
        self.changes += 1
        self.skipped_changes += skipped
        if change.generation_changed:
            self.generation_changes += 1
        return change
