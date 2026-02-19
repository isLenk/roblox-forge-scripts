"""Roblox foreground check and game ID detection from logs."""

import ctypes
import ctypes.wintypes
import os
import glob
import re
import json
import urllib.request


class RobloxFocus:
    """Checks if Roblox is focused and detects the active game."""

    def __init__(self):
        self._last_place_id = None
        self._last_game_name = None

    def is_focused(self):
        """Check if Roblox Player is the foreground window (by process exe)."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid))
            handle = ctypes.windll.kernel32.OpenProcess(
                0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            buf = ctypes.create_unicode_buffer(512)
            size = ctypes.wintypes.DWORD(512)
            ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size))
            ctypes.windll.kernel32.CloseHandle(handle)
            exe = buf.value.lower().rsplit('\\', 1)[-1]
            return exe == 'robloxplayerbeta.exe'
        except Exception:
            return False

    def detect_game(self):
        """Read the latest Roblox log to extract the current Place ID and game name.

        Returns (place_id, game_name) or (None, None).
        """
        try:
            log_dir = os.path.expandvars(r"%localappdata%\Roblox\logs")
            logs = glob.glob(os.path.join(log_dir, "*.log"))
            if not logs:
                return None, None
            latest = max(logs, key=os.path.getmtime)
            place_id = None
            with open(latest, "r", errors="ignore") as f:
                for line in f:
                    m = re.search(r"placeid:(\d{5,})", line, re.IGNORECASE)
                    if m:
                        place_id = m.group(1)
            if not place_id:
                return None, None
            # Resolve place ID -> universe ID -> game name
            url1 = (f"https://apis.roblox.com/universes/v1/"
                    f"places/{place_id}/universe")
            req1 = urllib.request.Request(
                url1, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req1, timeout=3) as resp:
                universe_id = json.loads(
                    resp.read().decode()).get("universeId")
            if not universe_id:
                return place_id, None
            url2 = (f"https://games.roblox.com/v1/games"
                    f"?universeIds={universe_id}")
            req2 = urllib.request.Request(
                url2, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req2, timeout=3) as resp:
                data = json.loads(resp.read().decode()).get("data", [])
            if data:
                return place_id, data[0].get("name")
            return place_id, None
        except Exception:
            return (self._last_place_id, self._last_game_name)

    def update_cache(self, place_id, game_name):
        """Cache the last known place ID and game name."""
        if place_id:
            self._last_place_id = place_id
        if game_name:
            self._last_game_name = game_name

    @property
    def last_place_id(self):
        return self._last_place_id

    @property
    def last_game_name(self):
        return self._last_game_name
