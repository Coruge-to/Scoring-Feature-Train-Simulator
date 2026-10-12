"""Win32 AppDirectory publisher used only by managed-process tests.

The fixture mirrors the Caller AppDirectory lifecycle without importing product
policy into the tests. A test owns one PID-scoped block and explicitly publishes
InstancePublished, ProcessStarted, ReadyAccepted, Withdrawing and Closed.
"""
import ctypes
import struct
from ctypes import wintypes

import managed_app_directory as directory

_PAGE_READWRITE = 0x04
_FILE_MAP_WRITE = 0x0002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_HEADER = struct.Struct("<IIIIII32sIIIIII")


class AppDirectoryFixture(object):
    def __init__(self, bve_pid, instance):
        directory.directory_name(bve_pid)
        if not isinstance(instance, str) or len(instance) != directory.INSTANCE_CHARS:
            raise ValueError("invalid-instance")
        try:
            raw = instance.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("invalid-instance")
        if any(c not in b"0123456789abcdef" for c in raw):
            raise ValueError("invalid-instance")
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileMappingW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        k.CreateFileMappingW.restype = wintypes.HANDLE
        k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.UnmapViewOfFile.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        self._k = k
        self.bve_pid = bve_pid
        self.instance = instance
        self.app_pid = 0
        self.flags = 0
        self.change_count = 0
        self.sequence = 0
        self._view = None
        self._handle = k.CreateFileMappingW(_INVALID_HANDLE_VALUE, None, _PAGE_READWRITE, 0, directory.DIRECTORY_SIZE, directory.directory_name(bve_pid))
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self._view = k.MapViewOfFile(self._handle, _FILE_MAP_WRITE, 0, 0, directory.DIRECTORY_SIZE)
        if not self._view:
            err = ctypes.get_last_error()
            k.CloseHandle(self._handle)
            self._handle = None
            raise ctypes.WinError(err)
        self.publish_instance()

    def _publish(self, flags, app_pid, instance=None):
        if self._view is None:
            raise RuntimeError("fixture-closed")
        identity = self.instance if instance is None else instance
        raw = identity.encode("ascii") if identity else (b"\0" * directory.INSTANCE_CHARS)
        odd = (self.sequence + 1) & 0xFFFFFFFF
        if not (odd & 1):
            odd = (odd + 1) & 0xFFFFFFFF
        even = (odd + 1) & 0xFFFFFFFF
        self.change_count = (self.change_count + 1) & 0xFFFFFFFF
        data = _HEADER.pack(directory.DIRECTORY_MAGIC, directory.DIRECTORY_VERSION, directory.DIRECTORY_SIZE,
                            self.bve_pid, even, flags, raw, app_pid, self.change_count, 0, 0, 0, even)
        ctypes.memmove(self._view, data, len(data))
        self.sequence = even
        self.flags = flags
        self.app_pid = app_pid

    def publish_instance(self):
        self._publish(directory.FLAG_INSTANCE_PUBLISHED, 0)

    def publish_process_started(self, app_pid):
        if not isinstance(app_pid, int) or isinstance(app_pid, bool) or app_pid <= 0:
            raise ValueError("invalid-app-pid")
        self._publish(directory.FLAG_INSTANCE_PUBLISHED | directory.FLAG_PROCESS_STARTED, app_pid)

    def publish_ready_accepted(self):
        if self.app_pid <= 0 or not (self.flags & directory.FLAG_PROCESS_STARTED):
            raise RuntimeError("process-not-started")
        self._publish(directory.FLAG_INSTANCE_PUBLISHED | directory.FLAG_PROCESS_STARTED | directory.FLAG_READY_ACCEPTED, self.app_pid)

    def publish_withdrawing(self):
        if self.flags == directory.FLAG_CLOSED:
            return
        self._publish(self.flags | directory.FLAG_WITHDRAWING, self.app_pid)

    def publish_closed(self):
        if self._view is None:
            return
        self._publish(directory.FLAG_CLOSED, 0, instance="")

    def close(self):
        view, handle = self._view, self._handle
        if view is None and handle is None:
            return
        try:
            if view is not None:
                self.publish_withdrawing()
                self.publish_closed()
        finally:
            self._view = None
            self._handle = None
            if view is not None:
                self._k.UnmapViewOfFile(view)
            if handle is not None:
                self._k.CloseHandle(handle)
