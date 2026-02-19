"""SendInput helpers for Roblox-compatible mouse and keyboard input."""

import ctypes
import ctypes.wintypes
import time

# Scan codes for SendInput keyboard events
SCAN_CODES = {
    '0': 0x0B, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09, '9': 0x0A,
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C,
}

SCAN_LSHIFT = 0x2A
SCAN_LCTRL = 0x1D
SCAN_LEFT_ARROW = 0x4B

WASD_VK = (0x57, 0x41, 0x53, 0x44)  # W, A, S, D


class InputManager:
    """Wraps Windows SendInput for mouse and keyboard events."""

    def __init__(self):
        self._setup_structs()

    def _setup_structs(self):
        """Prepare correct SendInput structs for 64-bit Windows."""
        ULONG_PTR = (ctypes.c_uint64
                     if ctypes.sizeof(ctypes.c_void_p) == 8
                     else ctypes.c_uint32)

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.wintypes.DWORD),
                ("wParamL", ctypes.wintypes.WORD),
                ("wParamH", ctypes.wintypes.WORD),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("union", INPUT_UNION),
            ]

        self._INPUT = INPUT
        self._MOUSEINPUT = MOUSEINPUT
        self._KEYBDINPUT = KEYBDINPUT

        # Virtual screen metrics for MOUSEEVENTF_ABSOLUTE
        self._virt_left = ctypes.windll.user32.GetSystemMetrics(76)
        self._virt_top = ctypes.windll.user32.GetSystemMetrics(77)
        self._virt_w = ctypes.windll.user32.GetSystemMetrics(78)
        self._virt_h = ctypes.windll.user32.GetSystemMetrics(79)

    def get_abs_coords(self):
        """Get current cursor position as ABSOLUTE coordinates for SendInput."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        abs_x = int((pt.x - self._virt_left) * 65535 / (self._virt_w - 1))
        abs_y = int((pt.y - self._virt_top) * 65535 / (self._virt_h - 1))
        return abs_x, abs_y, pt.x, pt.y

    def screen_to_abs(self, x, y):
        """Convert screen coordinates to absolute coordinates."""
        abs_x = int((x - self._virt_left) * 65535 / (self._virt_w - 1))
        abs_y = int((y - self._virt_top) * 65535 / (self._virt_h - 1))
        return abs_x, abs_y

    def send_mouse(self, flags, abs_x=None, abs_y=None):
        """Send a single mouse event via SendInput."""
        INPUT = self._INPUT
        MOUSEINPUT = self._MOUSEINPUT
        if abs_x is None:
            abs_x, abs_y, _, _ = self.get_abs_coords()
        inp = INPUT()
        inp.type = 0
        inp.union.mi = MOUSEINPUT(abs_x, abs_y, 0, flags, 0, 0)
        arr = (INPUT * 1)(inp)
        return ctypes.windll.user32.SendInput(
            1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def send_key(self, scan_code, key_up=False, extended=False):
        """Send a keyboard event via SendInput using scan codes."""
        INPUT = self._INPUT
        KEYBDINPUT = self._KEYBDINPUT
        flags = 0x0008  # KEYEVENTF_SCANCODE
        if extended:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= 0x0002  # KEYEVENTF_KEYUP
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(0, scan_code, flags, 0, 0)
        arr = (INPUT * 1)(inp)
        return ctypes.windll.user32.SendInput(
            1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def send_relative_move(self, dx, dy):
        """Send a relative mouse move via SendInput."""
        INPUT = self._INPUT
        MOUSEINPUT = self._MOUSEINPUT
        inp = INPUT()
        inp.type = 0
        inp.union.mi = MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)  # MOVE relative
        arr = (INPUT * 1)(inp)
        ctypes.windll.user32.SendInput(
            1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def move_to(self, target_x, target_y, steps=20, duration=0.05):
        """Smoothly drag cursor to target using relative SendInput moves."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

        total_dx = target_x - pt.x
        total_dy = target_y - pt.y

        if abs(total_dx) < 2 and abs(total_dy) < 2:
            return

        step_delay = duration / steps
        for i in range(steps):
            dx = int(total_dx * (i + 1) / steps) - int(total_dx * i / steps)
            dy = int(total_dy * (i + 1) / steps) - int(total_dy * i / steps)
            self.send_relative_move(dx, dy)
            time.sleep(step_delay)

    def click(self, x, y):
        """Click at current cursor position via SendInput ABSOLUTE."""
        abs_x, abs_y, px, py = self.get_abs_coords()
        self.send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
        time.sleep(0.03)
        sent = self.send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)
        print(f"[CLICK] at ({px},{py}) abs=({abs_x},{abs_y}) sent={sent}")
        return px, py

    def click_at_screen(self, x, y):
        """Smoothly drag the cursor to (x, y) then click."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        sx, sy = pt.x, pt.y

        steps = 20
        duration = 0.15
        for i in range(1, steps + 1):
            t = i / steps
            ix = sx + (x - sx) * t
            iy = sy + (y - sy) * t
            abs_x, abs_y = self.screen_to_abs(ix, iy)
            self.send_mouse(0x8000 | 0x4000 | 0x0001, abs_x, abs_y)
            time.sleep(duration / steps)

        abs_x, abs_y = self.screen_to_abs(x, y)
        self.send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
        time.sleep(0.03)
        self.send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)

    def press_game_key(self, key_name):
        """Press and release a key by its character name via SendInput."""
        scan = SCAN_CODES.get(key_name.lower())
        if scan is None:
            return
        self.send_key(scan, key_up=False)
        time.sleep(0.05)
        self.send_key(scan, key_up=True)

    def get_cursor_pos(self):
        """Get current cursor screen position."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
