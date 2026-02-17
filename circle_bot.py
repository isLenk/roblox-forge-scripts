"""
Circle Timing Bot
=================
Detects OSU-style shrinking circles and clicks when they turn green.
Also auto-plays the yellow-bar slit minigame.

Controls:
  P       - Toggle circle detection mode on/off
  I       - Toggle cursor jiggle on/off
  O       - Toggle bar game auto-player on/off
  U       - Toggle auto-phase (Smelting -> Casting -> Welding, advances on GO screen)
  F5      - Toggle autoclicker (clicks every 0.1s)
  F6      - Toggle hold left arrow key
  CapsLock - Toggle sprint (holds LeftShift while WASD pressed)
  Close the GUI window to exit

All modes only activate when Roblox is focused.

Dependencies:
  pip install opencv-python numpy mss keyboard
"""

import cv2
import numpy as np
import mss
import ctypes
import ctypes.wintypes
import keyboard
import tkinter as tk
from threading import Thread
import time
import random
import json
import os
import glob
import re
from version import VERSION
try:
    import mouse
except ImportError:
    mouse = None
from tkinter import ttk, simpledialog, messagebox
from wiki import WikiWindow, WikiSearchOverlay, load_wiki_data, save_wiki_data

# Fix DPI scaling on Windows so screen coords match pixel coords
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Scan codes for SendInput keyboard events
_SCAN_CODES = {
    '0': 0x0B, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09, '9': 0x0A,
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C,
}


def _get_primary_monitor_info():
    """Get the primary monitor's rect and friendly name via Windows API."""
    import ctypes.wintypes
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

    # Get the primary monitor handle (the one containing 0,0)
    hmon = ctypes.windll.user32.MonitorFromPoint(
        ctypes.wintypes.POINT(0, 0), 1  # MONITOR_DEFAULTTOPRIMARY
    )
    info = MONITORINFOEX()
    info.cbSize = ctypes.sizeof(MONITORINFOEX)
    ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info))

    rc = info.rcMonitor
    rect = {
        "left": rc.left,
        "top": rc.top,
        "width": rc.right - rc.left,
        "height": rc.bottom - rc.top,
    }

    # Get friendly name
    try:
        dd = DISPLAY_DEVICE()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICE)
        ctypes.windll.user32.EnumDisplayDevicesW(info.szDevice, 0, ctypes.byref(dd), 0)
        name = dd.DeviceString.strip() or info.szDevice.strip()
    except Exception:
        name = "Primary Monitor"

    return rect, name


class LenkTools:
    def __init__(self):
        self.active = False
        self.running = True

        # Get all monitors from mss (handles DPI correctly)
        sct_tmp = mss.mss()
        self.all_monitors = sct_tmp.monitors[1:]  # skip index 0 (combined virtual screen)
        sct_tmp.close()
        self.monitor_idx = 0  # start on first monitor
        self._apply_monitor()

        # --- Tunable Parameters ---
        self.scan_scale = 0.5               # downscale factor for speed
        self.min_area = 40                  # min contour area (at downscaled res)

        # Green/lime ring HSV range (the "click now" color)
        self.green_lo = np.array([28, 55, 65])
        self.green_hi = np.array([75, 255, 255])

        # White ring HSV range (bright white outer ring only)
        self.white_lo = np.array([0, 0, 210])
        self.white_hi = np.array([180, 40, 255])

        # Morphology kernel (reused)
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

        # SendInput structures for Roblox-compatible clicks
        self._setup_sendinput()

        # Jiggle state — moves between 20% from top and 20% from bottom of screen
        self.jiggling = False
        screen_h = self.monitor_rect['height']
        self.jiggle_top = int(screen_h * 0.20)       # 20% from top
        self.jiggle_bottom = int(screen_h * 0.80)     # 20% from bottom
        self.jiggle_period = 0.1                       # seconds per direction

        # Bar game state
        self.bar_game = False
        self.bar_shaping = False

        # Debug state
        self.debug = False

        # Autoclicker state
        self.autoclicker = False

        # Hold-left-arrow state
        self.holding_left = False

        # Sprint state (hold LeftShift while WASD pressed)
        self.sprint_enabled = False

        # Hotkeys enabled state
        self.hotkeys_enabled = True

        # Forge options enabled (I, O, P, U)
        self.forge_enabled = True

        # Radial menu state
        self._radial_menu = None
        self._radial_items = [
            {'label': 'Hotkeys', 'icon': '\u2328', 'toggle': self._toggle_hotkeys,
             'state': lambda: self.hotkeys_enabled},
            {'label': 'Sprint', 'icon': '\U0001f3c3', 'toggle': lambda: self.toggle_sprint(force=True),
             'state': lambda: self.sprint_enabled},
            {'label': 'Forge', 'icon': '\U0001f525', 'toggle': self._toggle_forge,
             'state': lambda: self.forge_enabled},
            {'label': 'Mini', 'icon': '\u25CB', 'toggle': self._toggle_mini_mode,
             'state': lambda: self._mini_mode},
            {'label': 'Wiki', 'icon': '\U0001f4d6', 'toggle': self._radial_wiki_search,
             'state': lambda: self.wiki_panel_open},
        ]

        # Mini mode state
        self._mini_mode = False
        self._mini_win = None

        # Macro editor state
        self.macro_panel_open = False
        self.macro_panel = None
        self.macro_recording = False
        self.macro_replaying = False
        self.macro_looping = False
        self.macro_record_kb = True
        self.macro_record_mouse = False
        self.macro_actions = []
        self.macro_saved = {}
        self.macro_selected_name = None
        self.macro_record_hotkey = 'f9'
        self.macro_hotkey_mode = 'record'  # 'record' or 'replay'
        self._macro_replay_idx = 0
        self._macro_kb_hook = None
        self._macro_mouse_hook = None
        self._macro_record_start = 0
        self._macro_last_event_time = 0
        self._macro_replay_thread = None
        self._macro_replay_stop = False

        # Wiki state
        self.wiki_panel_open = False
        self.wiki_panel = None

        # Periodic attack state (sub-feature of autoclicker)
        self.periodic_attack = False
        self.periodic_key1 = '2'       # first key to press
        self.periodic_key2 = '1'       # second key to press
        self.periodic_interval1 = 3.0  # cycle period in seconds
        self.periodic_delay2 = 1.0     # delay before second key press

        # Auto Sell state
        self.auto_sell_positions = {}   # {'sell_items': (x,y), ...}
        self.auto_sell_active = False
        self.auto_sell_interval = 300   # seconds (default 5min)
        self._auto_sell_stop = False
        self._auto_sell_executing = False
        self._auto_sell_overlays = []
        self.auto_sell_camlock = False
        self._load_auto_sell()

        # Auto-phase state (I -> O -> P, advances on GO screen)
        self.auto_phase = False
        self.phase_idx = 0  # 0=jiggle, 1=bar_game, 2=circle

        # Hotkeys (rebindable)
        self._hotkey_map = {
            'circle':      {'key': 'p',  'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.forge_enabled and self.toggle()},
            'jiggle':      {'key': 'i',  'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.forge_enabled and self.toggle_jiggle()},
            'bar_game':    {'key': 'o',  'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.forge_enabled and self._handle_o()},
            'auto_phase':  {'key': 'u',  'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.forge_enabled and self.toggle_auto_phase()},
            'autoclicker': {'key': 'f5', 'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.toggle_autoclicker()},
            'hold_left':   {'key': 'f6', 'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.toggle_holding_left()},
            'sprint':      {'key': 'caps lock', 'hook': None, 'callback': lambda _: self.hotkeys_enabled and self.toggle_sprint()},
        }
        for entry in self._hotkey_map.values():
            entry['hook'] = keyboard.on_press_key(entry['key'], entry['callback'])
        self._capturing_hotkey = None  # name of hotkey currently being rebound
        self._hotkey_ui = {}  # filled in _build_gui: name -> {'type': 'label'|'canvas', 'widget': ...}
        keyboard.on_press_key('enter', lambda _: self.hotkeys_enabled and self._handle_enter())
        self._macro_f9_hotkey_id = keyboard.add_hotkey('f9', self._macro_hotkey_dispatch)

        # GUI
        self._build_gui()

        # Worker threads
        Thread(target=self._loop, daemon=True).start()
        Thread(target=self._jiggle_loop, daemon=True).start()
        Thread(target=self._bar_game_loop, daemon=True).start()
        Thread(target=self._go_detector_loop, daemon=True).start()
        Thread(target=self._autoclicker_loop, daemon=True).start()
        Thread(target=self._hold_left_loop, daemon=True).start()
        Thread(target=self._sprint_loop, daemon=True).start()
        Thread(target=self._periodic_attack_loop, daemon=True).start()
        Thread(target=self._auto_sell_loop, daemon=True).start()

    # ------------------------------------------------------ Hotkeys toggle
    def _toggle_hotkeys(self):
        self.hotkeys_enabled = not self.hotkeys_enabled
        if self.hotkeys_enabled:
            self.hotkey_btn.config(text='Hotkeys: ON', fg='#50fa7b',
                                   activeforeground='#50fa7b')
        else:
            self.hotkey_btn.config(text='Hotkeys: OFF', fg='#ff5555',
                                   activeforeground='#ff5555')
        print(f"[HOTKEYS] {'ON' if self.hotkeys_enabled else 'OFF'}")

    # ------------------------------------------------------ Forge toggle
    def _toggle_forge(self):
        self.forge_enabled = not self.forge_enabled
        if not self.forge_enabled:
            # Turn off all forge features when disabling
            self.active = False
            self.jiggling = False
            self.bar_game = False
            self.bar_shaping = False
            self.auto_phase = False
        self.root.after(0, self._refresh_gui)
        print(f"[FORGE] {'ON' if self.forge_enabled else 'OFF'}")

    # ------------------------------------------------------ Mini mode
    def _toggle_mini_mode(self):
        self._mini_mode = not self._mini_mode
        if self._mini_mode:
            self.root.withdraw()
            self._build_mini_win()
        else:
            self._destroy_mini_win()
            self.root.deiconify()
        print(f"[MINI] {'ON' if self._mini_mode else 'OFF'}")

    def _build_mini_win(self):
        BG = '#0d1117'
        CIRCLE_SIZE = 36
        TRANSPARENT = '#010101'

        win = tk.Toplevel()
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.attributes('-transparentcolor', TRANSPARENT)
        win.configure(bg=TRANSPARENT)

        # Position at the old main-window location
        x = self.root.winfo_x()
        y = self.root.winfo_y()

        # Canvas for the draggable circle
        cvs = tk.Canvas(win, width=CIRCLE_SIZE, height=CIRCLE_SIZE,
                        bg=TRANSPARENT, highlightthickness=0)
        cvs.pack(side=tk.LEFT)
        # Outer glow
        cvs.create_oval(1, 1, CIRCLE_SIZE - 1, CIRCLE_SIZE - 1,
                        outline='#238636', width=2, fill=BG)
        # Inner icon
        cvs.create_text(CIRCLE_SIZE // 2, CIRCLE_SIZE // 2,
                        text='L', font=('Consolas', 13, 'bold'), fill='#50fa7b')

        # Floating labels frame (right of circle)
        lbl_frame = tk.Frame(win, bg=TRANSPARENT)
        lbl_frame.pack(side=tk.LEFT, padx=(4, 0))

        self._mini_labels = {}
        self._mini_lbl_frame = lbl_frame
        self._mini_win = win
        self._mini_cvs = cvs

        # Dragging
        def _start_drag(event):
            self._mini_drag_x = event.x_root - win.winfo_x()
            self._mini_drag_y = event.y_root - win.winfo_y()

        def _on_drag(event):
            nx = event.x_root - self._mini_drag_x
            ny = event.y_root - self._mini_drag_y
            win.geometry(f"+{nx}+{ny}")

        for w in (cvs,):
            w.bind('<Button-1>', _start_drag)
            w.bind('<B1-Motion>', _on_drag)

        # Double-click to restore full GUI
        cvs.bind('<Double-Button-1>', lambda e: self._toggle_mini_mode())

        win.geometry(f"+{x}+{y}")
        self._refresh_mini()

    def _refresh_mini(self):
        """Update the floating labels to show only active features."""
        if not self._mini_mode or not self._mini_win:
            return
        TRANSPARENT = '#010101'

        # Collect active features: (name, color)
        features = []
        if not self.forge_enabled:
            features.append(('Forge OFF', '#ff5555'))
        if self.jiggling:
            features.append(('Smelting', '#50fa7b'))
        if self.bar_game and not self.bar_shaping:
            features.append(('Casting', '#50fa7b'))
        if self.bar_shaping:
            features.append(('Shaping', '#58a6ff'))
        if self.active:
            features.append(('Welding', '#50fa7b'))
        if self.auto_phase:
            features.append(('Auto-Phase', '#f0c040'))
        if self.autoclicker:
            features.append(('Autoclick', '#50fa7b'))
        if self.holding_left:
            features.append(('Hold Left', '#50fa7b'))
        if self.sprint_enabled:
            features.append(('Sprint', '#50fa7b'))
        if self.periodic_attack:
            features.append(('Periodic', '#bd93f9'))
        if self.auto_sell_active:
            features.append(('AutoSell', '#ff79c6'))

        # Rebuild labels only when the set of active features changes
        active_keys = tuple((n, c) for n, c in features)
        if hasattr(self, '_mini_last_keys') and self._mini_last_keys == active_keys:
            return
        self._mini_last_keys = active_keys

        # Clear old labels
        for w in self._mini_lbl_frame.winfo_children():
            w.destroy()

        for name, color in features:
            tk.Label(self._mini_lbl_frame, text=name,
                     font=('Consolas', 9, 'bold'), fg=color,
                     bg=TRANSPARENT).pack(anchor='w')

        # Resize the window to fit
        self._mini_win.update_idletasks()
        w = self._mini_cvs.winfo_reqwidth() + self._mini_lbl_frame.winfo_reqwidth() + 4
        h = max(self._mini_cvs.winfo_reqheight(),
                self._mini_lbl_frame.winfo_reqheight(), 36)
        x = self._mini_win.winfo_x()
        y = self._mini_win.winfo_y()
        self._mini_win.geometry(f"{w}x{h}+{x}+{y}")

    def _destroy_mini_win(self):
        if self._mini_win:
            self._mini_win.destroy()
            self._mini_win = None
            self._mini_labels = {}
            if hasattr(self, '_mini_last_keys'):
                del self._mini_last_keys

    # ---------------------------------------------------- Radial menu
    def _poll_middle_click(self):
        """Poll for middle mouse button press via GetAsyncKeyState."""
        VK_MBUTTON = 0x04
        state = ctypes.windll.user32.GetAsyncKeyState(VK_MBUTTON)
        if state & 0x0001:  # pressed since last poll
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            try:
                self._open_radial_menu(pt.x, pt.y)
            except Exception:
                import traceback
                traceback.print_exc()
        if self.running:
            self.root.after(50, self._poll_middle_click)

    def _open_radial_menu(self, mx, my):
        """Open a radial menu centered on the mouse cursor."""
        print(f"[RADIAL] Middle-click at ({mx}, {my})")
        if self._radial_menu is not None:
            self._close_radial_menu()
            return

        TRANS = '#010101'
        BG_RING = '#161b22'
        BORDER = '#21262d'

        outer_r = 80
        inner_r = 30
        hover_pad = 15  # extra hit area beyond drawn ring
        pad = 5 + hover_pad
        size = (outer_r + pad) * 2
        c = size // 2

        menu = tk.Toplevel(self.root)
        menu.overrideredirect(True)
        menu.attributes('-topmost', True)
        menu.attributes('-transparentcolor', TRANS)
        menu.configure(bg=TRANS)
        menu.geometry(f'{size}x{size}+{mx - c}+{my - c}')

        canvas = tk.Canvas(menu, width=size, height=size,
                           bg=TRANS, highlightthickness=0)
        canvas.pack()

        items = self._radial_items
        n = len(items)
        seg = 360.0 / n

        # Invisible hover zone — #020202 is 1 shade off transparent key,
        # visually identical but catches mouse events for approach detection
        HOVER_ZONE = '#020202'
        hr = outer_r + hover_pad
        canvas.create_oval(
            c - hr, c - hr, c + hr, c + hr,
            fill=HOVER_ZONE, outline='', width=0)

        # Arc segments (clockwise from top)
        arc_ids = []
        for i in range(n):
            # Clamp extent to avoid degenerate -360 arc that draws nothing
            ext = max(-seg, -359.99)
            arc = canvas.create_arc(
                c - outer_r, c - outer_r, c + outer_r, c + outer_r,
                start=90 - i * seg, extent=ext,
                fill=BG_RING, outline=BORDER, width=2, style='pieslice')
            arc_ids.append(arc)

        # Inner circle (donut hole)
        canvas.create_oval(
            c - inner_r, c - inner_r, c + inner_r, c + inner_r,
            fill=HOVER_ZONE, outline=BORDER, width=2)

        # Icons on each segment
        icon_ids = []
        for i, item in enumerate(items):
            theta = np.radians((i + 0.5) * seg)
            r_mid = (outer_r + inner_r) / 2
            ix = c + r_mid * np.sin(theta)
            iy = c - r_mid * np.cos(theta)
            on = item['state']()
            icon_id = canvas.create_text(
                ix, iy, text=item['icon'],
                font=('Segoe UI Symbol', 20), fill='#50fa7b' if on else '#ff5555')
            icon_ids.append(icon_id)

        # Center label
        center_lbl = canvas.create_text(
            c, c, text='', font=('Consolas', 10, 'bold'), fill='#8b949e')

        self._radial_menu = menu
        self._radial_data = {
            'canvas': canvas, 'arc_ids': arc_ids, 'icon_ids': icon_ids,
            'center_lbl': center_lbl, 'c': c,
            'outer_r': outer_r + hover_pad, 'inner_r': max(inner_r - hover_pad, 5),
            'seg': seg, 'hovered': -1,
            'menu_x': mx - c, 'menu_y': my - c,
        }

        canvas.bind('<Motion>', self._radial_on_motion)
        canvas.bind('<B2-Motion>', self._radial_on_motion)
        canvas.bind('<Leave>', self._radial_on_leave)
        canvas.bind('<Button-1>', self._radial_on_click)
        menu.bind('<Escape>', lambda e: self._close_radial_menu())
        menu.bind('<FocusOut>',
                  lambda e: self.root.after(50, self._close_radial_menu))
        menu.focus_force()
        self.root.after(30, self._poll_middle_release)

    def _poll_middle_release(self):
        """While radial is open, poll cursor and watch for middle-button release."""
        if self._radial_menu is None:
            return
        d = self._radial_data
        if d is None:
            return

        # Get cursor screen position and convert to canvas coords
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        cx = pt.x - d['menu_x']
        cy = pt.y - d['menu_y']

        # Update hover highlight using canvas coords
        idx = self._radial_segment_at(cx, cy)
        if idx != d['hovered']:
            canvas = d['canvas']
            if d['hovered'] >= 0:
                canvas.itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
            if idx >= 0:
                canvas.itemconfig(d['arc_ids'][idx], fill='#30363d')
                canvas.itemconfig(d['center_lbl'],
                                  text=self._radial_items[idx]['label'])
            else:
                canvas.itemconfig(d['center_lbl'], text='')
            d['hovered'] = idx

        VK_MBUTTON = 0x04
        state = ctypes.windll.user32.GetAsyncKeyState(VK_MBUTTON)
        if not (state & 0x8000):  # middle button released
            if d['hovered'] >= 0:
                sel = d['hovered']
                self._close_radial_menu()
                self._radial_items[sel]['toggle']()
            return
        self.root.after(30, self._poll_middle_release)

    def _radial_segment_at(self, x, y):
        """Return the segment index at canvas coords (x, y), or -1."""
        d = self._radial_data
        dx = x - d['c']
        dy = y - d['c']
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < d['inner_r'] or dist > d['outer_r']:
            return -1
        angle = np.degrees(np.arctan2(dx, -dy)) % 360
        return min(int(angle / d['seg']), len(self._radial_items) - 1)

    def _radial_on_motion(self, event):
        """Highlight the hovered segment."""
        if self._radial_menu is None:
            return
        d = self._radial_data
        idx = self._radial_segment_at(event.x, event.y)
        if idx == d['hovered']:
            return
        canvas = d['canvas']
        if d['hovered'] >= 0:
            canvas.itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
        if idx >= 0:
            canvas.itemconfig(d['arc_ids'][idx], fill='#30363d')
            canvas.itemconfig(d['center_lbl'],
                              text=self._radial_items[idx]['label'])
        else:
            canvas.itemconfig(d['center_lbl'], text='')
        d['hovered'] = idx

    def _radial_on_leave(self, event):
        """Clear highlight when the mouse leaves the ring."""
        if self._radial_menu is None:
            return
        d = self._radial_data
        if d['hovered'] >= 0:
            d['canvas'].itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
            d['canvas'].itemconfig(d['center_lbl'], text='')
            d['hovered'] = -1

    def _radial_on_click(self, event):
        """Execute the clicked segment's action and close the menu."""
        if self._radial_menu is None:
            return
        idx = self._radial_segment_at(event.x, event.y)
        self._close_radial_menu()
        if 0 <= idx < len(self._radial_items):
            self._radial_items[idx]['toggle']()

    def _close_radial_menu(self):
        """Close the radial menu."""
        if self._radial_menu is None:
            return
        try:
            self._radial_menu.destroy()
        except tk.TclError:
            pass
        self._radial_menu = None
        self._radial_data = None

    # --------------------------------------------------------- Hotkey helpers
    def _handle_o(self):
        """O = bar game."""
        self.toggle_bar_game()

    def _handle_enter(self):
        """Enter during auto-phase ready: move cursor to middle-bottom of screen."""
        if not self.auto_phase or self.phase_idx != -1:
            return
        if not self._roblox_focused():
            return
        mon = self.monitor_rect
        target_x = mon['left'] + mon['width'] // 2
        target_y = mon['top'] + int(mon['height'] * 0.86)
        self._move_to(target_x, target_y)
        self._click(target_x, target_y)
        print(f"[ENTER] Cursor -> ({target_x}, {target_y}) + click")

    # --------------------------------------------------------------- Focus
    def _roblox_focused(self):
        """Check if Roblox Player is the foreground window (by process exe)."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
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

    def _detect_roblox_game(self):
        """Read the latest Roblox log to extract the current Place ID and game name."""
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
            # Resolve place ID -> universe ID -> game name (public APIs, no auth)
            import urllib.request
            # Step 1: place -> universe
            url1 = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
            req1 = urllib.request.Request(url1, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req1, timeout=3) as resp:
                universe_id = json.loads(resp.read().decode()).get("universeId")
            if not universe_id:
                return place_id, None
            # Step 2: universe -> game details
            url2 = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
            req2 = urllib.request.Request(url2, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req2, timeout=3) as resp:
                data = json.loads(resp.read().decode()).get("data", [])
            if data:
                return place_id, data[0].get("name")
            return place_id, None
        except Exception:
            return getattr(self, '_last_place_id', None), getattr(self, '_last_game_name', None)

    # --------------------------------------------------------------- Input
    def _setup_sendinput(self):
        """Prepare correct SendInput structs for 64-bit Windows."""
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

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

        # Virtual screen metrics for MOUSEEVENTF_ABSOLUTE (spans all monitors)
        self._virt_left = ctypes.windll.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        self._virt_top  = ctypes.windll.user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        self._virt_w    = ctypes.windll.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        self._virt_h    = ctypes.windll.user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN

    def _get_abs_coords(self):
        """Get current cursor position as ABSOLUTE coordinates for SendInput."""
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        abs_x = int((pt.x - self._virt_left) * 65535 / (self._virt_w - 1))
        abs_y = int((pt.y - self._virt_top) * 65535 / (self._virt_h - 1))
        return abs_x, abs_y, pt.x, pt.y

    def _send_mouse(self, flags, abs_x=None, abs_y=None):
        """Send a single mouse event via SendInput."""
        INPUT = self._INPUT
        MOUSEINPUT = self._MOUSEINPUT
        if abs_x is None:
            abs_x, abs_y, _, _ = self._get_abs_coords()
        inp = INPUT()
        inp.type = 0
        inp.union.mi = MOUSEINPUT(abs_x, abs_y, 0, flags, 0, 0)
        arr = (INPUT * 1)(inp)
        return ctypes.windll.user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def _send_key(self, scan_code, key_up=False, extended=False):
        """Send a keyboard event via SendInput using scan codes."""
        INPUT = self._INPUT
        KEYBDINPUT = self._KEYBDINPUT
        # KEYEVENTF_SCANCODE=0x0008, KEYEVENTF_KEYUP=0x0002, KEYEVENTF_EXTENDEDKEY=0x0001
        flags = 0x0008  # scan code mode
        if extended:
            flags |= 0x0001
        if key_up:
            flags |= 0x0002
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(0, scan_code, flags, 0, 0)
        arr = (INPUT * 1)(inp)
        return ctypes.windll.user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def _move_to(self, target_x, target_y, steps=20, duration=0.05):
        """Smoothly drag cursor to target using relative SendInput moves."""
        INPUT = self._INPUT
        MOUSEINPUT = self._MOUSEINPUT

        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

        total_dx = target_x - pt.x
        total_dy = target_y - pt.y

        if abs(total_dx) < 2 and abs(total_dy) < 2:
            return  # already there

        step_delay = duration / steps
        for i in range(steps):
            dx = int(total_dx * (i + 1) / steps) - int(total_dx * i / steps)
            dy = int(total_dy * (i + 1) / steps) - int(total_dy * i / steps)
            inp = INPUT()
            inp.type = 0
            inp.union.mi = MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)  # MOVE relative
            arr = (INPUT * 1)(inp)
            ctypes.windll.user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))
            time.sleep(step_delay)

    def _click(self, x, y):
        """Click at current cursor position via SendInput ABSOLUTE — cursor already dragged here."""
        abs_x, abs_y, px, py = self._get_abs_coords()

        # ABSOLUTE | VIRTUALDESK | LEFTDOWN — click at current position
        self._send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
        time.sleep(0.03)  # 30ms hold
        sent = self._send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)

        print(f"[CLICK] at ({px},{py}) abs=({abs_x},{abs_y}) sent={sent}")
        self.root.after(0, lambda: self._show_hit(px, py))

    def _show_hit(self, x, y):
        """Show a floating 'HIT' label at click position that fades after 300ms."""
        hit = tk.Toplevel(self.root)
        hit.overrideredirect(True)
        hit.attributes('-topmost', True)
        hit.attributes('-transparentcolor', '#000000')
        hit.configure(bg='#000000')
        hit.geometry(f"50x25+{x - 25}+{y + 15}")
        tk.Label(
            hit, text="HIT", font=("Consolas", 14, "bold"),
            fg="#ff2222", bg='#000000'
        ).pack()
        hit.after(300, hit.destroy)

    # --------------------------------------------------------- Overlays
    def _make_arrow_overlay(self, label_text):
        """Create a red arrow overlay positioned to the left of a target."""
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.configure(bg='#1a1a1a')
        ov.geometry("75x24+0+0")
        tk.Label(
            ov, text=f"{label_text} \u25b6", font=("Consolas", 12, "bold"),
            fg="#ff2222", bg='#1a1a1a'
        ).pack(fill='both', expand=True)
        ov.withdraw()
        return ov

    def _update_bar_overlays(self, scr_x, bar_y, slit_y, width,
                             col_left_scr=None, col_right_scr=None,
                             bot_scr=None):
        """Reposition red arrow overlays to the left of the bar and slit."""
        try:
            arrow_x = scr_x - 75  # position arrows to the left of the bar
            if bar_y is not None:
                self._bar_ov.geometry(f"70x22+{arrow_x}+{bar_y - 11}")
                self._bar_ov.deiconify()
            else:
                self._bar_ov.withdraw()
            if slit_y is not None:
                self._slit_ov.geometry(f"70x22+{arrow_x}+{slit_y - 11}")
                self._slit_ov.deiconify()
            else:
                self._slit_ov.withdraw()
            # Vertical red lines showing search region
            mon_h = self.monitor_rect['height']
            if col_left_scr is not None:
                self._col_left_ov.geometry(f"2x{mon_h}+{col_left_scr}+{self.monitor_rect['top']}")
                self._col_left_ov.deiconify()
                self._col_right_ov.geometry(f"2x{mon_h}+{col_right_scr}+{self.monitor_rect['top']}")
                self._col_right_ov.deiconify()
            else:
                self._col_left_ov.withdraw()
                self._col_right_ov.withdraw()
            # Horizontal red line showing bottom cutoff
            if bot_scr is not None:
                mon_w = self.monitor_rect['width']
                self._bot_ov.geometry(f"{mon_w}x2+{self.monitor_rect['left']}+{bot_scr}")
                self._bot_ov.deiconify()
            else:
                self._bot_ov.withdraw()
        except Exception:
            pass

    def _update_ring(self, x, y, text, color='#ff2222'):
        """Show targeting ring centered at screen (x, y) with timer text."""
        try:
            half = self._ring_size // 2
            self._ring_ov.geometry(f"+{x - half}+{y - half}")
            self._ring_cvs.itemconfig(self._ring_id, outline=color)
            self._ring_ov.deiconify()
            self._dtimer_lbl.config(text=text, fg=color)
            self._dtimer_ov.geometry(f"+{x + half + 5}+{y + half - 10}")
            self._dtimer_ov.deiconify()
        except Exception:
            pass

    def _hide_ring(self):
        try:
            self._ring_ov.withdraw()
            self._dtimer_ov.withdraw()
        except Exception:
            pass

    def _hide_bar_overlays(self):
        try:
            self._bar_ov.withdraw()
            self._slit_ov.withdraw()
            self._col_left_ov.withdraw()
            self._col_right_ov.withdraw()
            self._bot_ov.withdraw()
        except Exception:
            pass

    # --------------------------------------------------------------- Debug
    def toggle_debug(self):
        self.debug = not self.debug
        if self.debug:
            self.active = False
            self.jiggling = False
        self.root.after(0, self._refresh_gui)
        print(f"[DEBUG] {'ON' if self.debug else 'OFF'}")

    # --------------------------------------------------------- Autoclicker
    def toggle_autoclicker(self, force=False):
        if not force and not self._roblox_focused():
            return
        if self.autoclicker:
            self.autoclicker = False
        else:
            self.active = False
            self.jiggling = False
            self.bar_game = False
            self.debug = False
            self.autoclicker = True
        self.root.after(0, self._refresh_gui)
        print(f"[AUTOCLICK] {'ON' if self.autoclicker else 'OFF'}")

    def _autoclicker_loop(self):
        """Click at cursor position every 0.1s while active and Roblox is focused."""
        while self.running:
            if not self.autoclicker or not self._roblox_focused() or self._auto_sell_executing:
                time.sleep(0.05)
                continue
            abs_x, abs_y, _, _ = self._get_abs_coords()
            self._send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
            time.sleep(0.03)
            self._send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)
            time.sleep(0.07)

    # ---------------------------------------------- Auto Sell
    def _auto_sell_save_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'autosell.json')

    def _load_auto_sell(self):
        path = self._auto_sell_save_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                # Convert lists back to tuples
                self.auto_sell_positions = {
                    k: tuple(v) for k, v in data.get('positions', {}).items()
                }
                self.auto_sell_interval = data.get('interval', 300)
                self.auto_sell_camlock = data.get('camlock', False)
            except Exception:
                self.auto_sell_positions = {}
        else:
            self.auto_sell_positions = {}

    def _save_auto_sell(self):
        try:
            data = {
                'positions': self.auto_sell_positions,
                'interval': self.auto_sell_interval,
                'camlock': self.auto_sell_camlock,
            }
            with open(self._auto_sell_save_path(), 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[AUTO-SELL] Save error: {e}")

    @staticmethod
    def _fmt_interval(seconds):
        """Format seconds as human-readable e.g. '5m 0s'."""
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def _on_auto_sell_slider(self, val):
        self.auto_sell_interval = int(val)
        self._as_interval_lbl.config(text=self._fmt_interval(self.auto_sell_interval))
        self._save_auto_sell()

    def _toggle_auto_sell_camlock(self):
        self.auto_sell_camlock = not self.auto_sell_camlock
        color = '#50fa7b' if self.auto_sell_camlock else '#484f58'
        self._as_camlock_btn.config(fg=color, activeforeground=color)
        self._save_auto_sell()
        print(f"[AUTO-SELL] Camlock {'ON' if self.auto_sell_camlock else 'OFF'}")

    def _toggle_auto_sell(self):
        if not self.auto_sell_positions:
            print("[AUTO-SELL] No positions configured. Run Setup first.")
            return
        self.auto_sell_active = not self.auto_sell_active
        self.root.after(0, self._refresh_gui)
        print(f"[AUTO-SELL] {'ON' if self.auto_sell_active else 'OFF'}")

    def _wait_for_click_or_esc(self):
        """Block until the user left-clicks or presses Escape.

        Returns (x, y) on click, or None if cancelled with Escape.
        """
        import threading
        result = [None]
        cancelled = [False]
        evt = threading.Event()

        def on_esc(_):
            cancelled[0] = True
            evt.set()

        esc_hook = keyboard.on_press_key('escape', on_esc)

        if mouse:
            def on_click():
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                result[0] = (pt.x, pt.y)
                evt.set()
            mouse_hook = mouse.on_click(on_click)
            evt.wait()
            mouse.unhook(mouse_hook)
        else:
            # Fallback: poll GetAsyncKeyState for left-click
            while not evt.is_set():
                if ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    while ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:
                        time.sleep(0.01)
                    result[0] = (pt.x, pt.y)
                    break
                time.sleep(0.01)

        keyboard.unhook_key(esc_hook)
        if cancelled[0]:
            return None
        return result[0]

    def _auto_sell_setup(self):
        """Wizard to capture button positions for auto-sell.

        Shows a floating label that follows the cursor indicating
        which button to click next.  Each click is captured silently.
        Press Escape at any time to cancel.
        """
        steps = [
            ('sell_items', 'Click: Sell Items'),
            ('select_all', 'Click: Select All'),
            ('accept', 'Click: Accept'),
            ('yes', 'Click: Yes'),
            ('close', 'Click: X (close)'),
        ]
        positions = {}

        # --- floating cursor label ---
        TRANS = '#010101'
        tip = [None, None]  # [window, label]

        def _create_tip(text):
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.attributes('-topmost', True)
            w.attributes('-transparentcolor', TRANS)
            w.configure(bg=TRANS)
            lbl = tk.Label(w, text=text,
                           font=('Consolas', 11, 'bold'),
                           fg='#ff79c6', bg='#0d1117',
                           padx=6, pady=2)
            lbl.pack()
            tip[0] = w
            tip[1] = lbl

        def _update_tip_pos():
            w = tip[0]
            if w is None:
                return
            try:
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                w.geometry(f'+{pt.x + 18}+{pt.y + 18}')
            except Exception:
                pass
            if w.winfo_exists():
                w.after(16, _update_tip_pos)

        def _set_tip_text(text):
            if tip[0] is not None:
                tip[1].config(text=text)

        def _destroy_tip():
            if tip[0] is not None:
                try:
                    tip[0].destroy()
                except Exception:
                    pass
                tip[0] = None

        # Step 0: wait for user to focus Roblox
        self.root.after(0, lambda: _create_tip('Focus Roblox, then click [ESC cancel]'))
        self.root.after(0, _update_tip_pos)
        pos = self._wait_for_click_or_esc()
        if pos is None:
            self.root.after(0, _destroy_tip)
            print("[AUTO-SELL] Setup cancelled.")
            return

        # Press T to open stash
        self.root.after(0, lambda: _set_tip_text('Opening stash...'))
        self._press_game_key('t')
        time.sleep(2.0)

        # Capture each button click
        for key, label_text in steps:
            self.root.after(0, lambda t=label_text: _set_tip_text(t + '  [ESC cancel]'))
            time.sleep(0.3)
            pos = self._wait_for_click_or_esc()
            if pos is None:
                self.root.after(0, _destroy_tip)
                print("[AUTO-SELL] Setup cancelled.")
                return
            positions[key] = pos
            print(f"[AUTO-SELL] Captured {key}: {pos}")

        self.root.after(0, _destroy_tip)
        self.auto_sell_positions = positions
        self._save_auto_sell()
        self.root.after(0, self._draw_auto_sell_overlays)
        print("[AUTO-SELL] Setup complete.")

    def _draw_auto_sell_overlays(self):
        """Draw small overlay circles at each saved position."""
        self._clear_auto_sell_overlays()
        if not self.auto_sell_positions:
            return

        TRANS = '#010101'
        labels = {
            'sell_items': 'Sell',
            'select_all': 'SelAll',
            'accept': 'Accept',
            'yes': 'Yes',
            'close': 'Close',
        }
        for key, (x, y) in self.auto_sell_positions.items():
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.attributes('-transparentcolor', TRANS)
            win.configure(bg=TRANS)

            size = 40
            cvs = tk.Canvas(win, width=size, height=size + 14,
                            bg=TRANS, highlightthickness=0)
            cvs.pack()
            # Circle
            cvs.create_oval(4, 4, size - 4, size - 4,
                            outline='#ff79c6', width=2, fill='')
            # Label
            lbl_text = labels.get(key, key)
            cvs.create_text(size // 2, size + 6,
                            text=lbl_text, font=('Consolas', 8, 'bold'),
                            fill='#ff79c6')

            win.geometry(f"{size}x{size + 14}+{x - size // 2}+{y - size // 2}")
            self._auto_sell_overlays.append(win)

    def _clear_auto_sell_overlays(self):
        for win in self._auto_sell_overlays:
            try:
                win.destroy()
            except Exception:
                pass
        self._auto_sell_overlays = []

    def _click_at_screen(self, x, y):
        """Smoothly drag the cursor to (x, y) then click."""
        # Get current cursor position
        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        sx, sy = pt.x, pt.y

        # Interpolate from current position to target
        steps = 20
        duration = 0.15  # seconds for the drag
        for i in range(1, steps + 1):
            t = i / steps
            ix = sx + (x - sx) * t
            iy = sy + (y - sy) * t
            abs_x = int((ix - self._virt_left) * 65535 / (self._virt_w - 1))
            abs_y = int((iy - self._virt_top) * 65535 / (self._virt_h - 1))
            self._send_mouse(0x8000 | 0x4000 | 0x0001, abs_x, abs_y)
            time.sleep(duration / steps)

        # Click at final position
        abs_x = int((x - self._virt_left) * 65535 / (self._virt_w - 1))
        abs_y = int((y - self._virt_top) * 65535 / (self._virt_h - 1))
        self._send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
        time.sleep(0.03)
        self._send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)

    _SCAN_LCTRL = 0x1D  # scan code for Left Control

    def _execute_auto_sell(self):
        """Perform the sell sequence: T -> Sell Items -> Select All -> Accept -> Yes -> Close."""
        self._auto_sell_executing = True
        try:
            # Unlock camera if camlock enabled
            if self.auto_sell_camlock:
                self._send_key(self._SCAN_LCTRL, key_up=False)
                time.sleep(0.05)
                self._send_key(self._SCAN_LCTRL, key_up=True)
                time.sleep(0.3)

            steps = [
                ('t_key', None, 2.0),
                ('click', 'sell_items', 2.0),
                ('click', 'select_all', 2.0),
                ('click', 'accept', 4.0),
                ('click', 'yes', 2.0),
                ('click', 'close', 2.0),
            ]
            for step_type, target, delay in steps:
                if self._auto_sell_stop or not self.auto_sell_active:
                    return
                if step_type == 't_key':
                    self._press_game_key('t')
                else:
                    pos = self.auto_sell_positions.get(target)
                    if pos:
                        self._click_at_screen(pos[0], pos[1])
                deadline = time.time() + delay
                while time.time() < deadline:
                    if self._auto_sell_stop or not self.auto_sell_active or not self.running:
                        return
                    time.sleep(0.05)
        finally:
            # Re-lock camera if camlock enabled
            if self.auto_sell_camlock:
                self._send_key(self._SCAN_LCTRL, key_up=False)
                time.sleep(0.05)
                self._send_key(self._SCAN_LCTRL, key_up=True)
            self._auto_sell_executing = False

    def _auto_sell_loop(self):
        """Background loop that repeats the sell sequence on a timer."""
        while self.running:
            if not self.auto_sell_active or not self._roblox_focused():
                time.sleep(0.1)
                continue
            if not self.auto_sell_positions:
                time.sleep(0.1)
                continue

            self._execute_auto_sell()

            # Wait for interval
            deadline = time.time() + self.auto_sell_interval
            while time.time() < deadline:
                if self._auto_sell_stop or not self.auto_sell_active or not self.running:
                    break
                time.sleep(0.1)

    # ---------------------------------------------- Periodic Attack (autoclick sub-feature)
    def toggle_periodic_attack(self):
        self.periodic_attack = not self.periodic_attack
        self.root.after(0, self._refresh_gui)
        print(f"[PERIODIC] {'ON' if self.periodic_attack else 'OFF'}")

    def _press_game_key(self, key_name):
        """Press and release a key by its character name via SendInput."""
        scan = _SCAN_CODES.get(key_name.lower())
        if scan is None:
            return
        self._send_key(scan, key_up=False)
        time.sleep(0.05)
        self._send_key(scan, key_up=True)

    def _periodic_attack_loop(self):
        """Periodically press two keys in sequence while autoclicker + periodic attack are active."""
        while self.running:
            if not self.periodic_attack or not self.autoclicker or not self._roblox_focused():
                time.sleep(0.05)
                continue
            # Press first key
            self._press_game_key(self.periodic_key1)
            # Wait for delay before second key
            deadline = time.time() + self.periodic_delay2
            while time.time() < deadline:
                if not self.periodic_attack or not self.autoclicker or not self.running:
                    break
                time.sleep(0.05)
            if not self.periodic_attack or not self.autoclicker or not self.running:
                continue
            # Press second key
            self._press_game_key(self.periodic_key2)
            # Wait remaining time to complete the cycle
            remaining = self.periodic_interval1 - self.periodic_delay2
            if remaining > 0:
                deadline = time.time() + remaining
                while time.time() < deadline:
                    if not self.periodic_attack or not self.autoclicker or not self.running:
                        break
                    time.sleep(0.05)

    # ------------------------------------------------ Pipeline node click handler
    def _on_node_click(self, idx):
        """Handle click on a pipeline node to toggle its phase."""
        if not self.forge_enabled:
            return
        self.auto_phase = False  # manual click overrides auto-phase
        if idx == 0:  # Smelting -> jiggle
            if self.jiggling:
                self.jiggling = False
            else:
                self.active = False
                self.bar_game = False
                self.bar_shaping = False
                self.autoclicker = False
                self.debug = False
                self.jiggling = True
        elif idx == 1:  # Casting -> bar_game
            if self.bar_game and not self.bar_shaping:
                self.bar_game = False
            else:
                self.active = False
                self.jiggling = False
                self.autoclicker = False
                self.debug = False
                self.bar_shaping = False
                self.bar_game = True
        elif idx == 2:  # Shaping
            if self.bar_shaping:
                self.bar_shaping = False
                self.bar_game = False
            else:
                self.active = False
                self.jiggling = False
                self.autoclicker = False
                self.debug = False
                self.bar_game = True
                self.bar_shaping = True
        elif idx == 3:  # Welding -> circle detection
            if self.active:
                self.active = False
            else:
                self.jiggling = False
                self.bar_game = False
                self.bar_shaping = False
                self.autoclicker = False
                self.debug = False
                self.active = True
        self._refresh_gui()
        print(f"[GUI] Toggled node {idx}")

    # --------------------------------------------------------- Hold Left Arrow
    _SCAN_LEFT = 0x4B  # scan code for left arrow (extended key)

    def toggle_holding_left(self, force=False):
        if not force and not self._roblox_focused():
            return
        self.holding_left = not self.holding_left
        if not self.holding_left:
            self._send_key(self._SCAN_LEFT, key_up=True, extended=True)
        self.root.after(0, self._refresh_gui)
        print(f"[HOLD LEFT] {'ON' if self.holding_left else 'OFF'}")

    def _hold_left_loop(self):
        """Hold left arrow key while active and Roblox is focused."""
        was_holding = False
        while self.running:
            if self.holding_left and self._roblox_focused():
                self._send_key(self._SCAN_LEFT, key_up=False, extended=True)
                was_holding = True
                time.sleep(0.05)
            else:
                if was_holding:
                    self._send_key(self._SCAN_LEFT, key_up=True, extended=True)
                    was_holding = False
                time.sleep(0.05)

    # --------------------------------------------------------------- Sprint
    _SCAN_LSHIFT = 0x2A  # scan code for Left Shift
    _WASD_VK = (0x57, 0x41, 0x53, 0x44)  # virtual-key codes for W, A, S, D

    def toggle_sprint(self, force=False):
        if not force and not self._roblox_focused():
            return
        self.sprint_enabled = not self.sprint_enabled
        if not self.sprint_enabled:
            self._send_key(self._SCAN_LSHIFT, key_up=True)
        self.root.after(0, self._refresh_gui)
        print(f"[SPRINT] {'ON' if self.sprint_enabled else 'OFF'}")

    def _sprint_loop(self):
        """Hold LeftShift while any WASD key is pressed and sprint is enabled."""
        GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
        shift_held = False
        while self.running:
            if self.sprint_enabled and self._roblox_focused():
                wasd_pressed = any(GetAsyncKeyState(vk) & 0x8000
                                   for vk in self._WASD_VK)
                if wasd_pressed and not shift_held:
                    self._send_key(self._SCAN_LSHIFT, key_up=False)
                    shift_held = True
                elif not wasd_pressed and shift_held:
                    self._send_key(self._SCAN_LSHIFT, key_up=True)
                    shift_held = False
            else:
                if shift_held:
                    self._send_key(self._SCAN_LSHIFT, key_up=True)
                    shift_held = False
            time.sleep(0.02)

    # --------------------------------------------------------------- Jiggle
    def toggle_jiggle(self, force=False):
        if not force and not self._roblox_focused():
            return
        if self.jiggling:
            self.jiggling = False
        else:
            self.debug = False
            self.active = False
            self.bar_game = False
            self.autoclicker = False
            self.jiggling = True
            if self.auto_phase:
                self.phase_idx = 0
        self.root.after(0, self._refresh_gui)
        print(f"[JIGGLE] {'ON' if self.jiggling else 'OFF'}")

    def _jiggle_loop(self):
        """Smoothly move cursor between 20% from top and 20% from bottom of screen."""
        INPUT = self._INPUT
        MOUSEINPUT = self._MOUSEINPUT
        steps = 30
        mon_top = self.monitor_rect['top']
        going_up = True  # alternate direction each pass

        while self.running:
            if not self.jiggling or not self._roblox_focused():
                time.sleep(0.05)
                going_up = True
                continue

            step_delay = self.jiggle_period / steps

            # Where are we now, and where do we want to go?
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cur_y = pt.y

            if going_up:
                target_y = mon_top + self.jiggle_top
            else:
                target_y = mon_top + self.jiggle_bottom

            total_dy = target_y - cur_y
            for i in range(steps):
                if not self.jiggling:
                    break
                dy = int(total_dy * (i + 1) / steps) - int(total_dy * i / steps)
                inp = INPUT()
                inp.type = 0
                inp.union.mi = MOUSEINPUT(0, dy, 0, 0x0001, 0, 0)
                arr = (INPUT * 1)(inp)
                ctypes.windll.user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))
                time.sleep(step_delay)

            going_up = not going_up

    # ----------------------------------------------------------- Bar Game
    def toggle_bar_game(self, force=False):
        if not force and not self._roblox_focused():
            return
        if self.bar_game:
            self.bar_game = False
            self.bar_shaping = False
        else:
            self.active = False
            self.jiggling = False
            self.autoclicker = False
            self.bar_game = True
            if self.auto_phase:
                self.phase_idx = 1
        self.root.after(0, self._refresh_gui)
        print(f"[BAR GAME] {'ON' if self.bar_game else 'OFF'}")

    def _bar_game_loop(self):
        """Auto-play the yellow bar minigame: hold click to rise, release to fall."""
        sct = mss.mss()
        clicking = False

        # Yellow/olive-gold target zone HSV (dark muted gold bar)
        bar_yellow_lo = np.array([18, 25, 30])
        bar_yellow_hi = np.array([50, 255, 200])

        # Pre-compute the capture region (right quarter, top 80%)
        crop_region = None
        # Offset from crop origin to monitor origin
        crop_ox = 0
        crop_oy = 0

        white_lo = np.array([0, 0, 170])
        white_hi = np.array([180, 60, 255])
        yellow_gone_since = 0
        last_shape_click = 0

        while self.running:
            if not self.bar_game or not self._roblox_focused():
                if clicking:
                    self._send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                crop_region = None
                yellow_gone_since = 0
                self.root.after(0, self._hide_bar_overlays)
                if self.bar_shaping:
                    self.bar_shaping = False
                    self.root.after(0, self._refresh_gui)
                time.sleep(0.05)
                continue

            mon = self.monitor_rect

            # Recompute capture region when monitor changes
            if crop_region is None or crop_region.get('_mon') != mon:
                crop_ox = mon['width'] * 3 // 4
                crop_h = int(mon['height'] * 0.85)
                crop_region = {
                    'left': mon['left'] + crop_ox,
                    'top': mon['top'],
                    'width': mon['width'] - crop_ox,
                    'height': crop_h,
                    '_mon': mon,
                }
                top_margin = int(crop_h * 0.10)

            # Grab and downscale for speed
            frame = np.array(sct.grab(crop_region))[:, :, :3]
            frame = cv2.resize(frame, None, fx=0.5, fy=0.5,
                               interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Find yellow target zone
            yellow_mask = cv2.inRange(hsv, bar_yellow_lo, bar_yellow_hi)
            yellow_coords = np.where(yellow_mask > 0)
            yellow_ys = yellow_coords[0]
            yellow_xs = yellow_coords[1]

            # Already in shaping -> stay there, skip bar game logic
            if self.bar_shaping:
                if clicking:
                    self._send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                self.root.after(0, self._hide_bar_overlays)
                now = time.time()
                if now - last_shape_click >= 0.15:
                    jx = random.randint(-15, 15)
                    jy = random.randint(-15, 15)
                    cx = mon['left'] + int(mon['width'] * 0.6) + jx
                    cy = mon['top'] + int(mon['height'] * 0.5) + jy
                    abs_x = int((cx - self._virt_left) * 65535 / (self._virt_w - 1))
                    abs_y = int((cy - self._virt_top) * 65535 / (self._virt_h - 1))
                    self._send_mouse(0x8000 | 0x4000 | 0x0001 | 0x0002, abs_x, abs_y)
                    time.sleep(0.03)
                    self._send_mouse(0x8000 | 0x4000 | 0x0001 | 0x0004, abs_x, abs_y)
                    last_shape_click = now
                continue

            if len(yellow_ys) < 20:
                # No yellow bar -> start/continue 1s grace period
                if clicking:
                    self._send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                self.root.after(0, self._hide_bar_overlays)
                if yellow_gone_since == 0:
                    yellow_gone_since = time.time()
                elif time.time() - yellow_gone_since >= 1.0:
                    # Gone for 1s -> transition to Shaping permanently
                    self.bar_shaping = True
                    last_shape_click = 0
                    self.root.after(0, self._refresh_gui)
                continue

            # Yellow bar visible -> reset grace timer
            yellow_gone_since = 0

            # Yellow bar bounds — use percentiles to ignore stray pixels
            y_min, y_max = int(np.percentile(yellow_ys, 5)), int(np.percentile(yellow_ys, 95))
            x_min, x_max = int(np.percentile(yellow_xs, 5)), int(np.percentile(yellow_xs, 95))
            yellow_cy = y_min + int((y_max - y_min) * 0.625)
            bar_width = x_max - x_min

            # Find white slit
            white_mask = cv2.inRange(hsv, white_lo, white_hi)
            white_mask[:top_margin, :] = 0

            white_ys = np.where(white_mask > 0)[0]
            white_count = len(white_ys)
            white_cy = int(np.median(white_ys)) if white_count > 5 else None
            print(f"[BAR] slit={white_cy} bar={yellow_cy} ({y_min}-{y_max}) "
                  f"wpx={white_count} click={clicking}")

            # Convert crop-relative coords to screen coords (scale back up from 0.5x)
            bar_scr_x = mon['left'] + crop_ox + x_min * 2
            bar_scr_y = mon['top'] + yellow_cy * 2
            bar_scr_w = max(bar_width * 2, 20)
            slit_scr_y = (mon['top'] + white_cy * 2) if white_cy is not None else None
            col_l_scr = mon['left'] + crop_ox
            col_r_scr = mon['left'] + mon['width']
            bot_scr = mon['top'] + crop_region['height']

            self.root.after(0, lambda bx=bar_scr_x, by=bar_scr_y,
                            sy=slit_scr_y, bw=bar_scr_w,
                            cl=col_l_scr, cr=col_r_scr, bs=bot_scr:
                self._update_bar_overlays(bx, by, sy, bw, cl, cr, bs))

            if white_cy is None:
                continue

            abs_x, abs_y, _, _ = self._get_abs_coords()

            # Proportional deadband based on bar height
            bar_half = max((y_max - y_min) // 2, 1)
            deadband = max(5, bar_half // 4)

            if white_cy > yellow_cy + deadband:  # slit below target -> click to rise
                if not clicking:
                    self._send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
                    clicking = True
            elif white_cy < yellow_cy - deadband:  # slit above target -> release to fall
                if clicking:
                    self._send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)
                    clicking = False

    # ---------------------------------------------------- Auto-Phase / GO
    def toggle_auto_phase(self, force=False):
        if not self.forge_enabled:
            return
        if not force and not self._roblox_focused():
            return
        if self.auto_phase:
            self.auto_phase = False
            print("[PHASE] Auto-phase OFF")
        else:
            self.auto_phase = True
            self.phase_idx = -1
            # Start idle — first GO will trigger jiggle
            self.active = False
            self.bar_game = False
            self.debug = False
            self.jiggling = False
            print("[PHASE] Auto-phase ON -> waiting for GO")
        self.root.after(0, self._refresh_gui)

    def _advance_phase(self):
        """Move to the next phase (i -> o -> p). Stops at P and keeps it active."""
        phases = ['jiggle', 'bar_game', 'circle']
        self.phase_idx += 1
        if self.phase_idx >= len(phases):
            self.root.after(0, self._refresh_gui)
            return

        phase = phases[self.phase_idx]

        # Deactivate all, then activate the right one
        self.active = False
        self.jiggling = False
        self.bar_game = False

        if phase == 'jiggle':
            self.jiggling = True
        elif phase == 'bar_game':
            self.bar_game = True
        elif phase == 'circle':
            self.active = True
            # Final phase — turn off auto-phase, keep P running
            self.auto_phase = False
            print("[PHASE] -> circle (auto-phase done, P stays active)")

        print(f"[PHASE] -> {phase}")
        self.root.after(0, self._refresh_gui)

    def _go_detector_loop(self):
        """Watch for the large green GO text and advance phase."""
        sct = mss.mss()
        cooldown_until = 0

        # GO text is large, bright, saturated green in the center of screen
        go_green_lo = np.array([35, 80, 80])
        go_green_hi = np.array([85, 255, 255])

        while self.running:
            if not self.auto_phase or not self._roblox_focused():
                time.sleep(0.2)
                continue

            if time.time() < cooldown_until:
                time.sleep(0.1)
                continue

            mon = self.monitor_rect
            shot = sct.grab(mon)
            frame = np.array(shot)[:, :, :3]
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # Check center 40% of screen for massive green blob
            h, w = frame.shape[:2]
            cx1, cx2 = int(w * 0.3), int(w * 0.7)
            cy1, cy2 = int(h * 0.3), int(h * 0.7)
            center_hsv = hsv[cy1:cy2, cx1:cx2]

            go_mask = cv2.inRange(center_hsv, go_green_lo, go_green_hi)
            green_count = int(np.count_nonzero(go_mask))

            if green_count > 5000:
                print(f"[GO] Detected ({green_count} green px) -> advancing")
                self._advance_phase()
                cooldown_until = time.time() + 3.0

            time.sleep(0.15)

    # ------------------------------------------------------------ Monitor
    def _apply_monitor(self):
        mon = self.all_monitors[self.monitor_idx]
        self.monitor_rect = mon
        self.monitor_res = f"{mon['width']}x{mon['height']}"
        # Update jiggle bounds for new monitor
        self.jiggle_top = int(mon['height'] * 0.20)
        self.jiggle_bottom = int(mon['height'] * 0.80)
        print(f"[MONITOR] #{self.monitor_idx + 1} — {mon}")

    def _cycle_monitor(self, delta):
        self.monitor_idx = (self.monitor_idx + delta) % len(self.all_monitors)
        self._apply_monitor()
        self.root.after(0, self._refresh_monitor_label)

    def _refresh_monitor_label(self):
        n = self.monitor_idx + 1
        total = len(self.all_monitors)
        self.mon_lbl.config(text=f"Monitor {n}/{total}  ({self.monitor_res})")

    # ------------------------------------------------------------------ GUI
    def _build_gui(self):
        BG = '#0d1117'
        BG2 = '#161b22'
        BORDER = '#21262d'
        DIM = '#484f58'

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("350x530+10+10")
        self.root.attributes('-topmost', True)
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        self.root.after(50, self._poll_middle_click)

        # ---- Dotted background pattern ----
        W, H = 350, 530
        DOT_SPACING = 18
        DOT_COLOR = '#1a1f27'
        self._bg_img = tk.PhotoImage(width=W, height=H)
        self._bg_img.put(BG, to=(0, 0, W, H))
        for y in range(0, H, DOT_SPACING):
            for x in range(0, W, DOT_SPACING):
                self._bg_img.put(DOT_COLOR, to=(x, y, x + 2, y + 2))
        tk.Label(self.root, image=self._bg_img, bd=0
                 ).place(x=0, y=0, relwidth=1, relheight=1)

        # ---- Custom title bar ----
        titlebar = tk.Frame(self.root, bg=BG, height=30)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        title_lbl = tk.Label(
            titlebar, text=f"LENK.TOOLS v{VERSION}",
            font=("Consolas", 9, "bold"), fg=DIM, bg=BG)
        title_lbl.pack(side=tk.LEFT, padx=10)

        # Close button
        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: self._quit())
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg='#ff5555', bg='#1a0000'))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=DIM, bg=BG))

        # Minimize button
        min_btn = tk.Label(
            titlebar, text='\u2500', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        min_btn.pack(side=tk.RIGHT, fill='y')
        min_btn.bind('<Button-1>', lambda e: self._minimize())
        min_btn.bind('<Enter>', lambda e: min_btn.config(fg='#c9d1d9', bg='#161b22'))
        min_btn.bind('<Leave>', lambda e: min_btn.config(fg=DIM, bg=BG))

        # Update button (beside title)
        self._update_btn = tk.Label(
            titlebar, text='\u21BB', font=('Segoe UI', 11),
            fg=DIM, bg=BG, padx=4, cursor='hand2')
        self._update_btn.pack(side=tk.LEFT)
        self._update_btn.bind('<Button-1>', lambda e: self._run_in_app_update())
        self._update_btn.bind('<Enter>',
            lambda e: self._update_btn.config(fg='#58a6ff', bg='#161b22'))
        self._update_btn.bind('<Leave>',
            lambda e: self._update_btn.config(
                fg=self._update_btn._rest_fg if hasattr(self._update_btn, '_rest_fg') else DIM,
                bg=BG))
        self._update_btn._rest_fg = DIM

        # Dragging
        def _start_drag(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def _on_drag(event):
            x = self.root.winfo_x() + event.x - self._drag_x
            y = self.root.winfo_y() + event.y - self._drag_y
            self.root.geometry(f"+{x}+{y}")

        for w in (titlebar, title_lbl):
            w.bind('<Button-1>', _start_drag)
            w.bind('<B1-Motion>', _on_drag)

        # ---- Header bar ----
        header = tk.Frame(self.root, bg=BG2)
        header.pack(fill='x')

        self.focus_lbl = tk.Label(
            header, text="\u25CF  ROBLOX: --",
            font=("Consolas", 10, "bold"),
            fg="#888888", bg=BG2
        )
        self.focus_lbl.pack(pady=(6, 0))

        self.game_lbl = tk.Label(
            header, text="\u25CB  Game: --",
            font=("Consolas", 9),
            fg="#888888", bg=BG2
        )
        self.game_lbl.pack(pady=(0, 5))
        self._last_place_id = None
        self._last_game_name = None

        # ---- Monitor selector ----
        mon_frame = tk.Frame(self.root, bg=BG)
        mon_frame.pack(pady=(8, 0))

        tk.Button(
            mon_frame, text="\u25C0", font=("Segoe UI", 8),
            fg="#8b949e", bg=BORDER, activebackground='#30363d',
            width=2, bd=0, relief='flat',
            command=lambda: self._cycle_monitor(-1)
        ).pack(side=tk.LEFT, padx=2)

        n = self.monitor_idx + 1
        total = len(self.all_monitors)
        self.mon_lbl = tk.Label(
            mon_frame, text=f"Monitor {n}/{total}  ({self.monitor_res})",
            font=("Consolas", 9), fg="#58a6ff", bg=BG
        )
        self.mon_lbl.pack(side=tk.LEFT, padx=6)

        tk.Button(
            mon_frame, text="\u25B6", font=("Segoe UI", 8),
            fg="#8b949e", bg=BORDER, activebackground='#30363d',
            width=2, bd=0, relief='flat',
            command=lambda: self._cycle_monitor(1)
        ).pack(side=tk.LEFT, padx=2)

        # ---- Separator ----
        tk.Frame(self.root, bg=BORDER, height=1).pack(
            fill='x', padx=16, pady=(10, 0))

        # ---- Pipeline: I -> O -> (Shaping) -> P ----
        pipe_w, pipe_h = 340, 82
        self.pipe_canvas = tk.Canvas(
            self.root, width=pipe_w, height=pipe_h,
            bg=BG, highlightthickness=0
        )
        self.pipe_canvas.pack(pady=(6, 0))

        cy = 24          # vertical center of circles
        r = 18           # circle radius
        positions = [38, 118, 208, 298]
        icons = ['\u2195', '\u2261', '\u25C8', '\u25CE']   # ↕  ≡  ◈  ◎
        labels = ['Smelting', 'Casting', 'Shaping', 'Welding']
        keys = ['I', 'O', '', 'P']

        self._pipe_lines = []
        self._pipe_circles = []
        self._pipe_icons = []
        self._pipe_labels = []
        self._pipe_keys = []

        # Connecting lines (drawn first so circles sit on top)
        for i in range(len(positions) - 1):
            line = self.pipe_canvas.create_line(
                positions[i] + r + 3, cy,
                positions[i + 1] - r - 3, cy,
                width=3, fill=BORDER, capstyle='round'
            )
            self._pipe_lines.append(line)

        # Nodes
        for i, (x, icon, label, key) in enumerate(
                zip(positions, icons, labels, keys)):
            # Outer glow ring (invisible until active)
            glow = self.pipe_canvas.create_oval(
                x - r - 3, cy - r - 3, x + r + 3, cy + r + 3,
                fill='', outline='', width=0
            )
            circle = self.pipe_canvas.create_oval(
                x - r, cy - r, x + r, cy + r,
                fill=BG2, outline='#30363d', width=2
            )
            icon_id = self.pipe_canvas.create_text(
                x, cy, text=icon,
                font=('Segoe UI', 14, 'bold'), fill=DIM
            )
            label_id = self.pipe_canvas.create_text(
                x, cy + r + 12, text=label,
                font=('Consolas', 9), fill=DIM
            )
            key_id = self.pipe_canvas.create_text(
                x, cy + r + 25, text=f'[{key}]',
                font=('Consolas', 8, 'bold'), fill='#30363d'
            )
            self._pipe_circles.append((glow, circle))
            self._pipe_icons.append(icon_id)
            self._pipe_labels.append(label_id)
            self._pipe_keys.append(key_id)

        # Make pipeline nodes clickable
        # Map pipeline indices to hotkey names (index 2 = Shaping has no hotkey)
        _pipe_hotkey_names = {0: 'jiggle', 1: 'bar_game', 3: 'circle'}
        for i in range(4):
            tag = f'node_{i}'
            glow_id, circle_id = self._pipe_circles[i]
            for item_id in [glow_id, circle_id, self._pipe_icons[i],
                            self._pipe_labels[i]]:
                self.pipe_canvas.addtag_withtag(tag, item_id)
            # Key text: rebindable keys get their own tag, others join the node
            if i in _pipe_hotkey_names:
                key_tag = f'key_{i}'
                self.pipe_canvas.addtag_withtag(key_tag, self._pipe_keys[i])
                self.pipe_canvas.tag_bind(
                    key_tag, '<Button-1>',
                    lambda e, n=_pipe_hotkey_names[i]: self._start_key_rebind(n))
                self.pipe_canvas.tag_bind(
                    key_tag, '<Enter>',
                    lambda e: self.pipe_canvas.config(cursor='hand2'))
                self.pipe_canvas.tag_bind(
                    key_tag, '<Leave>',
                    lambda e: self.pipe_canvas.config(cursor=''))
                self._hotkey_ui[_pipe_hotkey_names[i]] = {
                    'type': 'canvas', 'item_id': self._pipe_keys[i]}
            else:
                self.pipe_canvas.addtag_withtag(tag, self._pipe_keys[i])
            self.pipe_canvas.tag_bind(
                tag, '<Button-1>',
                lambda e, idx=i: self._on_node_click(idx))
            self.pipe_canvas.tag_bind(
                tag, '<Enter>',
                lambda e: self.pipe_canvas.config(cursor='hand2'))
            self.pipe_canvas.tag_bind(
                tag, '<Leave>',
                lambda e: self.pipe_canvas.config(cursor=''))

        # "FORGE OFF" overlay (hidden by default)
        self._forge_off_overlay = self.pipe_canvas.create_text(
            pipe_w // 2, cy, text='FORGE OFF',
            font=('Consolas', 18, 'bold'), fill='#ff5555',
            state='hidden'
        )

        # ---- Shared helper for control rows ----
        def _ctrl_row(parent, text, key_text, command=None):
            """Create a control row: dot + label + right-aligned key hint."""
            row = tk.Frame(parent, bg=BG)
            row.pack(fill='x', pady=2)
            dot = tk.Label(row, text='\u25CF', font=('Segoe UI', 8),
                           fg='#ff5555', bg=BG)
            dot.pack(side=tk.LEFT, padx=(0, 6))
            lbl = tk.Label(row, text=text, font=('Consolas', 11, 'bold'),
                           fg=DIM, bg=BG, anchor='w')
            lbl.pack(side=tk.LEFT, fill='x', expand=True)
            hint = tk.Label(row, text=key_text, font=('Consolas', 9),
                            fg='#30363d', bg=BG, anchor='e')
            hint.pack(side=tk.RIGHT)
            if command:
                for widget in (dot, lbl, row):
                    widget.bind('<Button-1>', lambda e, cmd=command: cmd())
                    widget.config(cursor='hand2')
            return dot, lbl, hint

        # ---- Auto-Phase (belongs with forge pipeline) ----
        phase_frame = tk.Frame(self.root, bg=BG)
        phase_frame.pack(fill='x', padx=20, pady=(2, 0))
        self._phase_dot, self.phase_lbl, self._phase_hint = _ctrl_row(
            phase_frame, 'Auto-Phase: OFF', '[U]',
            lambda: self.toggle_auto_phase(force=True))

        # ---- Separator ----
        tk.Frame(self.root, bg=BORDER, height=1).pack(
            fill='x', padx=16, pady=(6, 0))

        # ---- Extra controls ----
        ctrl = tk.Frame(self.root, bg=BG)
        ctrl.pack(pady=(8, 0), fill='x', padx=20)

        self._autoclick_dot, self.autoclick_lbl, self._autoclick_hint = _ctrl_row(
            ctrl, 'Autoclick: OFF', '[F5]',
            lambda: self.toggle_autoclicker(force=True))
        self._holdleft_dot, self.holdleft_lbl, self._holdleft_hint = _ctrl_row(
            ctrl, 'Hold Left: OFF', '[F6]',
            lambda: self.toggle_holding_left(force=True))
        self._sprint_dot, self.sprint_lbl, self._sprint_hint = _ctrl_row(
            ctrl, 'Sprint: OFF', '[CapsLk]',
            lambda: self.toggle_sprint(force=True))

        # Make control-row hint labels clickable for rebinding
        for hotkey_name, hint_widget in [('auto_phase', self._phase_hint),
                                          ('autoclicker', self._autoclick_hint),
                                          ('hold_left', self._holdleft_hint),
                                          ('sprint', self._sprint_hint)]:
            hint_widget.config(cursor='hand2')
            hint_widget.bind('<Button-1>',
                             lambda e, n=hotkey_name: self._start_key_rebind(n))
            self._hotkey_ui[hotkey_name] = {'type': 'label', 'widget': hint_widget}

        # ---- Auto Sell sub-section ----
        as_frame = tk.Frame(self.root, bg=BG)
        as_frame.pack(fill='x', padx=20, pady=(6, 0))

        as_toggle_row = tk.Frame(as_frame, bg=BG)
        as_toggle_row.pack(fill='x', pady=2)
        self._as_dot = tk.Label(as_toggle_row, text='\u25CF',
                                font=('Segoe UI', 8), fg='#ff5555', bg=BG)
        self._as_dot.pack(side=tk.LEFT, padx=(0, 6))
        self.as_lbl = tk.Label(as_toggle_row, text='Auto Sell: OFF',
                               font=('Consolas', 10, 'bold'), fg=DIM, bg=BG,
                               anchor='w')
        self.as_lbl.pack(side=tk.LEFT, fill='x', expand=True)

        tk.Button(as_toggle_row, text='Setup', font=('Consolas', 9, 'bold'),
                  fg='#58a6ff', bg=BG2, activebackground='#30363d',
                  activeforeground='#58a6ff', bd=0, relief='flat',
                  cursor='hand2',
                  command=lambda: Thread(target=self._auto_sell_setup,
                                         daemon=True).start()
                  ).pack(side=tk.RIGHT, padx=(4, 0))

        camlock_color = '#50fa7b' if self.auto_sell_camlock else DIM
        self._as_camlock_btn = tk.Button(
            as_toggle_row, text='Camlock', font=('Consolas', 9, 'bold'),
            fg=camlock_color, bg=BG2, activebackground='#30363d',
            activeforeground=camlock_color, bd=0, relief='flat',
            cursor='hand2', command=self._toggle_auto_sell_camlock)
        self._as_camlock_btn.pack(side=tk.RIGHT, padx=(4, 0))

        for w in (self._as_dot, self.as_lbl, as_toggle_row):
            w.bind('<Button-1>', lambda e: self._toggle_auto_sell())
            w.config(cursor='hand2')

        # Interval slider row
        as_slider_row = tk.Frame(as_frame, bg=BG)
        as_slider_row.pack(fill='x', pady=(2, 0), padx=(14, 0))

        self._as_interval_lbl = tk.Label(
            as_slider_row, text=self._fmt_interval(self.auto_sell_interval),
            font=('Consolas', 9), fg='#8b949e', bg=BG, width=7, anchor='w')
        self._as_interval_lbl.pack(side=tk.LEFT)

        self._as_slider = tk.Scale(
            as_slider_row, from_=30, to=1800, orient=tk.HORIZONTAL,
            bg=BG, fg='#8b949e', troughcolor=BG2, highlightthickness=0,
            bd=0, sliderrelief='flat', showvalue=False,
            command=self._on_auto_sell_slider)
        self._as_slider.set(self.auto_sell_interval)
        self._as_slider.pack(side=tk.LEFT, fill='x', expand=True)

        # ---- Periodic Attack sub-section ----
        pa_frame = tk.Frame(self.root, bg=BG)
        pa_frame.pack(fill='x', padx=20, pady=(6, 0))

        # Toggle row
        pa_toggle_row = tk.Frame(pa_frame, bg=BG)
        pa_toggle_row.pack(fill='x', pady=2)
        self._pa_dot = tk.Label(pa_toggle_row, text='\u25CF',
                                font=('Segoe UI', 8), fg='#ff5555', bg=BG)
        self._pa_dot.pack(side=tk.LEFT, padx=(0, 6))
        self.pa_lbl = tk.Label(pa_toggle_row, text='Periodic Attack: OFF',
                               font=('Consolas', 10, 'bold'), fg=DIM, bg=BG,
                               anchor='w')
        self.pa_lbl.pack(side=tk.LEFT, fill='x', expand=True)
        for w in (self._pa_dot, self.pa_lbl, pa_toggle_row):
            w.bind('<Button-1>', lambda e: self.toggle_periodic_attack())
            w.config(cursor='hand2')

        # Two-column layout: sword | pickaxe
        pa_cols = tk.Frame(pa_frame, bg=BG)
        pa_cols.pack(fill='x', pady=(2, 0), padx=(14, 0))

        # --- Sword column (key1) ---
        sword_col = tk.Frame(pa_cols, bg=BG)
        sword_col.pack(side=tk.LEFT, expand=True, fill='x')

        sword_top = tk.Frame(sword_col, bg=BG)
        sword_top.pack()
        tk.Label(sword_top, text='\u2694', font=('Segoe UI', 16),
                 fg='#ff5555', bg=BG).pack(side=tk.LEFT)
        self._pa_time1_var = tk.StringVar(value='1.0')
        pa_time1_entry = tk.Entry(
            sword_top, textvariable=self._pa_time1_var,
            width=4, font=('Consolas', 10, 'bold'),
            fg='#58a6ff', bg=BG2, insertbackground='#58a6ff',
            bd=1, relief='flat', justify='center')
        pa_time1_entry.pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(sword_top, text='s', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)

        self._pa_key1_var = tk.StringVar(value='2')
        keycap1_outer = tk.Frame(sword_col, bg='#484f58')
        keycap1_outer.pack(pady=(4, 0), anchor='w', padx=(4, 0))
        keycap1_inner = tk.Frame(keycap1_outer, bg='#30363d')
        keycap1_inner.pack(padx=1, pady=(1, 2))
        pa_key1_entry = tk.Entry(
            keycap1_inner, textvariable=self._pa_key1_var,
            width=2, font=('Consolas', 11, 'bold'),
            fg='#c9d1d9', bg='#161b22', insertbackground='#58a6ff',
            bd=0, relief='flat', justify='center')
        pa_key1_entry.pack(padx=3, pady=2)

        # --- Pickaxe column (key2) ---
        pick_col = tk.Frame(pa_cols, bg=BG)
        pick_col.pack(side=tk.LEFT, expand=True, fill='x')

        pick_top = tk.Frame(pick_col, bg=BG)
        pick_top.pack()
        tk.Label(pick_top, text='\u26CF', font=('Segoe UI', 16),
                 fg='#50fa7b', bg=BG).pack(side=tk.LEFT)
        self._pa_time2_var = tk.StringVar(value='2.0')
        pa_time2_entry = tk.Entry(
            pick_top, textvariable=self._pa_time2_var,
            width=4, font=('Consolas', 10, 'bold'),
            fg='#58a6ff', bg=BG2, insertbackground='#58a6ff',
            bd=1, relief='flat', justify='center')
        pa_time2_entry.pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(pick_top, text='s', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)

        self._pa_key2_var = tk.StringVar(value='1')
        keycap2_outer = tk.Frame(pick_col, bg='#484f58')
        keycap2_outer.pack(pady=(4, 0), anchor='w', padx=(4, 0))
        keycap2_inner = tk.Frame(keycap2_outer, bg='#30363d')
        keycap2_inner.pack(padx=1, pady=(1, 2))
        pa_key2_entry = tk.Entry(
            keycap2_inner, textvariable=self._pa_key2_var,
            width=2, font=('Consolas', 11, 'bold'),
            fg='#c9d1d9', bg='#161b22', insertbackground='#58a6ff',
            bd=0, relief='flat', justify='center')
        pa_key2_entry.pack(padx=3, pady=2)

        # Sync key entries to state
        def _on_key1_change(*_):
            val = self._pa_key1_var.get()
            if val:
                self.periodic_key1 = val[-1]
                if len(val) > 1:
                    self._pa_key1_var.set(val[-1])

        def _on_key2_change(*_):
            val = self._pa_key2_var.get()
            if val:
                self.periodic_key2 = val[-1]
                if len(val) > 1:
                    self._pa_key2_var.set(val[-1])

        self._pa_key1_var.trace_add('write', _on_key1_change)
        self._pa_key2_var.trace_add('write', _on_key2_change)

        # Sync time entries to periodic state
        def _sync_pa_times(*_):
            try:
                sword_t = float(self._pa_time1_var.get())
            except ValueError:
                return
            try:
                pick_t = float(self._pa_time2_var.get())
            except ValueError:
                return
            if sword_t < 0.1 or pick_t < 0.1:
                return
            self.periodic_delay2 = sword_t
            self.periodic_interval1 = sword_t + pick_t

        self._pa_time1_var.trace_add('write', _sync_pa_times)
        self._pa_time2_var.trace_add('write', _sync_pa_times)

        # ---- Bottom buttons ----
        bottom_frame = tk.Frame(self.root, bg=BG)
        bottom_frame.pack(side=tk.BOTTOM, fill='x', pady=(0, 8))

        self.hotkey_btn = tk.Button(
            bottom_frame, text='Hotkeys: ON', font=('Consolas', 10, 'bold'),
            fg='#50fa7b', bg=BORDER, activebackground='#30363d',
            activeforeground='#50fa7b', bd=0, relief='flat',
            padx=12, pady=4,
            command=self._toggle_hotkeys
        )
        self.hotkey_btn.pack(side=tk.LEFT, expand=True, padx=(8, 4))

        self.macro_btn = tk.Button(
            bottom_frame, text='\u2630 Macro Editor', font=('Consolas', 10, 'bold'),
            fg='#bd93f9', bg=BORDER, activebackground='#30363d',
            activeforeground='#bd93f9', bd=0, relief='flat',
            padx=12, pady=4,
            command=self._toggle_macro_panel
        )
        self.macro_btn.pack(side=tk.LEFT, expand=True, padx=(4, 4))

        self.wiki_btn = tk.Button(
            bottom_frame, text='\U0001f4d6 Wiki', font=('Consolas', 10, 'bold'),
            fg='#58a6ff', bg=BORDER, activebackground='#30363d',
            activeforeground='#58a6ff', bd=0, relief='flat',
            padx=12, pady=4, command=self._toggle_wiki_panel)
        self.wiki_btn.pack(side=tk.LEFT, expand=True, padx=(4, 4))

        self.debug_btn = tk.Button(
            bottom_frame, text='\U0001f41b', font=('Segoe UI Emoji', 10),
            fg='#484f58', bg=BORDER, activebackground='#30363d',
            activeforeground='#ff5555', bd=0, relief='flat',
            padx=6, pady=4,
            command=self.toggle_debug
        )
        self.debug_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # On-screen overlay markers for bar game (click-through)
        self._bar_ov = self._make_arrow_overlay('BAR')
        self._slit_ov = self._make_arrow_overlay('SLIT')

        # Red lines showing search region boundaries
        for attr in ('_col_left_ov', '_col_right_ov', '_bot_ov'):
            ov = tk.Toplevel(self.root)
            ov.overrideredirect(True)
            ov.attributes('-topmost', True)
            ov.configure(bg='#ff2222')
            ov.geometry("2x100+0+0")
            ov.withdraw()
            setattr(self, attr, ov)

        # Targeting ring overlay for detect mode
        ring_d = 85
        self._ring_size = ring_d
        self._ring_ov = tk.Toplevel(self.root)
        self._ring_ov.overrideredirect(True)
        self._ring_ov.attributes('-topmost', True)
        self._ring_ov.attributes('-transparentcolor', '#000000')
        self._ring_ov.configure(bg='#000000')
        self._ring_ov.geometry(f"{ring_d}x{ring_d}+0+0")
        self._ring_cvs = tk.Canvas(
            self._ring_ov, width=ring_d, height=ring_d,
            bg='#000000', highlightthickness=0
        )
        self._ring_cvs.pack()
        pad = 3
        self._ring_id = self._ring_cvs.create_oval(
            pad, pad, ring_d - pad, ring_d - pad,
            outline='#ff2222', width=3, fill='#000000'
        )
        self._ring_ov.withdraw()

        # Timer label overlay (bottom-right of ring)
        self._dtimer_ov = tk.Toplevel(self.root)
        self._dtimer_ov.overrideredirect(True)
        self._dtimer_ov.attributes('-topmost', True)
        self._dtimer_ov.attributes('-transparentcolor', '#000000')
        self._dtimer_ov.configure(bg='#000000')
        self._dtimer_ov.geometry("100x25+0+0")
        self._dtimer_lbl = tk.Label(
            self._dtimer_ov, text="",
            font=("Consolas", 12, "bold"),
            fg="#ff2222", bg='#000000'
        )
        self._dtimer_lbl.pack()
        self._dtimer_ov.withdraw()

        # Start periodic focus check
        self._update_focus_label()

    def _update_focus_label(self):
        if self._roblox_focused():
            self.focus_lbl.config(text="\u25CF  ROBLOX: Focused", fg="#50fa7b")
            self._auto_select_monitor()
        else:
            self.focus_lbl.config(text="\u25CF  ROBLOX: Not Focused", fg="#ff5555")
        self.root.after(500, self._update_focus_label)
        # Update game detection every cycle
        self._update_game_label()

    def _update_game_label(self):
        """Update the game name label from Roblox logs (runs in background to avoid blocking)."""
        def _detect():
            place_id, name = self._detect_roblox_game()
            if place_id:
                self._last_place_id = place_id
                if name:
                    self._last_game_name = name
                display = name or f"Place {place_id}"
                if len(display) > 30:
                    display = display[:27] + "..."
                self.root.after(0, lambda: self.game_lbl.config(
                    text=f"\u25CB  Game: {display}", fg="#58a6ff"))
            else:
                self.root.after(0, lambda: self.game_lbl.config(
                    text="\u25CB  Game: --", fg="#888888"))
        Thread(target=_detect, daemon=True).start()

    def _auto_select_monitor(self):
        """Switch to the monitor Roblox is currently on."""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            hmon = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

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
            r_w, r_h = rc.right - rc.left, rc.bottom - rc.top

            for i, mon in enumerate(self.all_monitors):
                if (mon['left'] == r_left and mon['top'] == r_top
                        and mon['width'] == r_w and mon['height'] == r_h):
                    if i != self.monitor_idx:
                        self.monitor_idx = i
                        self._apply_monitor()
                        self._refresh_monitor_label()
                    break
        except Exception:
            pass

    def toggle(self, force=False):
        if not force and not self._roblox_focused():
            return
        if self.active:
            self.active = False
        else:
            self.debug = False
            self.jiggling = False
            self.bar_game = False
            self.autoclicker = False
            self.active = True
            if self.auto_phase:
                self.phase_idx = 2
                self.auto_phase = False
        self.root.after(0, self._refresh_gui)

    def _refresh_gui(self):
        # ---- Pipeline nodes ----
        # Smelting(I), Casting(O), Shaping(auto), Welding(P)
        states = [
            self.jiggling,
            self.bar_game and not self.bar_shaping,
            self.bar_shaping,
            self.active,
        ]

        if not self.forge_enabled:
            # Forge globally disabled — dim everything with red tint
            for i in range(4):
                glow, circle = self._pipe_circles[i]
                self.pipe_canvas.itemconfig(glow, outline='', width=0)
                self.pipe_canvas.itemconfig(circle, fill='#1a0a0a', outline='#3d1f1f')
                self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#3d1f1f')
                self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#3d1f1f')
                self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#2a1515')
            self.pipe_canvas.itemconfig(self._forge_off_overlay, state='normal')
        else:
            self.pipe_canvas.itemconfig(self._forge_off_overlay, state='hidden')
            for i, is_on in enumerate(states):
                glow, circle = self._pipe_circles[i]
                if is_on and self.auto_phase:
                    # Active via auto-phase -> yellow
                    self.pipe_canvas.itemconfig(glow, outline='#9e6a03', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#2d1b00', outline='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#9e6a03')
                elif is_on and i == 2:
                    # Shaping -> cyan
                    self.pipe_canvas.itemconfig(glow, outline='#1f6feb', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#0d1b3d', outline='#58a6ff')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#58a6ff')
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#58a6ff')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#1f6feb')
                elif is_on:
                    # Manually active -> green
                    self.pipe_canvas.itemconfig(glow, outline='#238636', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#0d4429', outline='#50fa7b')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#50fa7b')
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#c9d1d9')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#238636')
                else:
                    # Inactive
                    self.pipe_canvas.itemconfig(glow, outline='', width=0)
                    self.pipe_canvas.itemconfig(circle, fill='#161b22', outline='#30363d')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#484f58')
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#484f58')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#30363d')

        # ---- Connecting lines ----
        for line in self._pipe_lines:
            if not self.forge_enabled:
                self.pipe_canvas.itemconfig(line, fill='#2a1515')
            elif self.auto_phase:
                self.pipe_canvas.itemconfig(line, fill='#f0c040')
            else:
                self.pipe_canvas.itemconfig(line, fill='#21262d')

        # ---- Controls ----
        if self.auto_phase:
            phases = ['Smelting', 'Casting', 'Welding']
            idx = self.phase_idx
            name = phases[idx] if 0 <= idx < len(phases) else 'Ready'
            self.phase_lbl.config(text=f'Phase: {name}', fg='#f0c040')
            self._phase_dot.config(fg='#f0c040')
        else:
            self.phase_lbl.config(text='Auto-Phase: OFF', fg='#484f58')
            self._phase_dot.config(fg='#ff5555')

        if self.autoclicker and self._auto_sell_executing:
            self.autoclick_lbl.config(text='Autoclick: PAUSED', fg='#f0c040')
            self._autoclick_dot.config(fg='#f0c040')
        elif self.autoclicker:
            self.autoclick_lbl.config(text='Autoclick: ON', fg='#50fa7b')
            self._autoclick_dot.config(fg='#50fa7b')
        else:
            self.autoclick_lbl.config(text='Autoclick: OFF', fg='#484f58')
            self._autoclick_dot.config(fg='#ff5555')

        if self.debug:
            self.debug_btn.config(fg='#50fa7b', activeforeground='#50fa7b')
        else:
            self.debug_btn.config(fg='#484f58', activeforeground='#ff5555')

        if self.holding_left:
            self.holdleft_lbl.config(text='Hold Left: ON', fg='#50fa7b')
            self._holdleft_dot.config(fg='#50fa7b')
        else:
            self.holdleft_lbl.config(text='Hold Left: OFF', fg='#484f58')
            self._holdleft_dot.config(fg='#ff5555')

        if self.sprint_enabled:
            self.sprint_lbl.config(text='Sprint: ON', fg='#50fa7b')
            self._sprint_dot.config(fg='#50fa7b')
        else:
            self.sprint_lbl.config(text='Sprint: OFF', fg='#484f58')
            self._sprint_dot.config(fg='#ff5555')

        if self.periodic_attack:
            self.pa_lbl.config(text='Periodic Attack: ON', fg='#bd93f9')
            self._pa_dot.config(fg='#bd93f9')
        else:
            self.pa_lbl.config(text='Periodic Attack: OFF', fg='#484f58')
            self._pa_dot.config(fg='#ff5555')

        if self.auto_sell_active:
            self.as_lbl.config(text='Auto Sell: ON', fg='#50fa7b')
            self._as_dot.config(fg='#50fa7b')
        else:
            self.as_lbl.config(text='Auto Sell: OFF', fg='#484f58')
            self._as_dot.config(fg='#ff5555')

        # ---- Mini mode labels ----
        self._refresh_mini()

    # ----------------------------------------------------------- Detection
    def _find_targets(self, hsv, lo, hi):
        """Return list of (cx, cy, area) for circular color-matched regions."""
        h_frame, w_frame = hsv.shape[:2]

        # Margins: ignore 20% of left/right edges, 10% of top/bottom
        margin_x = int(w_frame * 0.20)
        margin_y = int(h_frame * 0.10)

        mask = cv2.inRange(hsv, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        targets = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue

            # Bounding box aspect ratio — circles are roughly square
            x_r, y_r, w_r, h_r = cv2.boundingRect(c)
            if w_r == 0 or h_r == 0:
                continue
            aspect = max(w_r, h_r) / min(w_r, h_r)
            if aspect > 2.0:  # skip elongated shapes (logos, text, UI)
                continue

            # Enclosing circle fill — contour area vs enclosing circle area
            (cx, cy), radius = cv2.minEnclosingCircle(c)
            if radius < 5:
                continue
            circle_area = np.pi * radius * radius
            fill = area / circle_area
            if fill < 0.20:  # skip sparse/irregular shapes
                continue

            # Margin check — skip targets near screen edges
            if cx < margin_x or cx > w_frame - margin_x:
                continue
            if cy < margin_y or cy > h_frame - margin_y:
                continue

            targets.append((int(cx), int(cy), area))

        return targets

    # ---------------------------------------------------------- Main loop
    # States: SCAN -> TRACK -> READY -> COOLDOWN
    #   SCAN:     looking for a white ring to lock onto
    #   TRACK:    hovering on the white ring, waiting for green
    #   READY:    green detected, waiting for rings to fully align before clicking
    #   COOLDOWN: just clicked, wait before looking for the next target

    def _loop(self):
        sct = mss.mss()  # must create in the thread that uses it
        scale = self.scan_scale
        inv_scale = 1.0 / scale

        state = "SCAN"
        cooldown_end = 0
        green_seen_at = 0
        lost_frames = 0
        track_x, track_y = 0, 0
        track_start = 0
        ring_shown = False

        debug_was_on = False

        while self.running:
            # Debug mode — show what the bot sees
            if self.debug:
                debug_was_on = True
                state = "SCAN"
                mon = self.monitor_rect
                shot = sct.grab(mon)
                frame = np.array(shot)[:, :, :3]
                small = cv2.resize(frame, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA)
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

                green_mask = cv2.inRange(hsv, self.green_lo, self.green_hi)
                white_mask = cv2.inRange(hsv, self.white_lo, self.white_hi)

                # Bar game masks (yellow + white slit)
                bar_yellow_mask = cv2.inRange(hsv, np.array([18, 25, 30]),
                                              np.array([50, 255, 200]))
                # Slit mask: white via HSV (low saturation, high value)
                bar_white_mask = cv2.inRange(hsv, np.array([0, 0, 170]),
                                             np.array([180, 60, 255]))

                # Draw detected targets on the frame
                preview = small.copy()
                for cx, cy, a in self._find_targets(hsv, self.green_lo, self.green_hi):
                    cv2.circle(preview, (cx, cy), 10, (0, 255, 0), 2)
                    cv2.putText(preview, "GREEN", (cx-20, cy-15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                for cx, cy, a in self._find_targets(hsv, self.white_lo, self.white_hi):
                    cv2.circle(preview, (cx, cy), 10, (255, 255, 255), 2)
                    cv2.putText(preview, "WHITE", (cx-20, cy-15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                dbg_scale = (1.0 / 3.0) / scale  # shrink to 1/3 of original
                def _dbg_resize(img):
                    return cv2.resize(img, None, fx=dbg_scale, fy=dbg_scale,
                                      interpolation=cv2.INTER_AREA)
                try:
                    cv2.imshow("Preview", _dbg_resize(preview))
                    cv2.imshow("Green Mask", _dbg_resize(green_mask))
                    cv2.imshow("White Mask", _dbg_resize(white_mask))
                    cv2.imshow("Bar Yellow", _dbg_resize(bar_yellow_mask))
                    cv2.imshow("Bar White", _dbg_resize(bar_white_mask))
                    cv2.waitKey(1)
                except cv2.error:
                    pass
                time.sleep(0.03)
                continue

            # Clean up debug windows when debug turns off
            if debug_was_on:
                debug_was_on = False
                try:
                    cv2.destroyAllWindows()
                    cv2.waitKey(1)
                except cv2.error:
                    pass

            # Update monitor in case user changed it
            mon = self.monitor_rect
            green_delay = 0.02 * (mon['height'] / 1080)

            if not self.active or not self._roblox_focused():
                state = "SCAN"
                if ring_shown:
                    self.root.after(0, self._hide_ring)
                    ring_shown = False
                time.sleep(0.05)
                continue

            # Capture & downscale for speed
            shot = sct.grab(mon)
            frame = np.array(shot)[:, :, :3]  # drop alpha (BGRA -> BGR)
            small = cv2.resize(frame, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

            if state == "SCAN":
                # Only look for white rings — ignore any green (expanding
                # success animations from already-clicked circles)
                whites = self._find_targets(hsv, self.white_lo, self.white_hi)
                if whites:
                    whites.sort(key=lambda t: t[2], reverse=True)
                    sx, sy = whites[0][0], whites[0][1]
                    track_x = int(sx * inv_scale) + mon["left"]
                    track_y = int(sy * inv_scale) + mon["top"]
                    print(f"[SCAN] White found: scaled=({sx},{sy}) screen=({track_x},{track_y})")
                    self._move_to(track_x, track_y)
                    track_start = time.time()
                    state = "TRACK"
                    lost_frames = 0

            elif state == "TRACK":
                # Hovering on target — wait for green near our tracked position
                greens = self._find_targets(hsv, self.green_lo, self.green_hi)
                if greens:
                    print(f"[TRACK] {len(greens)} green candidate(s)")
                # Only accept green close to where we're tracking (within 150px)
                nearby = []
                for gx, gy, ga in greens:
                    rx = int(gx * inv_scale) + mon["left"]
                    ry = int(gy * inv_scale) + mon["top"]
                    dist = ((rx - track_x) ** 2 + (ry - track_y) ** 2) ** 0.5
                    print(f"  green at ({rx},{ry}) dist={dist:.0f}")
                    if dist < 150:
                        nearby.append((gx, gy, ga))
                if nearby:
                    # Green appeared near our target -> wait for alignment
                    green_seen_at = time.time()
                    state = "READY"
                else:
                    # Check if white ring is still visible (don't move cursor)
                    whites = self._find_targets(hsv, self.white_lo, self.white_hi)
                    if whites:
                        lost_frames = 0
                    else:
                        lost_frames += 1
                        if lost_frames > 15:
                            state = "SCAN"

            elif state == "READY":
                # Green is showing — wait for the rings to fully align
                if time.time() - green_seen_at >= green_delay:
                    self._click(track_x, track_y)
                    state = "COOLDOWN"
                    cooldown_end = time.time() + 0.4

            elif state == "COOLDOWN":
                if time.time() >= cooldown_end:
                    state = "SCAN"

            # Update targeting ring overlay
            if state == "TRACK":
                elapsed = time.time() - track_start
                self.root.after(0, lambda tx=track_x, ty=track_y, e=elapsed:
                    self._update_ring(tx, ty, f"{e:.1f}s"))
                ring_shown = True
            elif state == "READY":
                remaining = max(0, green_delay - (time.time() - green_seen_at))
                self.root.after(0, lambda tx=track_x, ty=track_y, r=remaining:
                    self._update_ring(tx, ty, f"{r*1000:.0f}ms", '#ffaa00'))
                ring_shown = True
            elif ring_shown:
                self.root.after(0, self._hide_ring)
                ring_shown = False

            time.sleep(0.003)  # ~300 fps cap

    # --------------------------------------------------------- Wiki Panel
    def _toggle_wiki_panel(self):
        """Open or close the wiki panel."""
        if self.wiki_panel_open and self.wiki_panel:
            try:
                self.wiki_panel.destroy()
            except Exception:
                pass
            self.wiki_panel_open = False
            self.wiki_panel = None
            return
        data = load_wiki_data()
        self.wiki_panel = WikiWindow(self.root, data)
        self.wiki_panel_open = True

        # Watch for panel close
        orig_close = self.wiki_panel._on_close

        def _wrapped_close():
            orig_close()
            self.wiki_panel_open = False
            self.wiki_panel = None

        self.wiki_panel._on_close = _wrapped_close

    def _radial_wiki_search(self):
        """Open the floating wiki search bar from the radial menu."""
        data = load_wiki_data()

        def _open_wiki(entry_name):
            if not self.wiki_panel_open or not self.wiki_panel:
                self.wiki_panel = WikiWindow(self.root, data)
                self.wiki_panel_open = True
                orig_close = self.wiki_panel._on_close

                def _wrapped_close():
                    orig_close()
                    self.wiki_panel_open = False
                    self.wiki_panel = None

                self.wiki_panel._on_close = _wrapped_close
            self.wiki_panel.navigate_to(entry_name)

        WikiSearchOverlay(self.root, data, _open_wiki)

    # --------------------------------------------------------- Macro Editor
    def _macro_save_path(self):
        """Return path to macros.json next to this script."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'macros.json')

    def _load_macros(self):
        """Load saved macros from disk."""
        path = self._macro_save_path()
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    self.macro_saved = json.load(f)
            except Exception:
                self.macro_saved = {}
        else:
            self.macro_saved = {}

    def _save_macros(self):
        """Write saved macros to disk."""
        try:
            with open(self._macro_save_path(), 'w') as f:
                json.dump(self.macro_saved, f, indent=2)
        except Exception as e:
            print(f"[MACRO] Save error: {e}")

    def _toggle_macro_panel(self):
        """Open or close the macro editor panel."""
        if self.macro_panel_open and self.macro_panel:
            try:
                self.macro_panel.destroy()
            except Exception:
                pass
            self.macro_panel_open = False
            self.macro_panel = None
            return
        self._load_macros()
        self._build_macro_panel()
        self.macro_panel_open = True

    def _build_macro_panel(self):
        """Build the macro editor Toplevel window."""
        BG = '#0d1117'
        BG2 = '#161b22'
        BORDER = '#21262d'
        DIM = '#484f58'
        ACCENT = '#58a6ff'
        GREEN = '#50fa7b'
        RED = '#ff5555'

        # Position to the right of main window
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()

        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.geometry(f"380x520+{root_x + root_w + 10}+{root_y}")
        panel.attributes('-topmost', True)
        panel.resizable(False, False)
        panel.configure(bg=BG)
        self.macro_panel = panel

        def on_close():
            if self.macro_recording:
                self._stop_recording()
            if self.macro_replaying:
                self._stop_replay()
            self.macro_panel_open = False
            self.macro_panel = None
            panel.destroy()

        # ---- Dotted background pattern ----
        MW, MH = 380, 520
        DOT_SPACING = 18
        DOT_COLOR = '#1a1f27'
        self._macro_bg_img = tk.PhotoImage(width=MW, height=MH)
        self._macro_bg_img.put(BG, to=(0, 0, MW, MH))
        for y in range(0, MH, DOT_SPACING):
            for x in range(0, MW, DOT_SPACING):
                self._macro_bg_img.put(DOT_COLOR, to=(x, y, x + 2, y + 2))
        tk.Label(panel, image=self._macro_bg_img, bd=0
                 ).place(x=0, y=0, relwidth=1, relheight=1)

        # ---- Custom title bar ----
        titlebar = tk.Frame(panel, bg=BG, height=30)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        title_lbl = tk.Label(
            titlebar, text="MACRO EDITOR",
            font=("Consolas", 9, "bold"), fg=DIM, bg=BG)
        title_lbl.pack(side=tk.LEFT, padx=10)

        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: on_close())
        close_btn.bind('<Enter>', lambda e: close_btn.config(fg='#ff5555', bg='#1a0000'))
        close_btn.bind('<Leave>', lambda e: close_btn.config(fg=DIM, bg=BG))

        def _start_drag_macro(event):
            self._macro_drag_x = event.x
            self._macro_drag_y = event.y

        def _on_drag_macro(event):
            x = panel.winfo_x() + event.x - self._macro_drag_x
            y = panel.winfo_y() + event.y - self._macro_drag_y
            panel.geometry(f"+{x}+{y}")

        for w in (titlebar, title_lbl):
            w.bind('<Button-1>', _start_drag_macro)
            w.bind('<B1-Motion>', _on_drag_macro)

        # ---- Input toggles ----
        toggle_frame = tk.Frame(panel, bg=BG)
        toggle_frame.pack(fill='x', padx=12, pady=(8, 4))

        _toggle_sz = 32
        kb_wrap = tk.Frame(toggle_frame, bg=BORDER, width=_toggle_sz, height=_toggle_sz)
        kb_wrap.pack(side=tk.LEFT, padx=(0, 6))
        kb_wrap.pack_propagate(False)
        self._macro_kb_btn = tk.Button(
            kb_wrap, text='\u2328', font=('Segoe UI Symbol', 14),
            fg=GREEN, bg=BORDER, activebackground='#30363d', activeforeground=GREEN,
            bd=0, relief='flat',
            command=self._toggle_macro_kb)
        self._macro_kb_btn.pack(fill='both', expand=True)

        _mouse_fg = DIM if not mouse else RED
        mouse_wrap = tk.Frame(toggle_frame, bg=BORDER, width=_toggle_sz, height=_toggle_sz)
        mouse_wrap.pack(side=tk.LEFT)
        mouse_wrap.pack_propagate(False)
        self._macro_mouse_btn = tk.Button(
            mouse_wrap, text='\U0001f5b1', font=('Segoe UI Emoji', 12),
            fg=_mouse_fg, bg=BORDER, activebackground='#30363d',
            activeforeground=_mouse_fg,
            bd=0, relief='flat',
            command=self._toggle_macro_mouse,
            state='normal' if mouse else 'disabled',
            disabledforeground=DIM)
        self._macro_mouse_btn.pack(fill='both', expand=True)

        if not mouse:
            _tip = tk.Label(toggle_frame, text='pip install mouse',
                            font=('Consolas', 8), fg='#484f58', bg=BG)
            _tip.pack(side=tk.LEFT, padx=(6, 0))

        # ---- Record row ----
        rec_frame = tk.Frame(panel, bg=BG)
        rec_frame.pack(fill='x', padx=12, pady=(4, 4))

        tk.Label(rec_frame, text='Hotkey:', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._macro_hotkey_var = tk.StringVar(value=self.macro_record_hotkey.upper())
        self._hotkey_capture_btn = tk.Button(
            rec_frame, text=self.macro_record_hotkey.upper(),
            font=('Consolas', 10, 'bold'),
            fg=ACCENT, bg=BG2, activebackground='#30363d', activeforeground=ACCENT,
            bd=1, relief='flat', width=5, pady=0,
            command=self._start_hotkey_capture)
        self._hotkey_capture_btn.pack(side=tk.LEFT, padx=4)

        self._macro_mode_btn = tk.Button(
            rec_frame, text='\u25cf Record \u25c0', font=('Consolas', 9, 'bold'),
            fg='#0d1117', bg=RED, activebackground='#30363d', activeforeground=RED,
            bd=0, relief='flat', padx=6, pady=1,
            command=self._toggle_hotkey_mode)
        self._macro_mode_btn.pack(side=tk.LEFT, padx=(2, 0))

        self._macro_mode_btn2 = tk.Button(
            rec_frame, text='\u25b6 Replay', font=('Consolas', 9, 'bold'),
            fg=GREEN, bg=BG2, activebackground='#30363d', activeforeground=GREEN,
            bd=0, relief='flat', padx=6, pady=1,
            command=self._toggle_hotkey_mode)
        self._macro_mode_btn2.pack(side=tk.LEFT, padx=(2, 0))

        self._macro_rec_btn = tk.Button(
            rec_frame, text='\u25cf Record', font=('Consolas', 10, 'bold'),
            fg=RED, bg=BORDER, activebackground='#30363d', activeforeground=RED,
            bd=0, relief='flat', padx=10, pady=2,
            command=self._toggle_macro_recording)
        self._macro_rec_btn.pack(side=tk.RIGHT)

        # ---- Separator ----
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=4)

        # ---- Action list (Treeview) ----
        style = ttk.Style(panel)
        style.theme_use('clam')
        style.configure("Macro.Treeview",
                         background=BG2, foreground='#c9d1d9',
                         fieldbackground=BG2, borderwidth=0,
                         font=('Consolas', 9))
        style.configure("Macro.Treeview.Heading",
                         background=BORDER, foreground=ACCENT,
                         font=('Consolas', 9, 'bold'), borderwidth=0)
        style.map("Macro.Treeview",
                  background=[('selected', '#1f6feb')],
                  foreground=[('selected', '#ffffff')])

        tree_frame = tk.Frame(panel, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=(0, 4))

        self._macro_tree = ttk.Treeview(
            tree_frame, columns=('delay', 'action'), show='headings',
            style='Macro.Treeview', height=8, selectmode='extended')
        self._macro_tree.heading('delay', text='Delay (s)')
        self._macro_tree.heading('action', text='Action')
        self._macro_tree.column('delay', width=80, anchor='center')
        self._macro_tree.column('action', width=260, anchor='w')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical',
                                   command=self._macro_tree.yview)
        self._macro_tree.configure(yscrollcommand=scrollbar.set)
        self._macro_tree.pack(side=tk.LEFT, fill='both', expand=True)
        scrollbar.pack(side=tk.RIGHT, fill='y')

        self._macro_tree.bind('<Double-1>', self._on_action_double_click)

        # ---- Action controls ----
        act_frame = tk.Frame(panel, bg=BG)
        act_frame.pack(fill='x', padx=12, pady=(0, 4))

        tk.Button(act_frame, text='Delete Selected', font=('Consolas', 9),
                  fg=DIM, bg=BORDER, activebackground='#30363d',
                  bd=0, relief='flat', padx=6, pady=2,
                  command=self._delete_selected_actions).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(act_frame, text='Clear All', font=('Consolas', 9),
                  fg=RED, bg=BORDER, activebackground='#30363d',
                  bd=0, relief='flat', padx=6, pady=2,
                  command=self._clear_all_actions).pack(side=tk.LEFT)

        # ---- Separator ----
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=4)

        # ---- Replay row ----
        play_frame = tk.Frame(panel, bg=BG)
        play_frame.pack(fill='x', padx=12, pady=(0, 4))

        self._macro_play_btn = tk.Button(
            play_frame, text='\u25b6 Play', font=('Consolas', 10, 'bold'),
            fg=GREEN, bg=BORDER, activebackground='#30363d', activeforeground=GREEN,
            bd=0, relief='flat', padx=10, pady=2,
            command=self._toggle_replay)
        self._macro_play_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._macro_loop_btn = tk.Button(
            play_frame, text='Loop: OFF', font=('Consolas', 9, 'bold'),
            fg=RED, bg=BORDER, activebackground='#30363d', activeforeground=RED,
            bd=0, relief='flat', padx=8, pady=2,
            command=self._toggle_macro_loop)
        self._macro_loop_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._macro_interval_var = tk.DoubleVar(value=1.0)
        tk.Scale(
            play_frame, from_=0, to=10.0, resolution=0.1,
            orient='horizontal', variable=self._macro_interval_var,
            length=120, width=12, font=('Consolas', 8),
            fg=DIM, bg=BG, troughcolor=BG2,
            activebackground=ACCENT, highlightthickness=0,
            bd=0, sliderrelief='flat', showvalue=True,
            label='Interval').pack(side=tk.LEFT)

        # ---- Separator ----
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=4)

        # ---- Saved macros section ----
        tk.Label(panel, text="Saved Macros", font=("Consolas", 10, "bold"),
                 fg=DIM, bg=BG).pack(anchor='w', padx=12)

        saved_frame = tk.Frame(panel, bg=BG)
        saved_frame.pack(fill='x', padx=12, pady=(2, 4))

        self._macro_listbox = tk.Listbox(
            saved_frame, font=('Consolas', 9), fg='#c9d1d9', bg=BG2,
            selectbackground='#1f6feb', selectforeground='#ffffff',
            height=4, bd=0, highlightthickness=1, highlightcolor=BORDER,
            highlightbackground=BORDER)
        self._macro_listbox.pack(fill='x')
        self._macro_listbox.bind('<<ListboxSelect>>', self._on_saved_list_select)

        btn_frame = tk.Frame(panel, bg=BG)
        btn_frame.pack(fill='x', padx=12, pady=(0, 8))

        for text, cmd in [('Save As', self._save_macro_as),
                          ('Load', self._load_selected_macro),
                          ('Rename', self._rename_selected_macro),
                          ('Delete', self._delete_selected_macro)]:
            tk.Button(btn_frame, text=text, font=('Consolas', 9),
                      fg=DIM, bg=BORDER, activebackground='#30363d',
                      bd=0, relief='flat', padx=6, pady=2,
                      command=cmd).pack(side=tk.LEFT, padx=(0, 4))

        # Populate lists
        self._refresh_action_list()
        self._refresh_saved_list()

    # ------------------------------------------------------ Macro Toggles
    def _toggle_macro_kb(self):
        self.macro_record_kb = not self.macro_record_kb
        if self.macro_panel:
            if self.macro_record_kb:
                self._macro_kb_btn.config(fg='#50fa7b', activeforeground='#50fa7b')
            else:
                self._macro_kb_btn.config(fg='#ff5555', activeforeground='#ff5555')

    def _toggle_macro_mouse(self):
        if not mouse:
            print("[MACRO] Mouse recording requires 'pip install mouse'")
            return
        self.macro_record_mouse = not self.macro_record_mouse
        if self.macro_panel:
            if self.macro_record_mouse:
                self._macro_mouse_btn.config(fg='#50fa7b', activeforeground='#50fa7b')
            else:
                self._macro_mouse_btn.config(fg='#ff5555', activeforeground='#ff5555')

    def _toggle_macro_loop(self):
        self.macro_looping = not self.macro_looping
        if self.macro_panel:
            if self.macro_looping:
                self._macro_loop_btn.config(text='Loop: ON', fg='#50fa7b',
                                             activeforeground='#50fa7b')
            else:
                self._macro_loop_btn.config(text='Loop: OFF', fg='#ff5555',
                                             activeforeground='#ff5555')

    # ----------------------------------------------- Macro Hotkey Mode
    def _toggle_hotkey_mode(self):
        """Switch the hotkey between record and replay mode."""
        BG2 = '#161b22'
        RED = '#ff5555'
        GREEN = '#50fa7b'
        DARK = '#0d1117'
        if self.macro_hotkey_mode == 'record':
            self.macro_hotkey_mode = 'replay'
            if self.macro_panel and hasattr(self, '_macro_mode_btn'):
                self._macro_mode_btn.config(text='\u25cf Record', fg=RED, bg=BG2,
                                             activeforeground=RED)
                self._macro_mode_btn2.config(text='\u25b6 Replay \u25c0', fg=DARK, bg=GREEN,
                                              activeforeground=GREEN)
        else:
            self.macro_hotkey_mode = 'record'
            if self.macro_panel and hasattr(self, '_macro_mode_btn'):
                self._macro_mode_btn.config(text='\u25cf Record \u25c0', fg=DARK, bg=RED,
                                             activeforeground=RED)
                self._macro_mode_btn2.config(text='\u25b6 Replay', fg=GREEN, bg=BG2,
                                              activeforeground=GREEN)
        print(f"[MACRO] Hotkey mode: {self.macro_hotkey_mode}")

    def _macro_hotkey_dispatch(self):
        """Dispatch the hotkey press based on current mode."""
        if self.macro_hotkey_mode == 'replay':
            self._toggle_replay()
        else:
            self._toggle_macro_recording()

    # ---------------------------------------------------- Macro Recording
    def _toggle_macro_recording(self):
        if self.macro_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if self.macro_replaying:
            self._stop_replay()
        self.macro_actions = []
        self._macro_record_start = time.time()
        self._macro_last_event_time = time.time()
        self.macro_recording = True

        if self.macro_record_kb:
            self._macro_kb_hook = keyboard.hook(self._on_macro_key_event)
        if self.macro_record_mouse and mouse:
            self._macro_mouse_hook = mouse.hook(self._on_macro_mouse_event)

        if self.macro_panel:
            self._macro_rec_btn.config(text='\u25a0 Stop', fg='#ff5555',
                                        activeforeground='#ff5555')
        self._refresh_action_list()
        print("[MACRO] Recording started")

    def _stop_recording(self):
        self.macro_recording = False
        if self._macro_kb_hook:
            keyboard.unhook(self._macro_kb_hook)
            self._macro_kb_hook = None
        if self._macro_mouse_hook and mouse:
            mouse.unhook(self._macro_mouse_hook)
            self._macro_mouse_hook = None

        if self.macro_panel:
            self._macro_rec_btn.config(text='\u25cf Record', fg='#ff5555',
                                        activeforeground='#ff5555')
        self._refresh_action_list()
        print(f"[MACRO] Recording stopped, {len(self.macro_actions)} actions")

    def _on_macro_key_event(self, event):
        if not self.macro_recording:
            return
        # Filter out the record hotkey
        if event.name and event.name.lower() == self.macro_record_hotkey.lower():
            return

        now = time.time()
        delay = now - self._macro_last_event_time
        self._macro_last_event_time = now

        # Detect extended keys (arrows, insert, delete, etc.)
        _ext_names = {'insert', 'delete', 'home', 'end', 'page up', 'page down',
                      'up', 'down', 'left', 'right'}
        extended = (event.name or '').lower() in _ext_names

        action = {
            'type': 'key_down' if event.event_type == 'down' else 'key_up',
            'delay': round(delay, 4),
            'key': event.name,
            'scan_code': event.scan_code,
            'extended': extended,
        }
        self.macro_actions.append(action)
        if self.macro_panel:
            self.root.after(0, self._refresh_action_list)

    def _on_macro_mouse_event(self, event):
        if not self.macro_recording:
            return

        now = time.time()
        delay = now - self._macro_last_event_time

        if isinstance(event, mouse.MoveEvent):
            # Throttle mouse moves to ~50ms intervals
            if (self.macro_actions and self.macro_actions[-1]['type'] == 'mouse_move'
                    and delay < 0.05):
                self.macro_actions[-1]['x'] = event.x
                self.macro_actions[-1]['y'] = event.y
                return
            self._macro_last_event_time = now
            action = {
                'type': 'mouse_move',
                'delay': round(delay, 4),
                'x': event.x, 'y': event.y,
            }
        elif isinstance(event, mouse.ButtonEvent):
            if event.event_type == 'double':
                return  # skip double-click events
            self._macro_last_event_time = now
            action = {
                'type': 'mouse_down' if event.event_type == 'down' else 'mouse_up',
                'delay': round(delay, 4),
                'button': event.button,
                'x': None, 'y': None,
            }
            # Grab current cursor position
            try:
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                action['x'] = pt.x
                action['y'] = pt.y
            except Exception:
                pass
        else:
            return  # skip wheel events etc.

        self.macro_actions.append(action)
        if self.macro_panel:
            self.root.after(0, self._refresh_action_list)

    # ----------------------------------------------- Macro Action List GUI
    def _refresh_action_list(self):
        """Refresh the action list treeview."""
        if not self.macro_panel or not hasattr(self, '_macro_tree'):
            return
        try:
            tree = self._macro_tree
            tree.delete(*tree.get_children())
            for i, action in enumerate(self.macro_actions):
                delay_str = f"{action['delay']:.3f}"
                act_type = action['type']
                if act_type in ('key_down', 'key_up'):
                    arrow = '\u2193' if act_type == 'key_down' else '\u2191'
                    desc = f"{arrow} {action.get('key', '?')}"
                elif act_type == 'mouse_move':
                    desc = f"\u2192 move ({action.get('x', '?')}, {action.get('y', '?')})"
                elif act_type in ('mouse_down', 'mouse_up'):
                    arrow = '\u2193' if act_type == 'mouse_down' else '\u2191'
                    btn = action.get('button', '?')
                    pos = f"({action.get('x', '?')}, {action.get('y', '?')})"
                    desc = f"{arrow} {btn} click {pos}"
                else:
                    desc = act_type
                tree.insert('', 'end', iid=str(i), values=(delay_str, desc))
            # Auto-scroll to bottom
            children = tree.get_children()
            if children:
                tree.see(children[-1])
        except Exception:
            pass

    def _refresh_saved_list(self):
        """Refresh the saved macros listbox."""
        if not self.macro_panel or not hasattr(self, '_macro_listbox'):
            return
        try:
            self._macro_listbox.delete(0, tk.END)
            for name in sorted(self.macro_saved.keys()):
                count = len(self.macro_saved[name])
                self._macro_listbox.insert(tk.END, f"{name} ({count} actions)")
        except Exception:
            pass

    def _on_saved_list_select(self, event):
        sel = self._macro_listbox.curselection()
        if sel:
            text = self._macro_listbox.get(sel[0])
            name = text.rsplit(' (', 1)[0]
            self.macro_selected_name = name
        else:
            self.macro_selected_name = None

    def _on_action_double_click(self, event):
        """Allow inline editing of delay values."""
        region = self._macro_tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        col = self._macro_tree.identify_column(event.x)
        if col != '#1':  # only edit delay column
            return
        item = self._macro_tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        if idx >= len(self.macro_actions):
            return

        bbox = self._macro_tree.bbox(item, col)
        if not bbox:
            return

        x, y, w, h = bbox
        entry = tk.Entry(self._macro_tree, font=('Consolas', 9),
                         fg='#58a6ff', bg='#161b22', insertbackground='#58a6ff',
                         bd=0, justify='center')
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, f"{self.macro_actions[idx]['delay']:.3f}")
        entry.select_range(0, tk.END)
        entry.focus()

        def commit(e=None):
            try:
                val = float(entry.get())
                if val < 0:
                    val = 0
                self.macro_actions[idx]['delay'] = round(val, 4)
            except ValueError:
                pass
            entry.destroy()
            self._refresh_action_list()

        entry.bind('<Return>', commit)
        entry.bind('<FocusOut>', commit)
        entry.bind('<Escape>', lambda e: (entry.destroy(), self._refresh_action_list()))

    def _delete_selected_actions(self):
        """Delete selected actions from the list."""
        if not hasattr(self, '_macro_tree'):
            return
        selected = self._macro_tree.selection()
        if not selected:
            return
        indices = sorted([int(s) for s in selected], reverse=True)
        for idx in indices:
            if 0 <= idx < len(self.macro_actions):
                del self.macro_actions[idx]
        self._refresh_action_list()

    def _clear_all_actions(self):
        """Clear all recorded actions."""
        self.macro_actions = []
        self._refresh_action_list()

    # ------------------------------------------------------- Macro Replay
    def _toggle_replay(self):
        if self.macro_replaying:
            self._stop_replay()
        else:
            self._start_replay()

    def _start_replay(self):
        if not self.macro_actions:
            return
        if self.macro_recording:
            self._stop_recording()
        self._macro_replay_stop = False
        self.macro_replaying = True
        # Hook keyboard/mouse to stop replay on any user input
        self._replay_kb_hook = keyboard.on_press(self._on_replay_input, suppress=False)
        if mouse:
            self._replay_mouse_hook = mouse.on_click(lambda: self._on_replay_input(None))
        if self.macro_panel:
            self._macro_play_btn.config(text='\u25a0 Stop', fg='#ff5555',
                                         activeforeground='#ff5555')
        self._macro_replay_thread = Thread(target=self._replay_loop, daemon=True)
        self._macro_replay_thread.start()
        print("[MACRO] Replay started")

    def _on_replay_input(self, event):
        """Stop replay when user presses any key or clicks mouse."""
        if self.macro_replaying:
            self.root.after(0, self._stop_replay)

    def _stop_replay(self):
        self._macro_replay_stop = True
        self.macro_replaying = False
        # Unhook input listeners
        if hasattr(self, '_replay_kb_hook'):
            keyboard.unhook(self._replay_kb_hook)
            del self._replay_kb_hook
        if hasattr(self, '_replay_mouse_hook') and mouse:
            mouse.unhook(self._replay_mouse_hook)
            del self._replay_mouse_hook
        if self.macro_panel:
            self._macro_play_btn.config(text='\u25b6 Play', fg='#50fa7b',
                                         activeforeground='#50fa7b')
        self.root.after(0, lambda: self._highlight_action(-1))
        print("[MACRO] Replay stopped")

    def _replay_loop(self):
        """Replay recorded actions, optionally looping."""
        while not self._macro_replay_stop:
            for i, action in enumerate(self.macro_actions):
                if self._macro_replay_stop:
                    break
                # Pause while Roblox not focused
                while not self._roblox_focused() and not self._macro_replay_stop:
                    time.sleep(0.05)
                if self._macro_replay_stop:
                    break

                # Wait delay with 1ms poll granularity
                delay = action.get('delay', 0)
                deadline = time.time() + delay
                while time.time() < deadline:
                    if self._macro_replay_stop:
                        break
                    time.sleep(0.001)
                if self._macro_replay_stop:
                    break

                # Highlight current row
                self.root.after(0, lambda idx=i: self._highlight_action(idx))
                self._execute_macro_action(action)

            if not self.macro_looping or self._macro_replay_stop:
                break

            # Loop interval wait
            interval = self._macro_interval_var.get() if hasattr(self, '_macro_interval_var') else 1.0
            deadline = time.time() + interval
            while time.time() < deadline:
                if self._macro_replay_stop:
                    break
                time.sleep(0.01)

        # Finished
        self.macro_replaying = False
        if self.macro_panel:
            self.root.after(0, lambda: self._macro_play_btn.config(
                text='\u25b6 Play', fg='#50fa7b', activeforeground='#50fa7b'))
        self.root.after(0, lambda: self._highlight_action(-1))

    def _execute_macro_action(self, action):
        """Execute a single macro action via SendInput."""
        act_type = action['type']

        if act_type == 'key_down':
            sc = action.get('scan_code')
            if sc:
                self._send_key(sc, key_up=False, extended=action.get('extended', False))

        elif act_type == 'key_up':
            sc = action.get('scan_code')
            if sc:
                self._send_key(sc, key_up=True, extended=action.get('extended', False))

        elif act_type == 'mouse_move':
            x, y = action.get('x'), action.get('y')
            if x is not None and y is not None:
                abs_x = int((x - self._virt_left) * 65535 / (self._virt_w - 1))
                abs_y = int((y - self._virt_top) * 65535 / (self._virt_h - 1))
                # ABSOLUTE | VIRTUALDESK | MOVE
                self._send_mouse(0x8000 | 0x4000 | 0x0001, abs_x, abs_y)

        elif act_type == 'mouse_down':
            x, y = action.get('x'), action.get('y')
            button = action.get('button', 'left')
            flags = 0x8000 | 0x4000  # ABSOLUTE | VIRTUALDESK
            if button == 'left':
                flags |= 0x0002  # LEFTDOWN
            elif button == 'right':
                flags |= 0x0008  # RIGHTDOWN
            elif button == 'middle':
                flags |= 0x0020  # MIDDLEDOWN
            if x is not None and y is not None:
                abs_x = int((x - self._virt_left) * 65535 / (self._virt_w - 1))
                abs_y = int((y - self._virt_top) * 65535 / (self._virt_h - 1))
            else:
                abs_x, abs_y, _, _ = self._get_abs_coords()
            self._send_mouse(flags, abs_x, abs_y)

        elif act_type == 'mouse_up':
            x, y = action.get('x'), action.get('y')
            button = action.get('button', 'left')
            flags = 0x8000 | 0x4000  # ABSOLUTE | VIRTUALDESK
            if button == 'left':
                flags |= 0x0004  # LEFTUP
            elif button == 'right':
                flags |= 0x0010  # RIGHTUP
            elif button == 'middle':
                flags |= 0x0040  # MIDDLEUP
            if x is not None and y is not None:
                abs_x = int((x - self._virt_left) * 65535 / (self._virt_w - 1))
                abs_y = int((y - self._virt_top) * 65535 / (self._virt_h - 1))
            else:
                abs_x, abs_y, _, _ = self._get_abs_coords()
            self._send_mouse(flags, abs_x, abs_y)

    def _highlight_action(self, idx):
        """Highlight the given action row in the treeview."""
        if not self.macro_panel or not hasattr(self, '_macro_tree'):
            return
        try:
            tree = self._macro_tree
            for item in tree.get_children():
                tree.item(item, tags=())
            if 0 <= idx < len(self.macro_actions):
                item_id = str(idx)
                if tree.exists(item_id):
                    tree.item(item_id, tags=('playing',))
                    tree.tag_configure('playing', background='#1f6feb',
                                       foreground='#ffffff')
                    tree.see(item_id)
        except Exception:
            pass

    # ------------------------------------------------- Macro Persistence
    def _save_macro_as(self):
        """Save current actions under a new name."""
        if not self.macro_actions:
            return
        name = simpledialog.askstring("Save Macro", "Enter macro name:",
                                       parent=self.macro_panel)
        if not name or not name.strip():
            return
        name = name.strip()
        self.macro_saved[name] = [dict(a) for a in self.macro_actions]
        self._save_macros()
        self._refresh_saved_list()
        print(f"[MACRO] Saved '{name}' ({len(self.macro_actions)} actions)")

    def _load_selected_macro(self):
        """Load the selected macro into the action list."""
        if not self.macro_selected_name:
            return
        name = self.macro_selected_name
        if name not in self.macro_saved:
            return
        if self.macro_recording:
            self._stop_recording()
        if self.macro_replaying:
            self._stop_replay()
        self.macro_actions = [dict(a) for a in self.macro_saved[name]]
        self._refresh_action_list()
        print(f"[MACRO] Loaded '{name}' ({len(self.macro_actions)} actions)")

    def _rename_selected_macro(self):
        """Rename the selected saved macro."""
        if not self.macro_selected_name:
            return
        old_name = self.macro_selected_name
        if old_name not in self.macro_saved:
            return
        new_name = simpledialog.askstring("Rename Macro", "New name:",
                                           initialvalue=old_name,
                                           parent=self.macro_panel)
        if not new_name or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        self.macro_saved[new_name] = self.macro_saved.pop(old_name)
        self.macro_selected_name = new_name
        self._save_macros()
        self._refresh_saved_list()
        print(f"[MACRO] Renamed '{old_name}' -> '{new_name}'")

    def _delete_selected_macro(self):
        """Delete the selected saved macro."""
        if not self.macro_selected_name:
            return
        name = self.macro_selected_name
        if name not in self.macro_saved:
            return
        del self.macro_saved[name]
        self.macro_selected_name = None
        self._save_macros()
        self._refresh_saved_list()
        print(f"[MACRO] Deleted '{name}'")

    # ------------------------------------------------ Hotkey Rebinding
    def _start_key_rebind(self, hotkey_name):
        """Enter 'press any key' capture mode for a rebindable hotkey."""
        if self._capturing_hotkey is not None:
            return
        self._capturing_hotkey = hotkey_name
        ui = self._hotkey_ui[hotkey_name]
        if ui['type'] == 'label':
            ui['widget'].config(text='Press key...', fg='#f0c674')
        else:
            self.pipe_canvas.itemconfig(ui['item_id'],
                                        text='Press key...', fill='#f0c674')
        self._rebind_hook_id = keyboard.on_press(
            self._on_key_rebind_capture, suppress=False)

    def _on_key_rebind_capture(self, event):
        """Handle a key press during hotkey rebinding."""
        new_key = event.name
        keyboard.unhook(self._rebind_hook_id)
        name = self._capturing_hotkey
        self._capturing_hotkey = None
        self.root.after(0, lambda: self._apply_key_rebind(name, new_key))

    def _apply_key_rebind(self, hotkey_name, new_key):
        """Apply the captured key rebind on the main thread."""
        entry = self._hotkey_map[hotkey_name]
        old_key = entry['key']
        display = new_key.upper()
        ui = self._hotkey_ui[hotkey_name]
        if new_key == old_key:
            # Same key — just restore the display
            if ui['type'] == 'label':
                ui['widget'].config(text=f'[{display}]', fg='#30363d')
            else:
                self.pipe_canvas.itemconfig(ui['item_id'],
                                            text=f'[{display}]', fill='#30363d')
            return
        # Unhook old key
        try:
            keyboard.unhook(entry['hook'])
        except Exception:
            pass
        # Update state
        entry['key'] = new_key
        entry['hook'] = keyboard.on_press_key(new_key, entry['callback'])
        # Update UI
        if ui['type'] == 'label':
            ui['widget'].config(text=f'[{display}]', fg='#30363d')
        else:
            self.pipe_canvas.itemconfig(ui['item_id'],
                                        text=f'[{display}]', fill='#30363d')
        print(f"[HOTKEY] '{hotkey_name}' rebound: {old_key} -> {new_key}")

    # ------------------------------------------------ Macro Hotkey Capture
    def _start_hotkey_capture(self):
        """Enter 'press any key' mode on the hotkey button."""
        if getattr(self, '_hotkey_capturing', False):
            return
        self._hotkey_capturing = True
        self._hotkey_capture_btn.config(text='Press key...', fg='#f0c674')
        self._hotkey_hook_id = keyboard.on_press(self._on_hotkey_capture, suppress=False)

    def _on_hotkey_capture(self, event):
        """Handle a key press during hotkey capture."""
        new_key = event.name
        keyboard.unhook(self._hotkey_hook_id)
        self._hotkey_capturing = False
        # Apply on the main thread
        self.root.after(0, lambda: self._apply_captured_hotkey(new_key))

    def _apply_captured_hotkey(self, new_key):
        """Apply the captured hotkey on the main thread."""
        old_key = self.macro_record_hotkey
        if new_key == old_key:
            self._hotkey_capture_btn.config(text=new_key.upper(), fg='#58a6ff')
            return
        # Unregister old hotkey
        try:
            keyboard.remove_hotkey(self._macro_f9_hotkey_id)
        except Exception:
            pass
        self.macro_record_hotkey = new_key
        self._macro_hotkey_var.set(new_key.upper())
        self._hotkey_capture_btn.config(text=new_key.upper(), fg='#58a6ff')
        # Register new hotkey
        try:
            self._macro_f9_hotkey_id = keyboard.add_hotkey(
                new_key, self._macro_hotkey_dispatch)
        except Exception as e:
            print(f"[MACRO] Hotkey error: {e}")
        print(f"[MACRO] Record hotkey changed to '{new_key}'")

    # --------------------------------------------------------- Check update
    def _run_in_app_update(self):
        """Check for updates from within the running app."""
        from updater import check_for_update, apply_update, restart, _UpdateWindow

        btn = self._update_btn
        btn.config(text='\u231B', fg='#f0c040')  # hourglass
        btn._rest_fg = '#f0c040'
        btn.unbind('<Button-1>')  # prevent double-clicks
        self.root.update_idletasks()

        def _do_check():
            result = check_for_update()
            self.root.after(0, lambda: _on_check_done(result))

        def _on_check_done(result):
            if result is None:
                btn.config(text='\u2714', fg='#50fa7b')
                btn._rest_fg = '#50fa7b'
                print("[UPDATER] Already up to date.")
                # Reset after 2s
                self.root.after(2000, _reset_btn)
                return

            tag, url = result
            btn.config(text='\u21BB', fg='#58a6ff')
            btn._rest_fg = '#58a6ff'
            print(f"[UPDATER] New version: {tag}, downloading...")

            # Show the updater splash for download + apply
            win = _UpdateWindow()
            win.set_status(f"Updating to {tag}...", "Downloading new version")

            def _do_apply():
                ok = apply_update(url)
                self.root.after(0, lambda: _on_apply_done(ok, tag, win))

            Thread(target=_do_apply, daemon=True).start()
            _pump_splash(win)

        def _pump_splash(win):
            """Keep splash responsive while download thread runs."""
            try:
                win.root.update()
            except tk.TclError:
                return
            self.root.after(16, lambda: _pump_splash(win))

        def _on_apply_done(ok, tag, win):
            if ok:
                win.set_done(f"Updated to {tag}")
                win.set_status(f"Updated to {tag}", "Restarting...")
                win.root.update()
                import time
                time.sleep(1)
                win.close()
                self._quit()
                restart()
            else:
                win.set_error("Update failed")
                win.root.update()
                import time
                time.sleep(2)
                win.close()
                _reset_btn()

        def _reset_btn():
            btn.config(text='\u21BB', fg='#484f58')
            btn._rest_fg = '#484f58'
            btn.bind('<Button-1>', lambda e: self._run_in_app_update())

        Thread(target=_do_check, daemon=True).start()

    # ------------------------------------------------------------ Minimize
    def _minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()
        def _restore(event):
            self.root.overrideredirect(True)
            self.root.attributes('-topmost', True)
            self.root.unbind('<Map>')
        self.root.bind('<Map>', _restore)

    # --------------------------------------------------------------- Exit
    def _quit(self):
        self.running = False
        if self.macro_recording:
            self._stop_recording()
        if self.macro_replaying:
            self._stop_replay()
        if self.holding_left:
            self._send_key(self._SCAN_LEFT, key_up=True, extended=True)
        self._destroy_mini_win()
        keyboard.unhook_all()
        try:
            mouse.unhook_all()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    from updater import run_update_check
    run_update_check()
    LenkTools().run()
