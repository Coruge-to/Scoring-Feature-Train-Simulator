"""PID-D3 test helper: play the Current sender's side for a REAL managed application (or a fake one) in a Python test.

Resolves the application's Telemetry Receiver Directory through the named mapping (read only: it never creates or changes a mapping) and sends
Envelope v1 datagrams to the port the application published. Standard library only; Windows only."""
import ctypes
import os
import socket
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import dataplane_contract as contract

_FILE_MAP_READ = 0x0004


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenFileMappingW.restype = wintypes.HANDLE
    k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k.MapViewOfFile.restype = ctypes.c_void_p
    k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    k.UnmapViewOfFile.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


def read_directory(bve_pid, instance):
    """The decoded Telemetry Directory snapshot (dict of dataplane_contract.decode_telemetry_directory) or None (absent, torn or invalid)."""
    k = _kernel32()
    handle = k.OpenFileMappingW(_FILE_MAP_READ, False, contract.telemetry_name(bve_pid, instance))
    if not handle:
        return None
    try:
        view = k.MapViewOfFile(handle, _FILE_MAP_READ, 0, 0, contract.DIRECTORY_SIZE)
        if not view:
            return None
        try:
            for _ in range(3):
                data = ctypes.string_at(view, contract.DIRECTORY_SIZE)
                try:
                    return contract.decode_telemetry_directory(data)
                except ValueError:
                    continue
            return None
        finally:
            k.UnmapViewOfFile(view)
    finally:
        k.CloseHandle(handle)


def usable_endpoint(bve_pid, instance):
    """The directory when it is PUBLISHED + READY (not withdrawing / closed) and advertises ENVELOPE_V1, else None."""
    snap = read_directory(bve_pid, instance)
    if snap is None:
        return None
    state = snap["state"]
    if (state & (contract.PUBLISHED | contract.READY)) != (contract.PUBLISHED | contract.READY) or state & (contract.WITHDRAWING | contract.CLOSED):
        return None
    if not snap["capabilities"] & contract.CAP_ENVELOPE_V1:
        return None
    return snap


def wait_endpoint(bve_pid, instance, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = usable_endpoint(bve_pid, instance)
        if snap is not None:
            return snap
        time.sleep(0.02)
    return None


def envelope_for(snap, message_type, payload, bve_pid=None, sender_pid=None, token=None, request_id=None, generation=None, instance=None):
    """An Envelope v1 datagram for the endpoint `snap` (keyword arguments override single fields for negative tests)."""
    pid = snap["bve_pid"] if bve_pid is None else bve_pid
    return contract.encode_envelope(message_type, pid, pid if sender_pid is None else sender_pid, snap["generation"] if generation is None else generation,
                                    snap["app_instance"] if instance is None else instance, snap["token"] if token is None else token,
                                    bytes(16) if request_id is None else request_id, payload if isinstance(payload, bytes) else payload.encode("utf-8"))


def send(port, datagram):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(datagram, ("127.0.0.1", port))
    finally:
        s.close()


def udp_port_is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()
