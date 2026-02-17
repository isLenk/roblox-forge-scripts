"""
Auto-updater for LENK.TOOLS.
Checks GitHub Releases for a newer version on startup.
If found, downloads the new exe, replaces the current one, and restarts.
"""

import os
import sys
import json
import subprocess
import tempfile
import shutil
from urllib.request import urlopen, Request
from urllib.error import URLError

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
    time, which causes base_library.zip extraction conflicts.
    """
    current_exe = sys.executable
    old_path = current_exe + ".old"
    pid = os.getpid()

    # Write a temporary batch script that:
    # 1. Waits for our PID to disappear
    # 2. Cleans up the .old exe
    # 3. Launches the new exe
    # 4. Deletes itself
    bat_fd, bat_path = tempfile.mkstemp(suffix=".bat")
    with os.fdopen(bat_fd, "w") as f:
        f.write(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
if exist "{old_path}" del /f "{old_path}"
start "" "{current_exe}"
del "%~f0"
""")

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=0x00000008,  # DETACHED_PROCESS
    )
    sys.exit(0)


def run_update_check():
    """
    Main entry point. Call this before the bot starts.
    Checks for update, applies it, and restarts if needed.
    """
    print(f"[UPDATER] Current version: {VERSION}")
    result = check_for_update()
    if result is None:
        print("[UPDATER] Up to date.")
        return

    tag, url = result
    print(f"[UPDATER] New version available: {tag}")

    if apply_update(url):
        restart()
