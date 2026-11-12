"""Helper PROCESS for tests/test_initial_defaults_ownership.py (not a test: the file name does not start with test_).
It stands in for BVE with REAL top-level windows (ctypes, no Qt): `bve` = a main window plus a settings window OWNED by the main window (like BVE's modal settings dialog);
`app` = one plain top-level window of another application (like Chrome). It prints ONE JSON line with the HWNDs and its pid, then reads commands on stdin:
  destroy-settings   destroy the settings window (the owner of the initial-defaults window disappears)
  new-settings       create a new settings window owned by the main window and print its HWND
  minimize <name>    minimize a window of this process (name = main | settings)
  destroy-main       destroy the settings window AND the main window (the process stays alive: like BVE writing a crash report during its shutdown)
  new-main           create a new main window (a revived / re-created main window) and print its HWND
  exit               leave
Window creation, destruction and the message loop all run on the main thread of this process (a window must be destroyed by the thread that created it)."""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
u32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.DefWindowProcW.restype = LRESULT
u32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
u32.CreateWindowExW.restype = wt.HWND
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
u32.DestroyWindow.argtypes = [wt.HWND]
u32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
u32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
u32.PostQuitMessage.argtypes = [ctypes.c_int]
u32.RegisterClassW.argtypes = [ctypes.c_void_p]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


WM_APP = 0x8000
CMD_DESTROY_SETTINGS, CMD_NEW_SETTINGS, CMD_MINIMIZE_MAIN, CMD_MINIMIZE_SETTINGS, CMD_QUIT = WM_APP + 1, WM_APP + 2, WM_APP + 3, WM_APP + 4, WM_APP + 5
CMD_DESTROY_MAIN, CMD_NEW_MAIN = WM_APP + 6, WM_APP + 7
WS_OVERLAPPEDWINDOW, WS_VISIBLE, WS_POPUP, WS_CAPTION, WS_SYSMENU = 0x00CF0000, 0x10000000, 0x80000000, 0x00C00000, 0x00080000
state = {"main": 0, "settings": 0, "ctl": 0}
mode = sys.argv[1]


def wndproc(hwnd, msg, wparam, lparam):
    if msg == CMD_DESTROY_SETTINGS:
        if state["settings"]:
            u32.DestroyWindow(state["settings"])
            state["settings"] = 0
        return 0
    if msg == CMD_NEW_SETTINGS:
        state["settings"] = make_settings()
        print(json.dumps({"settings": state["settings"]}), flush=True)
        return 0
    if msg == CMD_MINIMIZE_MAIN:
        u32.ShowWindow(state["main"], 6)
        return 0
    if msg == CMD_MINIMIZE_SETTINGS:
        if state["settings"]:
            u32.ShowWindow(state["settings"], 6)
        return 0
    if msg == CMD_DESTROY_MAIN:
        if state["settings"]:
            u32.DestroyWindow(state["settings"])
            state["settings"] = 0
        if state["main"]:
            u32.DestroyWindow(state["main"])
            state["main"] = 0
        return 0
    if msg == CMD_NEW_MAIN:
        state["main"] = make_main("FAKE-BVE-MAIN", 90, 90)
        print(json.dumps({"main": state["main"]}), flush=True)
        return 0
    if msg == CMD_QUIT:
        u32.PostQuitMessage(0)
        return 0
    return u32.DefWindowProcW(hwnd, msg, wparam, lparam)


_proc = WNDPROC(wndproc)
cls = WNDCLASSW()
cls.lpfnWndProc = _proc
cls.hInstance = k32.GetModuleHandleW(None)
cls.lpszClassName = "TSSFakeBveWindow"
cls.hbrBackground = 6
u32.RegisterClassW(ctypes.byref(cls))


def make_main(title, x, y):
    return u32.CreateWindowExW(0, "TSSFakeBveWindow", title, WS_OVERLAPPEDWINDOW | WS_VISIBLE, x, y, 520, 380, None, None, cls.hInstance, None)


def make_settings():
    return u32.CreateWindowExW(0, "TSSFakeBveWindow", "FAKE-BVE-SETTINGS", WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE, 160, 160, 420, 300, state["main"], None, cls.hInstance, None)


state["ctl"] = u32.CreateWindowExW(0, "TSSFakeBveWindow", "ctl", 0, 0, 0, 0, 0, wt.HWND(-3), None, cls.hInstance, None)         # a message-only window: receives the commands, is never enumerated as a top-level window
if mode == "bve":
    state["main"] = make_main("FAKE-BVE-MAIN", 80, 80)
    state["settings"] = make_settings()
    info = {"pid": k32.GetCurrentProcessId(), "main": state["main"], "settings": state["settings"]}
else:
    state["main"] = make_main("FAKE-OTHER-APP", 240, 200)
    info = {"pid": k32.GetCurrentProcessId(), "main": state["main"], "settings": 0}
print(json.dumps(info), flush=True)


def reader():
    for line in sys.stdin:
        word = line.strip().split(" ")
        if word[0] == "destroy-settings":
            u32.PostMessageW(state["ctl"], CMD_DESTROY_SETTINGS, 0, 0)
        elif word[0] == "new-settings":
            u32.PostMessageW(state["ctl"], CMD_NEW_SETTINGS, 0, 0)
        elif word[0] == "minimize":
            u32.PostMessageW(state["ctl"], CMD_MINIMIZE_SETTINGS if len(word) > 1 and word[1] == "settings" else CMD_MINIMIZE_MAIN, 0, 0)
        elif word[0] == "destroy-main":
            u32.PostMessageW(state["ctl"], CMD_DESTROY_MAIN, 0, 0)
        elif word[0] == "new-main":
            u32.PostMessageW(state["ctl"], CMD_NEW_MAIN, 0, 0)
        elif word[0] == "exit":
            u32.PostMessageW(state["ctl"], CMD_QUIT, 0, 0)
            return
    u32.PostMessageW(state["ctl"], CMD_QUIT, 0, 0)            # stdin closed = the test is gone


threading.Thread(target=reader, daemon=True).start()
msg = wt.MSG()
while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
    u32.DispatchMessageW(ctypes.byref(msg))
