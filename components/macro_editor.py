"""Macro editor component — record, edit, and replay macros."""

import ctypes
import ctypes.wintypes
import time
import json
import os
import tkinter as tk
from tkinter import ttk
from threading import Thread

import keyboard

from components.base import Component
from core.theme import (BG, BG2, BORDER, DIM, ACCENT, GREEN, RED, TEXT,
                        make_dotted_bg, apply_glass, make_glass_dynamic,
                        apply_rounded_corners, style_flat_treeview,
                        build_titlebar, make_draggable)
from core.modal import ThemedModal

try:
    import mouse as mouse_module
except ImportError:
    mouse_module = None

_KEY_DISPLAY = {
    'backslash': '\\',
    'space': 'Spc',
    'tab': 'Tab',
    'escape': 'Esc',
    'enter': 'Ent',
    'delete': 'Del',
    'insert': 'Ins',
    'home': 'Home',
    'end': 'End',
    'page up': 'PgUp',
    'page down': 'PgDn',
}


def _fmt_key(key):
    return _KEY_DISPLAY.get(key.lower(), key.upper())


class MacroEditorComponent(Component):
    """Record, edit, and replay keyboard/mouse macros."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self.default_hotkey = config.get('default_hotkey', 'backslash')

        # State
        self.panel_open = False
        self.panel = None
        self.recording = False
        self.replaying = False
        self.looping = False
        self.record_kb = True
        self.record_mouse = False
        self.actions = []
        self.saved = {}
        self.selected_name = None
        self.record_hotkey = self.default_hotkey
        self.hotkey_mode = 'record'
        self._replay_idx = 0
        self._kb_hook = None
        self._mouse_hook = None
        self._record_start = 0
        self._last_event_time = 0
        self._replay_thread = None
        self._replay_stop = False
        self._hotkey_id = None

    def start(self):
        """Register the macro hotkey."""
        self._active = True
        self._hotkey_id = keyboard.on_press_key(
            self.record_hotkey, lambda e: self._hotkey_dispatch())

    def stop(self):
        """Unregister the macro hotkey."""
        self._active = False
        if self._hotkey_id is not None:
            try:
                keyboard.unhook(self._hotkey_id)
            except Exception:
                pass
            self._hotkey_id = None

    def load_macros(self):
        """Load saved macros from data/macros.json."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Try data/ first, then root
        for path in [os.path.join(base, 'data', 'macros.json'),
                     os.path.join(base, 'macros.json')]:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        self.saved = json.load(f)
                    return
                except Exception:
                    pass
        self.saved = {}

    def save_macros(self):
        """Write saved macros to data/macros.json."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'data', 'macros.json')
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                json.dump(self.saved, f, indent=2)
        except Exception as e:
            print(f"[MACRO] Save error: {e}")

    def toggle_panel(self, root):
        """Open or close the macro editor panel."""
        if self.panel_open and self.panel:
            try:
                self.panel.destroy()
            except Exception:
                pass
            self.panel_open = False
            self.panel = None
            return
        self.load_macros()
        self._build_panel(root)
        self.panel_open = True

    def _hotkey_dispatch(self):
        if self.replaying:
            self._stop_replay()
        elif self.hotkey_mode == 'replay':
            self._toggle_replay()
        else:
            self._toggle_recording()

    def _toggle_recording(self):
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        if self.replaying:
            self._stop_replay()
        self.actions = []
        self._record_start = time.time()
        self._last_event_time = time.time()
        self.recording = True

        if self.record_kb:
            self._kb_hook = keyboard.hook(self._on_key_event)
        if self.record_mouse and mouse_module:
            self._mouse_hook = mouse_module.hook(self._on_mouse_event)

        if self.panel:
            self._rec_btn.config(text='\u25a0 Stop', fg=RED,
                                  activeforeground=RED)
        self._refresh_action_list()
        print("[MACRO] Recording started")

    def _stop_recording(self):
        self.recording = False
        if self._kb_hook:
            keyboard.unhook(self._kb_hook)
            self._kb_hook = None
        if self._mouse_hook and mouse_module:
            mouse_module.unhook(self._mouse_hook)
            self._mouse_hook = None

        if self.panel:
            self._rec_btn.config(text='\u25cf Record', fg=RED,
                                  activeforeground=RED)
        self._refresh_action_list()
        print(f"[MACRO] Recording stopped, {len(self.actions)} actions")

    def _is_hotkey_event(self, event):
        """True if event matches the current record hotkey (name-normalized)."""
        if not getattr(event, 'name', None):
            return False
        try:
            return (keyboard.normalize_name(event.name)
                    == keyboard.normalize_name(self.record_hotkey))
        except Exception:
            return event.name.lower() == self.record_hotkey.lower()

    def _on_key_event(self, event):
        if not self.recording:
            return
        if self._is_hotkey_event(event):
            return

        now = time.time()
        delay = now - self._last_event_time
        self._last_event_time = now

        _ext_names = {'insert', 'delete', 'home', 'end', 'page up',
                      'page down', 'up', 'down', 'left', 'right'}
        extended = (event.name or '').lower() in _ext_names

        action = {
            'type': 'key_down' if event.event_type == 'down' else 'key_up',
            'delay': round(delay, 4),
            'key': event.name,
            'scan_code': event.scan_code,
            'extended': extended,
        }
        self.actions.append(action)
        if self.panel:
            self.hub.root.after(0, self._refresh_action_list)

    def _on_mouse_event(self, event):
        if not self.recording:
            return

        now = time.time()
        delay = now - self._last_event_time

        if isinstance(event, mouse_module.MoveEvent):
            if (self.actions and self.actions[-1]['type'] == 'mouse_move'
                    and delay < 0.05):
                self.actions[-1]['x'] = event.x
                self.actions[-1]['y'] = event.y
                return
            self._last_event_time = now
            action = {
                'type': 'mouse_move', 'delay': round(delay, 4),
                'x': event.x, 'y': event.y,
            }
        elif isinstance(event, mouse_module.ButtonEvent):
            if event.event_type == 'double':
                return
            self._last_event_time = now
            action = {
                'type': ('mouse_down' if event.event_type == 'down'
                         else 'mouse_up'),
                'delay': round(delay, 4),
                'button': event.button, 'x': None, 'y': None,
            }
            try:
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                action['x'] = pt.x
                action['y'] = pt.y
            except Exception:
                pass
        else:
            return

        self.actions.append(action)
        if self.panel:
            self.hub.root.after(0, self._refresh_action_list)

    def _toggle_replay(self):
        if self.replaying:
            self._stop_replay()
        else:
            self._start_replay()

    def _start_replay(self):
        if not self.actions:
            return
        if self.recording:
            self._stop_recording()
        self._replay_stop = False
        self.replaying = True
        self._replay_kb_hook = keyboard.on_press(
            self._on_replay_input, suppress=False)
        if mouse_module:
            self._replay_mouse_hook = mouse_module.on_click(
                lambda: self._on_replay_input(None))
        if self.panel:
            self._play_btn.config(text='\u25a0 Stop', fg=RED,
                                   activeforeground=RED)
        self._replay_thread = Thread(target=self._replay_loop, daemon=True)
        self._replay_thread.start()
        print("[MACRO] Replay started")

    def _on_replay_input(self, event):
        if self.replaying:
            if event is not None and self._is_hotkey_event(event):
                return
            self.hub.root.after(0, self._stop_replay)

    def _stop_replay(self):
        self._replay_stop = True
        self.replaying = False
        if hasattr(self, '_replay_kb_hook'):
            keyboard.unhook(self._replay_kb_hook)
            del self._replay_kb_hook
        if hasattr(self, '_replay_mouse_hook') and mouse_module:
            mouse_module.unhook(self._replay_mouse_hook)
            del self._replay_mouse_hook
        if self.panel:
            self._play_btn.config(text='\u25b6 Play', fg=GREEN,
                                   activeforeground=GREEN)
        self.hub.root.after(0, lambda: self._highlight_action(-1))
        print("[MACRO] Replay stopped")

    def _replay_loop(self):
        inp = self.hub.input
        while not self._replay_stop:
            for i, action in enumerate(self.actions):
                if self._replay_stop:
                    break
                while (not self.hub.focus.is_focused()
                       and not self._replay_stop):
                    time.sleep(0.05)
                if self._replay_stop:
                    break

                delay = action.get('delay', 0)
                deadline = time.time() + delay
                while time.time() < deadline:
                    if self._replay_stop:
                        break
                    time.sleep(0.001)
                if self._replay_stop:
                    break

                self.hub.root.after(
                    0, lambda idx=i: self._highlight_action(idx))
                self._execute_action(action, inp)

            if not self.looping or self._replay_stop:
                break

            try:
                interval = max(0.0, float(
                    self._interval_var.get()
                    if hasattr(self, '_interval_var') else 1.0))
            except (ValueError, tk.TclError):
                interval = 1.0
            deadline = time.time() + interval
            while time.time() < deadline:
                if self._replay_stop:
                    break
                time.sleep(0.01)

        self.replaying = False
        if self.panel:
            self.hub.root.after(0, lambda: self._play_btn.config(
                text='\u25b6 Play', fg=GREEN, activeforeground=GREEN))
        self.hub.root.after(0, lambda: self._highlight_action(-1))

    def _execute_action(self, action, inp):
        act_type = action['type']

        if act_type == 'key_down':
            sc = action.get('scan_code')
            if sc:
                inp.send_key(
                    sc, key_up=False,
                    extended=action.get('extended', False))
        elif act_type == 'key_up':
            sc = action.get('scan_code')
            if sc:
                inp.send_key(
                    sc, key_up=True,
                    extended=action.get('extended', False))
        elif act_type == 'mouse_move':
            x, y = action.get('x'), action.get('y')
            if x is not None and y is not None:
                abs_x, abs_y = inp.screen_to_abs(x, y)
                inp.send_mouse(0x8000 | 0x4000 | 0x0001, abs_x, abs_y)
        elif act_type == 'mouse_down':
            x, y = action.get('x'), action.get('y')
            button = action.get('button', 'left')
            flags = 0x8000 | 0x4000
            if button == 'left':
                flags |= 0x0002
            elif button == 'right':
                flags |= 0x0008
            elif button == 'middle':
                flags |= 0x0020
            if x is not None and y is not None:
                abs_x, abs_y = inp.screen_to_abs(x, y)
            else:
                abs_x, abs_y, _, _ = inp.get_abs_coords()
            inp.send_mouse(flags, abs_x, abs_y)
        elif act_type == 'mouse_up':
            x, y = action.get('x'), action.get('y')
            button = action.get('button', 'left')
            flags = 0x8000 | 0x4000
            if button == 'left':
                flags |= 0x0004
            elif button == 'right':
                flags |= 0x0010
            elif button == 'middle':
                flags |= 0x0040
            if x is not None and y is not None:
                abs_x, abs_y = inp.screen_to_abs(x, y)
            else:
                abs_x, abs_y, _, _ = inp.get_abs_coords()
            inp.send_mouse(flags, abs_x, abs_y)

    def _build_panel(self, root):
        """Build the macro editor Toplevel window."""
        root_x = root.winfo_x()
        root_y = root.winfo_y()
        root_w = root.winfo_width()

        panel = tk.Toplevel(root)
        panel.overrideredirect(True)
        panel.geometry(f"380x520+{root_x + root_w + 10}+{root_y}")
        panel.attributes('-topmost', True)
        panel.resizable(False, False)
        panel.configure(bg=BG)
        apply_glass(panel)
        make_glass_dynamic(panel)
        apply_rounded_corners(panel)
        self.panel = panel

        def on_close():
            if self.recording:
                self._stop_recording()
            if self.replaying:
                self._stop_replay()
            self.panel_open = False
            self.panel = None
            panel.destroy()

        # Background
        MW, MH = 380, 520
        self._bg_img = make_dotted_bg(MW, MH)
        tk.Label(panel, image=self._bg_img, bd=0).place(
            x=0, y=0, relwidth=1, relheight=1)

        # Title bar
        titlebar, title_lbl = build_titlebar(
            panel, "MACRO EDITOR", on_close=on_close)
        make_draggable(titlebar, panel)
        make_draggable(title_lbl, panel)

        # ── Controls row ─────────────────────────────────────────────
        ctrl = tk.Frame(panel, bg=BG)
        ctrl.pack(fill='x', padx=12, pady=(8, 4))

        # KB / Mouse input toggles
        SZ = 26
        kb_wrap = tk.Frame(ctrl, bg=BORDER, width=SZ, height=SZ)
        kb_wrap.pack(side=tk.LEFT, padx=(0, 3))
        kb_wrap.pack_propagate(False)
        self._kb_btn = tk.Button(
            kb_wrap, text='\u2328', font=('Segoe UI Symbol', 12),
            fg=GREEN, bg=BORDER, activebackground='#30363d',
            activeforeground=GREEN, bd=0, relief='flat',
            command=self._toggle_kb)
        self._kb_btn.pack(fill='both', expand=True)

        _mfg = DIM if not mouse_module else RED
        mouse_wrap = tk.Frame(ctrl, bg=BORDER, width=SZ, height=SZ)
        mouse_wrap.pack(side=tk.LEFT, padx=(0, 8))
        mouse_wrap.pack_propagate(False)
        self._mouse_btn = tk.Button(
            mouse_wrap, text='\U0001f5b1', font=('Segoe UI Emoji', 10),
            fg=_mfg, bg=BORDER, activebackground='#30363d',
            activeforeground=_mfg, bd=0, relief='flat',
            command=self._toggle_mouse,
            state='normal' if mouse_module else 'disabled',
            disabledforeground=DIM)
        self._mouse_btn.pack(fill='both', expand=True)

        # Hotkey capture
        tk.Label(ctrl, text='Hotkey:', font=('Consolas', 8),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._hotkey_capture_btn = tk.Button(
            ctrl, text=_fmt_key(self.record_hotkey),
            font=('Consolas', 9, 'bold'),
            fg=ACCENT, bg=BG2, activebackground='#30363d',
            activeforeground=ACCENT, bd=0, relief='flat', width=4,
            command=self._start_hotkey_capture)
        self._hotkey_capture_btn.pack(side=tk.LEFT, padx=(4, 6))

        # Mode badge — single toggle: ● REC ↔ ▶ RPL
        self._mode_badge = tk.Button(
            ctrl, text='\u25cf REC',
            font=('Consolas', 8, 'bold'),
            fg='#0d1117', bg=RED, activebackground=RED,
            activeforeground='#0d1117', bd=0, relief='flat', padx=5, pady=1,
            command=self._toggle_hotkey_mode)
        self._mode_badge.pack(side=tk.LEFT)

        # Record action button
        self._rec_btn = tk.Button(
            ctrl, text='\u25cf Record',
            font=('Consolas', 9, 'bold'),
            fg=RED, bg=BORDER, activebackground='#30363d',
            activeforeground=RED, bd=0, relief='flat', padx=8, pady=2,
            command=self._toggle_recording)
        self._rec_btn.pack(side=tk.RIGHT)

        # ── Separator ─────────────────────────────────────────────────
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=(4, 0))

        # ── Action list ───────────────────────────────────────────────
        style = ttk.Style(panel)
        style.theme_use('clam')
        style_flat_treeview(style, 'Macro')

        tree_frame = tk.Frame(panel, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=12, pady=(4, 0))

        self._tree = ttk.Treeview(
            tree_frame, columns=('delay', 'action'), show='headings',
            style='Macro.Treeview', height=8, selectmode='extended')
        self._tree.heading('delay', text='Delay (s)')
        self._tree.heading('action', text='Action')
        self._tree.column('delay', width=80, anchor='center')
        self._tree.column('action', width=260, anchor='w')

        sb = ttk.Scrollbar(tree_frame, orient='vertical',
                           command=self._tree.yview,
                           style='Macro.Vertical.TScrollbar')
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill='both', expand=True)
        sb.pack(side=tk.RIGHT, fill='y')

        self._tree.bind('<Double-1>', self._on_action_double_click)

        # ── Action controls ───────────────────────────────────────────
        act_frame = tk.Frame(panel, bg=BG)
        act_frame.pack(fill='x', padx=12, pady=(4, 0))

        tk.Button(act_frame, text='Delete', font=('Consolas', 9),
                  fg=DIM, bg=BORDER, activebackground='#30363d',
                  bd=0, relief='flat', padx=6, pady=2,
                  command=self._delete_selected).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(act_frame, text='Clear All', font=('Consolas', 9),
                  fg=RED, bg=BORDER, activebackground='#30363d',
                  bd=0, relief='flat', padx=6, pady=2,
                  command=self._clear_all).pack(side=tk.LEFT)

        # ── Separator ─────────────────────────────────────────────────
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=6)

        # ── Replay controls ───────────────────────────────────────────
        play_frame = tk.Frame(panel, bg=BG)
        play_frame.pack(fill='x', padx=12, pady=(0, 6))

        self._play_btn = tk.Button(
            play_frame, text='\u25b6 Play',
            font=('Consolas', 9, 'bold'),
            fg=GREEN, bg=BORDER, activebackground='#30363d',
            activeforeground=GREEN, bd=0, relief='flat', padx=8, pady=2,
            command=self._toggle_replay)
        self._play_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._loop_btn = tk.Button(
            play_frame, text='Loop: OFF',
            font=('Consolas', 9),
            fg=DIM, bg=BORDER, activebackground='#30363d',
            activeforeground=DIM, bd=0, relief='flat', padx=6, pady=2,
            command=self._toggle_loop)
        self._loop_btn.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(play_frame, text='Interval:', font=('Consolas', 8),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._interval_var = tk.DoubleVar(value=1.0)
        tk.Entry(
            play_frame, textvariable=self._interval_var,
            font=('Consolas', 9), fg=ACCENT, bg=BG2,
            insertbackground=ACCENT, bd=0, relief='flat',
            width=4, justify='center').pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(play_frame, text='s', font=('Consolas', 8),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)

        # ── Separator ─────────────────────────────────────────────────
        tk.Frame(panel, bg=BORDER, height=1).pack(fill='x', padx=12, pady=(0, 6))

        # ── Saved macros ──────────────────────────────────────────────
        tk.Label(panel, text="SAVED MACROS",
                 font=("Consolas", 8, "bold"),
                 fg=DIM, bg=BG).pack(anchor='w', padx=12)

        saved_frame = tk.Frame(panel, bg=BG)
        saved_frame.pack(fill='x', padx=12, pady=(2, 4))

        self._listbox = tk.Listbox(
            saved_frame, font=('Consolas', 9), fg=TEXT, bg=BG2,
            selectbackground='#1f6feb', selectforeground='#ffffff',
            height=4, bd=0, highlightthickness=1, highlightcolor=BORDER,
            highlightbackground=BORDER)
        self._listbox.pack(fill='x')
        self._listbox.bind('<<ListboxSelect>>', self._on_saved_select)

        btn_frame = tk.Frame(panel, bg=BG)
        btn_frame.pack(fill='x', padx=12, pady=(0, 8))

        for text, cmd in [('Save As', self._save_as),
                          ('Load', self._load_selected),
                          ('Rename', self._rename_selected),
                          ('Delete', self._delete_saved)]:
            tk.Button(btn_frame, text=text, font=('Consolas', 9),
                      fg=DIM, bg=BORDER, activebackground='#30363d',
                      bd=0, relief='flat', padx=6, pady=2,
                      command=cmd).pack(side=tk.LEFT, padx=(0, 4))

        self._refresh_action_list()
        self._refresh_saved_list()

    def _toggle_kb(self):
        self.record_kb = not self.record_kb
        if self.panel:
            fg = GREEN if self.record_kb else RED
            self._kb_btn.config(fg=fg, activeforeground=fg)

    def _toggle_mouse(self):
        if not mouse_module:
            return
        self.record_mouse = not self.record_mouse
        if self.panel:
            fg = GREEN if self.record_mouse else RED
            self._mouse_btn.config(fg=fg, activeforeground=fg)

    def _toggle_loop(self):
        self.looping = not self.looping
        if self.panel:
            if self.looping:
                self._loop_btn.config(text='Loop: ON', fg=GREEN,
                                       activeforeground=GREEN)
            else:
                self._loop_btn.config(text='Loop: OFF', fg=DIM,
                                       activeforeground=DIM)

    def _toggle_hotkey_mode(self):
        DARK = '#0d1117'
        if self.hotkey_mode == 'record':
            self.hotkey_mode = 'replay'
            if self.panel and hasattr(self, '_mode_badge'):
                self._mode_badge.config(
                    text='\u25b6 RPL', fg=DARK, bg=GREEN,
                    activebackground=GREEN, activeforeground=DARK)
        else:
            self.hotkey_mode = 'record'
            if self.panel and hasattr(self, '_mode_badge'):
                self._mode_badge.config(
                    text='\u25cf REC', fg=DARK, bg=RED,
                    activebackground=RED, activeforeground=DARK)

    def _start_hotkey_capture(self):
        if getattr(self, '_hotkey_capturing', False):
            return
        self._hotkey_capturing = True
        self._hotkey_capture_btn.config(text='Press key...', fg='#f0c674')
        self._capture_hook = keyboard.on_press(
            self._on_hotkey_capture, suppress=False)

    def _on_hotkey_capture(self, event):
        new_key = event.name
        keyboard.unhook(self._capture_hook)
        self._hotkey_capturing = False
        self.hub.root.after(
            0, lambda: self._apply_hotkey(new_key))

    def _apply_hotkey(self, new_key):
        old_key = self.record_hotkey
        if new_key == old_key:
            self._hotkey_capture_btn.config(text=_fmt_key(new_key), fg=ACCENT)
            return
        if self._hotkey_id is not None:
            try:
                keyboard.unhook(self._hotkey_id)
            except Exception:
                pass
        self.record_hotkey = new_key
        self._hotkey_capture_btn.config(text=_fmt_key(new_key), fg=ACCENT)
        try:
            self._hotkey_id = keyboard.on_press_key(
                new_key, lambda e: self._hotkey_dispatch())
        except Exception as e:
            print(f"[MACRO] Hotkey error: {e}")
        print(f"[MACRO] Record hotkey changed to '{new_key}'")

    def _refresh_action_list(self):
        if not self.panel or not hasattr(self, '_tree'):
            return
        try:
            tree = self._tree
            tree.delete(*tree.get_children())
            for i, action in enumerate(self.actions):
                delay_str = f"{action['delay']:.3f}"
                act_type = action['type']
                if act_type in ('key_down', 'key_up'):
                    arrow = '\u2193' if act_type == 'key_down' else '\u2191'
                    desc = f"{arrow} {action.get('key', '?')}"
                elif act_type == 'mouse_move':
                    desc = (f"\u2192 move ({action.get('x', '?')}, "
                            f"{action.get('y', '?')})")
                elif act_type in ('mouse_down', 'mouse_up'):
                    arrow = '\u2193' if act_type == 'mouse_down' else '\u2191'
                    btn = action.get('button', '?')
                    pos = f"({action.get('x', '?')}, {action.get('y', '?')})"
                    desc = f"{arrow} {btn} click {pos}"
                else:
                    desc = act_type
                tree.insert('', 'end', iid=str(i), values=(delay_str, desc))
            children = tree.get_children()
            if children:
                tree.see(children[-1])
        except Exception:
            pass

    def _refresh_saved_list(self):
        if not self.panel or not hasattr(self, '_listbox'):
            return
        try:
            self._listbox.delete(0, tk.END)
            for name in sorted(self.saved.keys()):
                count = len(self.saved[name])
                self._listbox.insert(tk.END, f"{name} ({count} actions)")
        except Exception:
            pass

    def _on_saved_select(self, event):
        sel = self._listbox.curselection()
        if sel:
            text = self._listbox.get(sel[0])
            name = text.rsplit(' (', 1)[0]
            self.selected_name = name
        else:
            self.selected_name = None

    def _on_action_double_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        if region != 'cell':
            return
        col = self._tree.identify_column(event.x)
        if col != '#1':
            return
        item = self._tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        if idx >= len(self.actions):
            return

        bbox = self._tree.bbox(item, col)
        if not bbox:
            return

        x, y, w, h = bbox
        entry = tk.Entry(self._tree, font=('Consolas', 9),
                         fg=ACCENT, bg=BG2, insertbackground=ACCENT,
                         bd=0, justify='center')
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, f"{self.actions[idx]['delay']:.3f}")
        entry.select_range(0, tk.END)
        entry.focus()

        def commit(e=None):
            try:
                val = float(entry.get())
                if val < 0:
                    val = 0
                self.actions[idx]['delay'] = round(val, 4)
            except ValueError:
                pass
            entry.destroy()
            self._refresh_action_list()

        entry.bind('<Return>', commit)
        entry.bind('<FocusOut>', commit)
        entry.bind('<Escape>',
                   lambda e: (entry.destroy(), self._refresh_action_list()))

    def _delete_selected(self):
        if not hasattr(self, '_tree'):
            return
        selected = self._tree.selection()
        if not selected:
            return
        indices = sorted([int(s) for s in selected], reverse=True)
        for idx in indices:
            if 0 <= idx < len(self.actions):
                del self.actions[idx]
        self._refresh_action_list()

    def _clear_all(self):
        self.actions = []
        self._refresh_action_list()

    def _highlight_action(self, idx):
        if not self.panel or not hasattr(self, '_tree'):
            return
        try:
            tree = self._tree
            for item in tree.get_children():
                tree.item(item, tags=())
            if 0 <= idx < len(self.actions):
                item_id = str(idx)
                if tree.exists(item_id):
                    tree.item(item_id, tags=('playing',))
                    tree.tag_configure('playing', background='#1f6feb',
                                       foreground='#ffffff')
                    tree.see(item_id)
        except Exception:
            pass

    def _save_as(self):
        if not self.actions:
            return
        name = ThemedModal.ask_string(self.panel, "Save Macro", "Macro name:")
        if not name:
            return
        self.saved[name] = [dict(a) for a in self.actions]
        self.save_macros()
        self._refresh_saved_list()

    def _load_selected(self):
        if not self.selected_name or self.selected_name not in self.saved:
            return
        if self.recording:
            self._stop_recording()
        if self.replaying:
            self._stop_replay()
        self.actions = [dict(a) for a in self.saved[self.selected_name]]
        self._refresh_action_list()

    def _rename_selected(self):
        if not self.selected_name or self.selected_name not in self.saved:
            return
        old = self.selected_name
        new = ThemedModal.ask_string(self.panel, "Rename Macro", "New name:",
                                     initial=old)
        if not new or new == old:
            return
        self.saved[new] = self.saved.pop(old)
        self.selected_name = new
        self.save_macros()
        self._refresh_saved_list()

    def _delete_saved(self):
        if not self.selected_name or self.selected_name not in self.saved:
            return
        del self.saved[self.selected_name]
        self.selected_name = None
        self.save_macros()
        self._refresh_saved_list()

    def cleanup(self):
        """Clean up on exit."""
        if self.recording:
            self._stop_recording()
        if self.replaying:
            self._stop_replay()
        self.stop()
