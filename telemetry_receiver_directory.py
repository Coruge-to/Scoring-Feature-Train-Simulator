"""PID-D2: Python-owned PID-scoped Telemetry receiver directory.

The Caller-owned AppDirectory is never modified here.  This publisher owns one
128-byte mapping for the lifetime of one managed Python process and exposes only
its loopback UDP endpoint.  App Lock remains the outer lifetime guard.
"""
import ctypes
import secrets
import struct
from ctypes import wintypes

import dataplane_contract as contract

_PAGE_READWRITE = 0x04
_FILE_MAP_WRITE = 0x0002
_ERROR_ALREADY_EXISTS = 183
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_HEAD_OFFSET = 16
_TAIL_OFFSET = 124


class TelemetryDirectoryPublisher(object):
    def __init__(self, bve_pid, instance, app_pid, port, kernel32=None):
        contract.telemetry_name(bve_pid, instance)
        if not isinstance(app_pid, int) or isinstance(app_pid, bool) or app_pid <= 0:
            raise ValueError("app-pid")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("port")
        self.bve_pid = bve_pid
        self.instance = instance
        self.app_pid = app_pid
        self.port = port
        self.generation = secrets.randbits(32) or 1
        self.token = secrets.token_bytes(16)
        self.change_count = 0
        self.sequence = 0
        self.state = 0
        self._handle = None
        self._view = None
        self._closed = False
        self._k = kernel32 or self._load_kernel32()
        self._open_new_mapping()
        self._publish(contract.PUBLISHED)

    @staticmethod
    def _load_kernel32():
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileMappingW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR]
        k.CreateFileMappingW.restype = wintypes.HANDLE
        k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
        k.MapViewOfFile.restype = ctypes.c_void_p
        k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k.UnmapViewOfFile.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        return k

    def _open_new_mapping(self):
        name = contract.telemetry_name(self.bve_pid, self.instance)
        handle = self._k.CreateFileMappingW(_INVALID_HANDLE_VALUE, None, _PAGE_READWRITE, 0, contract.DIRECTORY_SIZE, name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == _ERROR_ALREADY_EXISTS:
            self._k.CloseHandle(handle)
            raise RuntimeError("telemetry-directory-already-exists")
        view = self._k.MapViewOfFile(handle, _FILE_MAP_WRITE, 0, 0, contract.DIRECTORY_SIZE)
        if not view:
            error = ctypes.get_last_error()
            self._k.CloseHandle(handle)
            raise ctypes.WinError(error)
        self._handle = handle
        self._view = view

    def _next_sequences(self):
        odd = (self.sequence + 1) & 0xFFFFFFFF
        if not (odd & 1):
            odd = (odd + 1) & 0xFFFFFFFF
        even = (odd + 1) & 0xFFFFFFFF
        return odd, even

    def _publish(self, state):
        if self._closed or self._view is None:
            raise RuntimeError("telemetry-directory-closed")
        odd, even = self._next_sequences()
        self.change_count = (self.change_count + 1) & 0xFFFFFFFF
        if state == contract.CLOSED:
            data = contract.encode_telemetry_directory(self.bve_pid, even, state, "", 0, 0, 0, bytes(16), self.change_count, 0)
        else:
            data = contract.encode_telemetry_directory(self.bve_pid, even, state, self.instance, self.app_pid, self.port,
                                                       self.generation, self.token, self.change_count, 0)
        ctypes.memmove(self._view, data[:_HEAD_OFFSET], _HEAD_OFFSET)
        ctypes.memmove(self._view + _HEAD_OFFSET, struct.pack("<I", odd), 4)
        ctypes.memmove(self._view + _HEAD_OFFSET + 4, data[_HEAD_OFFSET + 4:_TAIL_OFFSET + 4], contract.DIRECTORY_SIZE - (_HEAD_OFFSET + 4))
        ctypes.memmove(self._view + _HEAD_OFFSET, struct.pack("<I", even), 4)
        self.sequence = even
        self.state = state

    def publish_ready(self):
        if self.state == contract.PUBLISHED:
            self._publish(contract.PUBLISHED | contract.READY)

    def publish_withdrawing(self):
        if self._closed or self.state in (contract.CLOSED, contract.PUBLISHED | contract.READY | contract.WITHDRAWING):
            return
        if self.state & contract.PUBLISHED:
            self._publish(self.state | contract.WITHDRAWING)

    def close(self):
        if self._closed:
            return
        view, handle = self._view, self._handle
        try:
            if view is not None:
                self.publish_withdrawing()
                self._publish(contract.CLOSED)
        finally:
            self._closed = True
            self._view = None
            self._handle = None
            if view is not None:
                self._k.UnmapViewOfFile(view)
            if handle is not None:
                self._k.CloseHandle(handle)
