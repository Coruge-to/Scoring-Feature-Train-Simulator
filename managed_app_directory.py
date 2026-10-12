"""PID-scoped AppDirectory reader for TS Scoring.

Mirrors AppDirectoryPublisher.cs byte for byte. This module is independent of Qt,
scoring, UDP and managed-mode lifecycle policy. It only validates and reads the
80-byte memory block named by one BVE process id.
"""
import ctypes
import re
import struct
from ctypes import wintypes

DIRECTORY_MAGIC = 0x44415354  # "TSAD" as little-endian uint32
DIRECTORY_VERSION = 1
DIRECTORY_SIZE = 80
INSTANCE_CHARS = 32

OFF_MAGIC = 0
OFF_VERSION = 4
OFF_SIZE = 8
OFF_BVE_PID = 12
OFF_HEAD = 16
OFF_FLAGS = 20
OFF_INSTANCE = 24
OFF_APP_PID = 56
OFF_CHANGE_COUNT = 60
OFF_RESERVED0 = 64
OFF_RESERVED1 = 68
OFF_RESERVED2 = 72
OFF_TAIL = 76

FLAG_INSTANCE_PUBLISHED = 1 << 0
FLAG_PROCESS_STARTED = 1 << 1
FLAG_READY_ACCEPTED = 1 << 2
FLAG_WITHDRAWING = 1 << 3
FLAG_CLOSED = 1 << 4
KNOWN_FLAGS = (
    FLAG_INSTANCE_PUBLISHED
    | FLAG_PROCESS_STARTED
    | FLAG_READY_ACCEPTED
    | FLAG_WITHDRAWING
    | FLAG_CLOSED
)

_HEADER = struct.Struct("<IIIIII32sIIIIII")
_INSTANCE_RE = re.compile(r"[0-9a-f]{32}")
_READ_ATTEMPTS = 3
_FILE_MAP_READ = 0x0004


def directory_name(bve_pid):
    if not isinstance(bve_pid, int) or isinstance(bve_pid, bool) or bve_pid <= 0 or bve_pid > 0xFFFFFFFF:
        raise ValueError("invalid-bve-pid")
    return "Local\\TSScoringPlugin.v1.%d.AppDirectory" % bve_pid


class DirectorySnapshot(object):
    __slots__ = ("bve_pid", "instance", "app_pid", "flags", "change_count", "head")

    def __init__(self, bve_pid, instance, app_pid, flags, change_count, head):
        self.bve_pid = bve_pid
        self.instance = instance
        self.app_pid = app_pid
        self.flags = flags
        self.change_count = change_count
        self.head = head

    @property
    def instance_published(self):
        return bool(self.flags & FLAG_INSTANCE_PUBLISHED)

    @property
    def process_started(self):
        return bool(self.flags & FLAG_PROCESS_STARTED)

    @property
    def ready_accepted(self):
        return bool(self.flags & FLAG_READY_ACCEPTED)

    @property
    def withdrawing(self):
        return bool(self.flags & FLAG_WITHDRAWING)

    @property
    def closed(self):
        return bool(self.flags & FLAG_CLOSED)

    @property
    def usable(self):
        """A live, Ready-accepted application identity, not being withdrawn."""
        return self.ready_accepted and not self.withdrawing and not self.closed

    def __eq__(self, other):
        return isinstance(other, DirectorySnapshot) and all(
            getattr(self, name) == getattr(other, name) for name in self.__slots__
        )

    def __repr__(self):
        return "DirectorySnapshot(bve_pid=%d instance=%r app_pid=%d flags=0x%X changes=%d)" % (
            self.bve_pid, self.instance, self.app_pid, self.flags, self.change_count
        )


def parse_directory(data, expected_bve_pid):
    """Returns (DirectorySnapshot, None) or (None, fixed_reason)."""
    if data is None or len(data) < DIRECTORY_SIZE:
        return None, "short"
    try:
        fields = _HEADER.unpack_from(data, 0)
    except struct.error:
        return None, "short"
    (magic, version, size, bve_pid, head, flags, raw_instance, app_pid,
     change_count, reserved0, reserved1, reserved2, tail) = fields
    if magic != DIRECTORY_MAGIC:
        return None, "magic"
    if version != DIRECTORY_VERSION:
        return None, "version"
    if size != DIRECTORY_SIZE:
        return None, "size"
    if bve_pid != expected_bve_pid:
        return None, "pid"
    if head & 1 or head != tail:
        return None, "torn"
    if flags & ~KNOWN_FLAGS:
        return None, "flags"
    if reserved0 or reserved1 or reserved2:
        return None, "reserved"

    closed = bool(flags & FLAG_CLOSED)
    if closed:
        if flags != FLAG_CLOSED or raw_instance != (b"\0" * INSTANCE_CHARS) or app_pid != 0:
            return None, "closed"
        return DirectorySnapshot(bve_pid, "", 0, flags, change_count, head), None

    if not (flags & FLAG_INSTANCE_PUBLISHED):
        return None, "flags"
    if (flags & FLAG_READY_ACCEPTED) and not (flags & FLAG_PROCESS_STARTED):
        return None, "flags"
    if flags & FLAG_PROCESS_STARTED:
        if app_pid <= 0:
            return None, "app-pid"
    elif app_pid != 0:
        return None, "app-pid"
    try:
        instance = raw_instance.decode("ascii")
    except UnicodeDecodeError:
        return None, "instance"
    if not _INSTANCE_RE.fullmatch(instance):
        return None, "instance"
    return DirectorySnapshot(bve_pid, instance, app_pid, flags, change_count, head), None


class Win32DirectorySource(object):
    """Read-only mapping source for one AppDirectory object."""
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
        if self._view is not None:
            return True
        handle = self._k.OpenFileMappingW(_FILE_MAP_READ, False, name)
        if not handle:
            return False
        view = self._k.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, DIRECTORY_SIZE)
        if not view:
            self._k.CloseHandle(handle)
            return False
        self._handle = int(handle)
        self._view = int(view)
        return True

    def read(self):
        return None if self._view is None else ctypes.string_at(self._view, DIRECTORY_SIZE)

    def close(self):
        view, handle = self._view, self._handle
        self._view = self._handle = None
        if view is not None:
            self._k.UnmapViewOfFile(view)
        if handle is not None:
            self._k.CloseHandle(handle)


class DirectoryReader(object):
    """Cheap polling reader. It never raises from open(), poll(), or close()."""
    def __init__(self, bve_pid, source=None):
        directory_name(bve_pid)
        self.bve_pid = bve_pid
        self.source = source if source is not None else Win32DirectorySource()
        self.attached = False
        self.last = None
        self.open_failure = None
        self.last_rejection = None
        self.reads = 0
        self.torn_retries = 0

    def open(self):
        if self.attached:
            return True
        self.open_failure = None
        try:
            if not self.source.open(directory_name(self.bve_pid)):
                self.open_failure = "block-missing"
                return False
            snap, reason = self._read_once()
            if snap is None:
                self.open_failure = reason
                self.source.close()
                return False
            self.attached = True
            self.last = snap
            return True
        except Exception:
            self.open_failure = "open-error"
            try:
                self.source.close()
            except Exception:
                pass
            return False

    def _read_once(self):
        for _attempt in range(_READ_ATTEMPTS):
            try:
                first = self.source.read()
                second = self.source.read()
            except Exception as exc:
                return None, "read-" + type(exc).__name__
            if first is None or second is None:
                return None, "closed"
            if first != second:
                self.torn_retries += 1
                continue
            snap, reason = parse_directory(first, self.bve_pid)
            if reason != "torn":
                return snap, reason
            self.torn_retries += 1
        return None, "torn"

    def poll(self):
        if not self.attached:
            return None
        self.reads += 1
        snap, reason = self._read_once()
        if snap is not None:
            self.last = snap
            self.last_rejection = None
            return snap
        self.last_rejection = reason
        return None

    def close(self):
        self.attached = False
        try:
            self.source.close()
        except Exception:
            pass
