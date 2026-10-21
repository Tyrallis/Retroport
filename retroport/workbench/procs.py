"""Closing and starting the game client and the worldserver around a creature install (Windows).

The client is closed like its window's close button. The worldserver gets a Ctrl+C in its console,
which AzerothCore handles as a shutdown: it saves the players and exits. Either one is forced only
when it has not gone after a while.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

CLIENT_EXES = ("WowClient64.exe", "Wow64.exe", "Wow.exe")
SERVER_EXE = "worldserver.exe"

_NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
_NEW_CONSOLE = 0x00000010        # CREATE_NEW_CONSOLE
_BREAKAWAY = 0x01000000          # CREATE_BREAKAWAY_FROM_JOB

# Attach to the target's console and press Ctrl+C there; this helper ignores it itself.
_CTRL_C = ("import ctypes, sys\n"
           "k = ctypes.windll.kernel32\n"
           "k.FreeConsole()\n"
           "if not k.AttachConsole(int(sys.argv[1])): sys.exit(1)\n"
           "k.SetConsoleCtrlHandler(None, True)\n"
           "sys.exit(0 if k.GenerateConsoleCtrlEvent(0, 0) else 2)\n")


def processes(names: tuple[str, ...]) -> list[dict]:
    """Running processes with one of these image names: pid, name, exe, cmd."""
    if os.name != "nt" or not names:
        return []
    flt = " or ".join(f"Name='{n}'" for n in names)
    ps = (f"Get-CimInstance Win32_Process -Filter \"{flt}\" | "
          "Select-Object ProcessId, Name, ExecutablePath, CommandLine | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True,
                             text=True, timeout=30, creationflags=_NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    if not out:
        return []
    try:
        rows = json.loads(out)
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [{"pid": int(r["ProcessId"]), "name": r.get("Name") or "", "exe": r.get("ExecutablePath") or "",
             "cmd": r.get("CommandLine") or ""} for r in rows]


def _wait_gone(pid: int, seconds: float) -> bool:
    """True once the process has exited (or never was), waiting up to ``seconds``."""
    import ctypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x00100000 | 0x1000, False, pid)     # SYNCHRONIZE | QUERY_LIMITED_INFORMATION
    if not h:
        return True
    try:
        return k.WaitForSingleObject(ctypes.c_void_p(h), int(seconds * 1000)) == 0   # WAIT_OBJECT_0
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def alive(pid: int) -> bool:
    return not _wait_gone(pid, 0)


def _force(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=_NO_WINDOW)


def close_window_app(pid: int, wait: float = 20) -> str:
    """Close a windowed program as its close button does; force it after ``wait`` seconds."""
    subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=_NO_WINDOW)
    if _wait_gone(pid, wait):
        return "closed"
    _force(pid)
    _wait_gone(pid, 10)
    return "forced"


def python_exe() -> str:
    """A python.exe for the Ctrl+C helper (the app may run under pythonw)."""
    exe = sys.executable or "python"
    d, base = os.path.split(exe)
    if base.lower() == "pythonw.exe" and os.path.isfile(os.path.join(d, "python.exe")):
        return os.path.join(d, "python.exe")
    return exe


def stop_console_app(pid: int, wait: float = 90) -> str:
    """Press Ctrl+C in a console program; force it after ``wait`` seconds."""
    try:
        subprocess.run([python_exe(), "-I", "-c", _CTRL_C, str(pid)], capture_output=True, timeout=30,
                       creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass
    if _wait_gone(pid, wait):
        return "stopped"
    _force(pid)
    _wait_gone(pid, 10)
    return "forced"


# Start a console program in a new console with Ctrl+C turned on: a child inherits "ignore Ctrl+C"
# from whoever starts it, and the next stop_console_app needs it. Prints the child's pid.
_LAUNCH = ("import ctypes, json, subprocess, sys\n"
           "ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)\n"
           "a = json.loads(sys.argv[1])\n"
           "p = subprocess.Popen(a['cmd'], cwd=a['cwd'], creationflags=0x10 | a['extra'], close_fds=True)\n"
           "print(p.pid)\n")


def start(cmd: str | list, cwd: str, console: bool) -> int:
    """Start a program on its own, so it outlives the Workbench. ``console``: in a new console window
    (not a new process group either: Windows turns Ctrl+C off there)."""
    for extra in (_BREAKAWAY, 0):
        try:
            if console:
                arg = json.dumps({"cmd": cmd, "cwd": cwd, "extra": extra})
                out = subprocess.run([python_exe(), "-I", "-c", _LAUNCH, arg], capture_output=True, text=True,
                                     timeout=30, creationflags=_NO_WINDOW | extra)
                if out.returncode:
                    raise OSError(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "launch failed")
                return int(out.stdout.strip() or 0)
            p = subprocess.Popen(cmd, cwd=cwd, creationflags=extra, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return p.pid
        except OSError:
            if not extra:
                raise
    return 0


def find_worldserver(world_conf: str) -> str:
    """worldserver.exe near a worldserver.conf (beside it, one or two folders up, or in bin)."""
    if not world_conf:
        return ""
    d = os.path.dirname(os.path.abspath(world_conf))
    for base in (d, os.path.dirname(d), os.path.dirname(os.path.dirname(d))):
        for sub in ("", "bin"):
            p = os.path.join(base, sub, SERVER_EXE)
            if os.path.isfile(p):
                return p
    return ""


def find_client(client_dir: str) -> str:
    for name in CLIENT_EXES:
        p = os.path.join(client_dir or "", name)
        if os.path.isfile(p):
            return p
    return ""


class Restart:
    """Closes the client and the worldserver, and later starts them again: the ones that ran, as they
    were started, else the ones Settings and worldserver.conf point at."""

    def __init__(self, client_dir: str, world_conf: str, say=lambda m: None):
        self.client_dir, self.world_conf, self.say = client_dir, world_conf, say
        self.client: dict | None = None
        self.server: dict | None = None

    def _ours(self, p: dict, folder: str) -> bool:
        return not folder or not p["exe"] or os.path.normcase(os.path.dirname(p["exe"])) == os.path.normcase(
            os.path.abspath(folder))

    def stop(self) -> None:
        for p in processes(CLIENT_EXES):
            if self._ours(p, self.client_dir):
                self.client = self.client or p
                self.say(f"closing the client ({p['name']}, pid {p['pid']})")
                self.say(f"client: {close_window_app(p['pid'])}")
        server_dir = os.path.dirname(find_worldserver(self.world_conf))
        for p in processes((SERVER_EXE,)):
            if self._ours(p, server_dir) or not server_dir:
                self.server = self.server or p
                self.say(f"stopping the worldserver (pid {p['pid']}): it saves the players first")
                self.say(f"worldserver: {stop_console_app(p['pid'])}")

    def start_all(self) -> list[str]:
        started = []
        exe = (self.server or {}).get("exe") or find_worldserver(self.world_conf)
        if exe:
            start((self.server or {}).get("cmd") or [exe], os.path.dirname(exe), console=True)
            started.append("worldserver")
            self.say(f"started {exe}")
        else:
            self.say("worldserver.exe not found next to worldserver.conf: start it yourself")
        exe = (self.client or {}).get("exe") or find_client(self.client_dir)
        if exe:
            start((self.client or {}).get("cmd") or [exe], os.path.dirname(exe), console=False)
            started.append("client")
            self.say(f"started {exe}")
        else:
            self.say("no client .exe found in the client folder: start it yourself")
        return started
