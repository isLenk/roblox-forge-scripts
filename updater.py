"""
Auto-updater for LENK.TOOLS.
Checks GitHub Releases for a newer version on startup.
If found, downloads the new exe, replaces the current one, and restarts.
Shows a small GUI overlay with spinner and status text during the process.
"""

import os
import sys
import json
import subprocess
import tempfile
import shutil
import math
import time
import tkinter as tk
from pathlib import Path
from threading import Thread
from urllib.request import urlopen, Request
from urllib.error import URLError

_ASSETS = (Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS')
           else Path(__file__).resolve().parent) / 'assets'

from version import VERSION

GITHUB_REPO = "isLenk/roblox-forge-scripts"
RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXE_NAME = "LENK.TOOLS.exe"


def _parse_version(v):
    """Turn '1.2.3' into (1, 2, 3) for comparison."""
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))


def check_for_update():
    """
    Check GitHub for a newer release.
    Returns (tag, download_url) if an update is available, else None.
    """
    try:
        req = Request(RELEASE_URL, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError):
        return None

    tag = data.get("tag_name", "")
    if not tag:
        return None

    try:
        remote_ver = _parse_version(tag)
        local_ver = _parse_version(VERSION)
    except (ValueError, AttributeError):
        return None

    if remote_ver <= local_ver:
        return None

    # Find the exe asset
    for asset in data.get("assets", []):
        if asset["name"].lower() == EXE_NAME.lower():
            return tag, asset["browser_download_url"]

    return None


def apply_update(download_url):
    """
    Download the new exe and replace the current one.
    Returns True if the update was applied and the app should restart.
    """
    # Only works when running as a frozen exe (PyInstaller)
    if not getattr(sys, "frozen", False):
        print("[UPDATER] Not running as exe, skipping update.")
        return False

    current_exe = sys.executable
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".exe", dir=os.path.dirname(current_exe))

    try:
        print(f"[UPDATER] Downloading update...")
        req = Request(download_url)
        with urlopen(req, timeout=30) as resp:
            with os.fdopen(tmp_fd, "wb") as f:
                shutil.copyfileobj(resp, f)

        # Rename current exe to .old, move new one in, then restart
        old_path = current_exe + ".old"
        if os.path.exists(old_path):
            os.remove(old_path)

        os.rename(current_exe, old_path)
        shutil.move(tmp_path, current_exe)
        print("[UPDATER] Update applied. Restarting...")
        return True

    except Exception as e:
        print(f"[UPDATER] Update failed: {e}")
        # Clean up temp file if it still exists
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def restart():
    """Restart via a helper batch script that waits for this process to exit first.

    This prevents two PyInstaller --onefile processes from running at the same
    time, which causes base_library.zip extraction conflicts and Python DLL
    load failures.
    """
    current_exe = sys.executable
    old_path = current_exe + ".old"
    pid = os.getpid()
    mei_dir = getattr(sys, '_MEIPASS', '')

    bat_fd, bat_path = tempfile.mkstemp(suffix=".bat")
    with os.fdopen(bat_fd, "w") as f:
        script = f"""@echo off
setlocal enabledelayedexpansion
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
timeout /t 2 /nobreak >nul
"""
        if mei_dir:
            script += f"""rem Wait for old PyInstaller extraction dir to be fully released
set "_tries=0"
:cleanmei
if not exist "{mei_dir}" goto doneClean
rmdir /s /q "{mei_dir}" 2>nul
set /a "_tries+=1"
if !_tries! GEQ 15 goto doneClean
timeout /t 1 /nobreak >nul
goto cleanmei
:doneClean
"""
        script += f"""if exist "{old_path}" del /f "{old_path}"
start "" "{current_exe}"
del "%~f0"
"""
        f.write(script)

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    # Use os._exit to terminate immediately without Python/PyInstaller cleanup.
    # The batch script handles _MEI cleanup instead, which is more reliable
    # than racing between PyInstaller's atexit handler and the new process.
    os._exit(0)


# ------------------------------------------------------------------ GUI

class _UpdateWindow:
    """Small splash-style overlay that shows update progress with a spinner."""

    BG = '#0d1117'
    BG2 = '#161b22'
    BORDER = '#21262d'
    GREEN = '#50fa7b'
    DIM = '#484f58'
    TEXT = '#c9d1d9'

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)

        W, H = 320, 140
        # Center on screen
        sx = self.root.winfo_screenwidth()
        sy = self.root.winfo_screenheight()
        x = (sx - W) // 2
        y = (sy - H) // 2
        self.root.geometry(f"{W}x{H}+{x}+{y}")

        # Logo / title
        _logo_file = _ASSETS / 'logo.png'
        self._logo_photo = None
        if _logo_file.exists():
            try:
                from PIL import Image, ImageEnhance, ImageTk
                _limg = Image.open(str(_logo_file))
                lh = 18
                lw = round(_limg.width * lh / _limg.height)
                _limg = _limg.resize((lw, lh), Image.LANCZOS)
                _limg = ImageEnhance.Brightness(_limg).enhance(0.45)
                self._logo_photo = ImageTk.PhotoImage(_limg)
                tk.Label(self.root, image=self._logo_photo,
                         bg=self.BG, bd=0).pack(pady=(14, 0))
            except Exception:
                self._logo_photo = None
        if self._logo_photo is None:
            tk.Label(self.root, text="LENK.TOOLS",
                     font=('Consolas', 10, 'bold'), fg=self.DIM,
                     bg=self.BG).pack(pady=(14, 0))
        tk.Label(self.root, text=f"v{VERSION}",
                 font=('Consolas', 8), fg=self.DIM,
                 bg=self.BG).pack(pady=(2, 0))

        # Spinner canvas
        self._spinner_size = 36
        self._spinner = tk.Canvas(self.root, width=self._spinner_size,
                                  height=self._spinner_size, bg=self.BG,
                                  highlightthickness=0)
        self._spinner.pack(pady=(10, 0))
        self._angle = 0
        self._spinner_arcs = []
        self._draw_spinner()

        # Status label
        self._status = tk.Label(self.root, text="Checking for updates...",
                                font=('Consolas', 10), fg=self.TEXT,
                                bg=self.BG)
        self._status.pack(pady=(10, 0))

        # Sub-status (smaller, dimmer)
        self._sub = tk.Label(self.root, text="",
                             font=('Consolas', 8), fg=self.DIM,
                             bg=self.BG)
        self._sub.pack(pady=(2, 0))

        self._animate()

    def _draw_spinner(self):
        """Draw a circular arc spinner."""
        s = self._spinner_size
        pad = 4
        self._spinner.delete('all')
        # Background track
        self._spinner.create_oval(pad, pad, s - pad, s - pad,
                                  outline=self.BORDER, width=3)
        # Spinning arc
        self._spinner.create_arc(pad, pad, s - pad, s - pad,
                                 start=self._angle, extent=90,
                                 outline=self.GREEN, width=3,
                                 style='arc')

    def _animate(self):
        """Rotate the spinner."""
        self._angle = (self._angle - 12) % 360
        self._draw_spinner()
        self.root.after(33, self._animate)  # ~30fps

    def set_status(self, text, sub=""):
        self._status.config(text=text)
        self._sub.config(text=sub)
        self.root.update_idletasks()

    def set_done(self, text):
        """Show completion state — green check replaces spinner."""
        self._spinner.delete('all')
        self._spinner.create_text(self._spinner_size // 2,
                                  self._spinner_size // 2,
                                  text='\u2714', font=('Segoe UI', 18),
                                  fill=self.GREEN)
        self._status.config(text=text, fg=self.GREEN)
        self._sub.config(text="")
        self.root.update_idletasks()

    def set_error(self, text):
        self._spinner.delete('all')
        self._spinner.create_text(self._spinner_size // 2,
                                  self._spinner_size // 2,
                                  text='\u2717', font=('Segoe UI', 18),
                                  fill='#ff5555')
        self._status.config(text=text, fg='#ff5555')
        self._sub.config(text="")
        self.root.update_idletasks()

    def close(self):
        self.root.destroy()


def run_update_check():
    """
    Main entry point. Call this before the bot starts.
    Shows a GUI splash while checking/applying updates.
    """
    print(f"[UPDATER] Current version: {VERSION}")

    win = _UpdateWindow()
    result_holder = [None]  # (tag, url) or None
    error_holder = [None]

    def _check():
        try:
            result_holder[0] = check_for_update()
        except Exception as e:
            error_holder[0] = e

    # Run check in background thread
    t = Thread(target=_check, daemon=True)
    t.start()

    # Pump the GUI while the check runs
    while t.is_alive():
        win.root.update()
        time.sleep(0.016)

    if error_holder[0] or result_holder[0] is None:
        if error_holder[0]:
            win.set_error("Update check failed")
            print(f"[UPDATER] Error: {error_holder[0]}")
            win.root.update()
            time.sleep(1.5)
        else:
            win.set_done("Up to date")
            print("[UPDATER] Up to date.")
            win.root.update()
            time.sleep(0.6)
        win.close()
        return

    tag, url = result_holder[0]
    win.set_status(f"Updating to {tag}...", "Downloading new version")
    print(f"[UPDATER] New version available: {tag}")
    win.root.update()

    apply_holder = [False]
    apply_error = [None]

    def _apply():
        try:
            apply_holder[0] = apply_update(url)
        except Exception as e:
            apply_error[0] = e

    t2 = Thread(target=_apply, daemon=True)
    t2.start()

    while t2.is_alive():
        win.root.update()
        time.sleep(0.016)

    if apply_error[0] or not apply_holder[0]:
        msg = f"Update failed: {apply_error[0]}" if apply_error[0] else "Update skipped"
        win.set_error(msg)
        print(f"[UPDATER] {msg}")
        win.root.update()
        time.sleep(2)
        win.close()
        return

    win.set_done(f"Updated to {tag}")
    win.set_status(f"Updated to {tag}", "Restarting...")
    win.root.update()
    time.sleep(1)
    win.close()
    restart()
