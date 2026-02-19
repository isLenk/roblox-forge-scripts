"""Multi-monitor management and auto-detection."""

import ctypes
import ctypes.wintypes
import mss


def get_primary_monitor_info():
    """Get the primary monitor's rect and friendly name via Windows API."""
    CCHDEVICENAME = 32

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.DWORD),
            ("rcMonitor", ctypes.wintypes.RECT),
            ("rcWork", ctypes.wintypes.RECT),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szDevice", ctypes.c_wchar * CCHDEVICENAME),
        ]

    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("DeviceName", ctypes.c_wchar * 32),
            ("DeviceString", ctypes.c_wchar * 128),
            ("StateFlags", ctypes.wintypes.DWORD),
            ("DeviceID", ctypes.c_wchar * 128),
            ("DeviceKey", ctypes.c_wchar * 128),
        ]

    hmon = ctypes.windll.user32.MonitorFromPoint(
        ctypes.wintypes.POINT(0, 0), 1)
    info = MONITORINFOEX()
    info.cbSize = ctypes.sizeof(MONITORINFOEX)
    ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))

    rc = info.rcMonitor
    rect = {
        "left": rc.left, "top": rc.top,
        "width": rc.right - rc.left, "height": rc.bottom - rc.top,
    }

    try:
        dd = DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
        ctypes.windll.user32.EnumDisplayDevicesW(
            info.szDevice, 0, ctypes.byref(dd), 0)
        name = dd.DeviceString.strip() or info.szDevice.strip()
    except Exception:
        name = "Primary Monitor"

    return rect, name


class MonitorManager:
    """Manages multi-monitor selection and auto-detection."""

    def __init__(self):
        sct_tmp = mss.mss()
        self.all_monitors = sct_tmp.monitors[1:]  # skip combined virtual
        sct_tmp.close()
        self.monitor_idx = 0
        self._apply()

    def _apply(self):
        mon = self.all_monitors[self.monitor_idx]
        self.rect = mon
        self.resolution = f"{mon['width']}x{mon['height']}"
        print(f"[MONITOR] #{self.monitor_idx + 1} — {mon}")

    def cycle(self, delta):
        """Cycle monitor selection by delta (+1 or -1)."""
        self.monitor_idx = (
            (self.monitor_idx + delta) % len(self.all_monitors))
        self._apply()

    def auto_select(self):
        """Switch to the monitor Roblox is currently on.

        Returns True if the monitor changed.
        """
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("rcMonitor", ctypes.wintypes.RECT),
                    ("rcWork", ctypes.wintypes.RECT),
                    ("dwFlags", ctypes.wintypes.DWORD),
                ]

            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))

            rc = mi.rcMonitor
            r_left, r_top = rc.left, rc.top
            r_w = rc.right - rc.left
            r_h = rc.bottom - rc.top

            for i, mon in enumerate(self.all_monitors):
                if (mon['left'] == r_left and mon['top'] == r_top
                        and mon['width'] == r_w and mon['height'] == r_h):
                    if i != self.monitor_idx:
                        self.monitor_idx = i
                        self._apply()
                        return True
                    break
        except Exception:
            pass
        return False

    @property
    def count(self):
        return len(self.all_monitors)

    @property
    def current_index(self):
        return self.monitor_idx
