"""Phase E2 - managed mode of TS Scoring (the Python side of the future Caller <-> application contract).

This module is deliberately independent of Qt, of the scoring logic and of main.py: it only knows command line arguments, named Windows
kernel objects and a small lifecycle state machine, so every rule below can be tested without a GUI.

Managed mode is entered ONLY by an explicit `--managed` argument. Without it main.py behaves exactly as before.

    python main.py --managed --owner <token> --bve-pid <decimal> --instance <16..32 lowercase hex>

Named objects (Local\\ = per logon session). <PID> = BVE process id, <INST> = instance id, new for EVERY launch and never reused:

    Local\\TSScoringPlugin.v1.<PID>.App.<INST>.Lock   mutex, created by this process. A second process with the same names exits with code 3.
    Local\\TSScoringPlugin.v1.<PID>.App.<INST>.Stop   manual-reset event, created by the OWNER before the launch. Opened (never created) here.
                                                    SET = "terminate this application process" and nothing else.
    Local\\TSScoringPlugin.v1.<PID>.App.<INST>.Ready  manual-reset event, created by this process. SET = AppReady.

AppReady means only: this managed process is alive, opened its required contract objects, can receive the stop request and finished its
initialisation. It does not mean ScenarioReady, DrivingActive, a visible HUD or a running score. It is published last and withdrawn first.

Exit codes (the diagnostic line `[MANAGED] event=exit` carries the reason as well):
    0 stop request received / event loop ended without error     1 unhandled exception while running
    2 UDP port could not be bound                                 3 the same instance is already running
    4 required initialisation failed (event/mutex/Qt)             5 invalid managed-mode arguments

Owner process watch (only for `--owner caller`): the BVE process named by --bve-pid is the owner of this application. Its process handle is
opened right at start (SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION) and waited on next to the Stop event, so the owner vanishing without a Stop
request (crash, kill, power-off of the sim) ends this process by itself instead of leaving it holding UDP 54321 for the next BVE session:

    owner not found / not the process that started us / handle cannot be opened   -> exit 4, reason parent-process-missing / -unwatchable, Ready never set
    owner ended while running (or while starting)                                  -> exit 0, reason parent-process-exited, same orderly shut-down as Stop
Opening the handle first (never searching the pid again later) is what makes a recycled pid harmless: the handle names the process object, not a number.
"""
import ctypes
import os
import re
import sys
import threading
import time
from ctypes import wintypes

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_BIND_FAILED = 2
EXIT_DUPLICATE_INSTANCE = 3
EXIT_INIT_FAILED = 4
EXIT_ARGS_INVALID = 5

MANAGED_FLAG = "--managed"
PARENT_WATCH_OWNER = "caller"
NAME_PREFIX = "Local\\TSScoringPlugin.v1."
_PID_RE = re.compile(r"[1-9][0-9]{0,9}")
_INSTANCE_RE = re.compile(r"[0-9a-f]{16,32}")
_OWNER_RE = re.compile(r"[a-z][a-z0-9-]{0,15}")
_MAX_PID = 0xFFFFFFFF


class ManagedArgs(object):
    """Validated managed-mode arguments. Values are restricted to characters that cannot alter an object name."""

    def __init__(self, bve_pid, instance, owner):
        self.bve_pid = bve_pid
        self.instance = instance
        self.owner = owner

    def _name(self, kind):
        return "%s%d.App.%s.%s" % (NAME_PREFIX, self.bve_pid, self.instance, kind)

    @property
    def watches_parent(self):
        """Only the Caller-owned launch ties this process to the BVE process it names. Any other owner token (manual tests, future owners)
        keeps the plain Stop-event contract; normal (non-managed) mode never gets here at all."""
        return self.owner == PARENT_WATCH_OWNER

    @property
    def lock_name(self):
        return self._name("Lock")

    @property
    def stop_name(self):
        return self._name("Stop")

    @property
    def ready_name(self):
        return self._name("Ready")


def is_managed_requested(args):
    """True only for the explicit flag. Everything else (including stray managed-only options) stays normal mode."""
    return MANAGED_FLAG in args


def parse_managed_args(args):
    """args = sys.argv[1:]. Returns (ManagedArgs, None) or (None, reason). The reason never echoes the offending value."""
    values = {}
    seen_flag = False
    i = 0
    options = {"--bve-pid": "bve_pid", "--instance": "instance", "--owner": "owner"}
    while i < len(args):
        token = args[i]
        if token == MANAGED_FLAG:
            if seen_flag:
                return None, "duplicate-managed-flag"
            seen_flag = True
            i += 1
            continue
        key = None
        value = None
        if token in options:
            key = options[token]
            if i + 1 >= len(args):
                return None, "missing-value:" + token
            value = args[i + 1]
            i += 2
        elif token.startswith("--") and "=" in token and token.split("=", 1)[0] in options:
            name, value = token.split("=", 1)
            key = options[name]
            i += 1
        else:
            return None, "unknown-argument"
        if key in values:
            return None, "duplicate-option:--" + key.replace("_", "-")
        values[key] = value
    if not seen_flag:
        return None, "managed-flag-missing"
    for need in ("--bve-pid", "--instance", "--owner"):
        if options[need] not in values:
            return None, "missing-option:" + need
    if not _PID_RE.fullmatch(values["bve_pid"]) or int(values["bve_pid"]) > _MAX_PID:
        return None, "invalid-bve-pid"
    if not _INSTANCE_RE.fullmatch(values["instance"]):
        return None, "invalid-instance"
    if not _OWNER_RE.fullmatch(values["owner"]):
        return None, "invalid-owner"
    return ManagedArgs(int(values["bve_pid"]), values["instance"], values["owner"]), None


# ---------------------------------------------------------------------------------------------------------------------------------------
# Windows named objects
# ---------------------------------------------------------------------------------------------------------------------------------------
_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87  # OpenProcess for a pid that does not exist
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF


class Win32Sync(object):
    """The real implementation. Handles are plain integers. Every call is a thin kernel32 wrapper."""

    def __init__(self):
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k.OpenEventW.restype = wintypes.HANDLE
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.SetEvent.restype = wintypes.BOOL
        k.ResetEvent.argtypes = [wintypes.HANDLE]
        k.ResetEvent.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD]
        k.WaitForMultipleObjects.restype = wintypes.DWORD
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.GetCurrentProcess.argtypes = []
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k.GetProcessTimes.restype = wintypes.BOOL
        self._k = k

    def open_process(self, pid):
        """Opens the process for waiting + creation-time query. Returns (handle, 0) or (None, GetLastError())."""
        handle = self._k.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        err = ctypes.get_last_error()
        if not handle:
            return None, err
        return int(handle), 0

    def process_created(self, handle):
        """Creation time of the process behind `handle` as a 64-bit FILETIME integer, None when it cannot be read. handle=None means this process."""
        target = self._k.GetCurrentProcess() if handle is None else handle  # the current-process pseudo handle needs no CloseHandle
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self._k.GetProcessTimes(target, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return (created.dwHighDateTime << 32) | created.dwLowDateTime

    def create_mutex(self, name):
        """Returns (handle, existed). Raises OSError when the object cannot be created."""
        handle = self._k.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(err)
        return int(handle), err == _ERROR_ALREADY_EXISTS

    def create_event(self, name):
        """Manual-reset, initially non-signaled. name=None makes an unnamed (private) event. Returns (handle, existed)."""
        handle = self._k.CreateEventW(None, True, False, name)
        err = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(err)
        return int(handle), err == _ERROR_ALREADY_EXISTS

    def open_event(self, name):
        """Opens an existing event for waiting only. Returns the handle or None when it does not exist (or cannot be opened)."""
        handle = self._k.OpenEventW(_SYNCHRONIZE, False, name)
        return int(handle) if handle else None

    def set_event(self, handle):
        self._k.SetEvent(handle)

    def reset_event(self, handle):
        self._k.ResetEvent(handle)

    def is_set(self, handle):
        return self._k.WaitForSingleObject(handle, 0) == _WAIT_OBJECT_0

    def close(self, handle):
        self._k.CloseHandle(handle)

    def wait_any(self, handles, timeout_ms=None):
        """Index of the first signaled handle, -1 on timeout. Raises OSError on failure. timeout_ms=None waits without a limit."""
        arr = (wintypes.HANDLE * len(handles))(*handles)
        result = self._k.WaitForMultipleObjects(len(handles), arr, False, _INFINITE if timeout_ms is None else timeout_ms)
        if result == _WAIT_TIMEOUT:
            return -1
        if result == _WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(result) - _WAIT_OBJECT_0


# ---------------------------------------------------------------------------------------------------------------------------------------
# Lifecycle state machine (no Qt)
# ---------------------------------------------------------------------------------------------------------------------------------------
STATE_NEW = "new"
STATE_INITIALIZING = "initializing"
STATE_READY = "ready"
STATE_STOPPING = "stopping"
STATE_STOPPED = "stopped"

_WATCHER_JOIN_SECONDS = 2.0
REASON_PARENT_EXITED = "parent-process-exited"  # exit code 0, told apart from the Stop request's "stop-requested"


class ManagedLifecycle(object):
    """Owns the three named objects of one managed instance and decides the exit reason / exit code.

    Order: acquire() -> start_stop_watch() -> publish_ready() -> (run) -> shutdown().
    Ready is published only after the Stop watcher runs, is withdrawn before anything else on a stop / failure, and is never left set.
    The first terminal reason wins; later stop requests or failures never change the exit code.
    """

    def __init__(self, args, sync, log):
        self._args = args
        self._sync = sync
        self._log = log
        self._lock = threading.RLock()
        self._state = STATE_NEW
        self._lock_handle = None
        self._stop_handle = None
        self._ready_handle = None
        self._cancel_handle = None
        self._parent_handle = None
        self._watcher = None
        self._ready_set = False
        self._ready_ever_published = False
        self._stop_requested = False
        self._reason = None
        self._exit_code = None
        self._on_stop = None
        self._finished = False
        self._started = time.monotonic()

    # -- observation --------------------------------------------------------------------------------------------------------------------
    @property
    def state(self):
        return self._state

    @property
    def ready_published(self):
        """True while Ready is currently set by this instance."""
        return self._ready_set

    @property
    def stop_requested(self):
        return self._stop_requested

    @property
    def exit_reason(self):
        return self._reason

    @property
    def exit_code(self):
        """The code shutdown() will return/has returned (0 when nothing failed)."""
        return EXIT_OK if self._exit_code is None else self._exit_code

    def _emit(self, event, **fields):
        text = "[MANAGED] event=%s inst=%s owner=%s pid=%d" % (event, self._args.instance, self._args.owner, self._args.bve_pid)
        for key in sorted(fields):
            text += " %s=%s" % (key, fields[key])
        try:
            self._log(text)
        except Exception:
            pass

    # -- start-up -----------------------------------------------------------------------------------------------------------------------
    def acquire(self):
        """Takes the Lock, opens Stop and creates Ready (non-signaled). Returns None on success or the exit code (3 or 4).
        On a failure nothing stays open and Ready was never signaled. A duplicate never touches the first instance's Ready."""
        with self._lock:
            if self._state != STATE_NEW:
                raise RuntimeError("acquire called twice")
            self._state = STATE_INITIALIZING
            self._emit("state", state=self._state)
            try:
                handle, existed = self._sync.create_mutex(self._args.lock_name)
            except Exception as e:
                return self._acquire_failed(EXIT_INIT_FAILED, "lock-create-failed", e)
            if existed:
                self._sync.close(handle)
                return self._acquire_failed(EXIT_DUPLICATE_INSTANCE, "duplicate-instance", None)
            self._lock_handle = handle
            stop = self._sync.open_event(self._args.stop_name)
            if stop is None:
                return self._acquire_failed(EXIT_INIT_FAILED, "stop-event-missing", None)
            self._stop_handle = stop
            if self._args.watches_parent:
                code = self._open_parent()
                if code is not None:
                    return code
            try:
                ready, existed = self._sync.create_event(self._args.ready_name)
            except Exception as e:
                return self._acquire_failed(EXIT_INIT_FAILED, "ready-create-failed", e)
            self._ready_handle = ready
            if existed:
                # a leftover Ready of an earlier run of this very instance (someone still holds its handle): it must not count as ours
                self._sync.reset_event(ready)
                self._emit("ready-stale-cleared")
            try:
                self._cancel_handle, _ = self._sync.create_event(None)
            except Exception as e:
                return self._acquire_failed(EXIT_INIT_FAILED, "cancel-create-failed", e)
            self._emit("acquired")
            return None

    def _open_parent(self):
        """Takes the owner's process handle BEFORE anything is published. Returns None, or the exit code (4) after cleaning up.
        The handle - not the pid - is what is watched from here on, so a pid recycled later can never be mistaken for the owner. A pid recycled
        BEFORE this point is caught by the creation times: the owner must be older than this process (it started us)."""
        pid = self._args.bve_pid
        try:
            handle, err = self._sync.open_process(pid)
        except Exception as e:
            return self._acquire_failed(EXIT_INIT_FAILED, "parent-process-unwatchable", e)
        if handle is None:
            reason = "parent-process-missing" if err == _ERROR_INVALID_PARAMETER else "parent-process-unwatchable:win32-%d" % err
            return self._acquire_failed(EXIT_INIT_FAILED, reason, None)
        self._parent_handle = handle
        try:
            parent_created = self._sync.process_created(handle)
            own_created = self._sync.process_created(None)
            already_gone = self._sync.is_set(handle)
        except Exception as e:
            return self._acquire_failed(EXIT_INIT_FAILED, "parent-process-unwatchable", e)
        if parent_created is None or own_created is None:
            return self._acquire_failed(EXIT_INIT_FAILED, "parent-process-unwatchable:times", None)
        if parent_created > own_created:
            return self._acquire_failed(EXIT_INIT_FAILED, "parent-process-missing:pid-reused", None)
        if already_gone:
            return self._acquire_failed(EXIT_INIT_FAILED, "parent-process-missing:already-exited", None)
        self._emit("parent-watch-armed")
        return None

    def _acquire_failed(self, code, reason, exc):
        self._record_terminal(code, reason + (":" + type(exc).__name__ if exc is not None else ""))
        self._release_handles()
        self._state = STATE_STOPPED
        self._finish_log()
        return code

    def start_stop_watch(self, on_stop):
        """Starts the watcher thread. on_stop() runs on that thread, once, after Ready was withdrawn; it must only hand over to the UI thread."""
        with self._lock:
            if self._state != STATE_INITIALIZING or self._watcher is not None:
                raise RuntimeError("start_stop_watch in wrong state")
            self._on_stop = on_stop
            preset = self._sync.is_set(self._stop_handle)
            if preset:
                # recorded before the watcher runs, so that Ready can never be published for a stop that is already pending
                self._emit("stop-already-set")
                self.request_stop("stop-requested")
            elif self._parent_handle is not None and self._sync.is_set(self._parent_handle):
                # the owner ended between acquire() and now: same rule as a pending Stop, Ready is never published
                self._emit("parent-process-exited", when="before-ready")
                self.request_stop(REASON_PARENT_EXITED)
            thread = threading.Thread(target=self._watch, name="managed-stop-watch", daemon=True)
            self._watcher = thread
            thread.start()

    def _watch(self):
        # Stop comes first in the list: if both are signaled at once WaitForMultipleObjects reports the Stop (lowest index), so the ordinary
        # shut-down keeps its ordinary reason. Either way request_stop() accepts the first reason only and the hand-over happens once.
        handles = [self._stop_handle, self._cancel_handle]
        if self._parent_handle is not None:
            handles.append(self._parent_handle)
        try:
            index = self._sync.wait_any(handles, None)
        except Exception as e:
            self.fail(EXIT_RUNTIME_ERROR, "stop-watch-failed:" + type(e).__name__)
            self._notify()
            return
        if index == 0:
            self.request_stop("stop-requested")
            self._notify()
        elif index == 2:
            self._emit("parent-process-exited", when="running")
            self.request_stop(REASON_PARENT_EXITED)
            self._notify()

    def _notify(self):
        callback = self._on_stop
        if callback is None:
            return
        try:
            callback()
        except Exception as e:
            self._emit("notify-failed", error=type(e).__name__)

    def publish_ready(self):
        """Sets Ready. False when a stop/failure was already recorded or the state does not allow it (then Ready stays unset)."""
        with self._lock:
            if self._state != STATE_INITIALIZING or self._stop_requested or self._exit_code is not None:
                return False
            if self._watcher is None:
                raise RuntimeError("publish_ready before start_stop_watch")
            self._sync.set_event(self._ready_handle)
            self._ready_set = True
            self._ready_ever_published = True
            self._state = STATE_READY
            self._emit("ready-published", state=self._state)
            return True

    # -- stop / failure -----------------------------------------------------------------------------------------------------------------
    def request_stop(self, reason="stop-requested"):
        """The one and only meaning of a stop request: terminate this process. Idempotent; True for the first call that was accepted."""
        with self._lock:
            if self._stop_requested:
                return False
            self._stop_requested = True
            self._withdraw_ready_locked()
            if self._exit_code is None:
                self._record_terminal(EXIT_OK, reason)
            if self._state in (STATE_INITIALIZING, STATE_READY):
                self._state = STATE_STOPPING
            self._emit("stop-received", reason=reason)
            return True

    def fail(self, code, reason):
        """Records a failure (first terminal reason wins) and withdraws Ready immediately."""
        with self._lock:
            self._withdraw_ready_locked()
            first = self._exit_code is None
            if first:
                self._record_terminal(code, reason)
                self._emit("failure", code=code, reason=reason)
            if self._state in (STATE_INITIALIZING, STATE_READY):
                self._state = STATE_STOPPING
            return first

    def _record_terminal(self, code, reason):
        if self._exit_code is None:
            self._exit_code = code
            self._reason = reason

    def _withdraw_ready_locked(self):
        if self._ready_set and self._ready_handle is not None:
            self._sync.reset_event(self._ready_handle)
            self._ready_set = False
            self._emit("ready-withdrawn")

    # -- shut-down ----------------------------------------------------------------------------------------------------------------------
    def shutdown(self, cleanup=None):
        """Idempotent. Ready is withdrawn first, the watcher is ended, `cleanup` (UI / workers) runs, then the objects are released and the
        final diagnostic line is written. Returns the exit code."""
        with self._lock:
            if self._finished:
                return self.exit_code
            self._withdraw_ready_locked()
            if self._exit_code is None:
                self._record_terminal(EXIT_OK, "event-loop-ended")
            if self._state != STATE_STOPPED:
                self._state = STATE_STOPPING
        self._end_watcher()
        if cleanup is not None:
            try:
                cleanup()
            except Exception as e:
                self._emit("cleanup-failed", error=type(e).__name__)
        with self._lock:
            self._release_handles()
            self._state = STATE_STOPPED
            self._finish_log()
            return self.exit_code

    def _end_watcher(self):
        watcher = self._watcher
        if watcher is None:
            return
        if self._cancel_handle is not None:
            self._sync.set_event(self._cancel_handle)
        if watcher is not threading.current_thread():
            watcher.join(_WATCHER_JOIN_SECONDS)
        if watcher.is_alive():
            # never close a handle another thread may still be waiting on
            self._emit("watcher-join-timeout")
            self._stop_handle = None
            self._cancel_handle = None
            self._parent_handle = None
        else:
            self._emit("watcher-ended")

    def _release_handles(self):
        for attr in ("_ready_handle", "_stop_handle", "_cancel_handle", "_parent_handle", "_lock_handle"):  # the Lock is released last
            handle = getattr(self, attr)
            if handle is not None:
                try:
                    self._sync.close(handle)
                except Exception:
                    pass
                setattr(self, attr, None)

    def _finish_log(self):
        if self._finished:
            return
        self._finished = True
        self._emit("exit", code=self.exit_code, reason=self._reason, ready_published=str(self._ready_ever_published).lower(),
                   uptime_ms=int((time.monotonic() - self._started) * 1000))
        settle_std_streams()


def describe_exception(exc):
    """Type name and the innermost frame's file name + line number only: no message, no path, no user name."""
    tb = exc.__traceback__
    where = ""
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is not None:
        where = "@%s:%d" % (tb.tb_frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1], tb.tb_lineno)
    return type(exc).__name__ + where


def _replace_broken_stream(name):
    try:
        setattr(sys, name, open(os.devnull, "w"))
    except Exception:
        pass


def settle_std_streams():
    """When the owner vanished, the pipes it read our stdout / stderr through are broken. Python's own flush of them at interpreter shutdown would
    then fail and turn the exit code into 120 although the orderly shut-down succeeded: swap a broken stream for the null device first."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.flush()
        except Exception:
            _replace_broken_stream(name)


def stderr_log(text):
    """Diagnostic sink of managed mode: one flushed line per state change on stderr (absent under pythonw -> ignored)."""
    stream = sys.stderr
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except Exception:
        _replace_broken_stream("stderr")  # the reader is gone: later lines are dropped, and the shutdown flush cannot fail
