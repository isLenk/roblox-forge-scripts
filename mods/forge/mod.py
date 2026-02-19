"""Forge game mod — circle detection, smelting, bar game, auto-phase."""

import tkinter as tk
from pathlib import Path
from threading import Thread

import sys as _sys
_ASSETS = (Path(_sys._MEIPASS) if hasattr(_sys, '_MEIPASS')
           else Path(__file__).resolve().parent.parent.parent) / 'assets'

from mods.base import GameMod
from mods.forge.circle_detect import CircleDetector
from mods.forge.cursor_jiggle import CursorJiggle
from mods.forge.bar_game import BarGame
from mods.forge.go_detector import GoDetector
from components.autoclicker import AutoclickerComponent
from components.sprint import SprintComponent
from components.hold_key import HoldKeyComponent
from components.periodic_attack import PeriodicAttackComponent
from components.auto_sell import AutoSellComponent
from components.macro_editor import MacroEditorComponent
from core.theme import (BG, BG2, BG_DARK, BORDER, DIM, ACCENT, GREEN, RED, TEXT,
                        make_dotted_bg, apply_glass, make_glass_dynamic,
                        apply_rounded_corners)
from version import VERSION


class ForgeMod(GameMod):
    MOD_ID = "forge"
    MOD_NAME = "Forge"
    GAME_PLACE_IDS = []
    WIKI_URL = "https://forge-roblox.fandom.com/wiki"

    def __init__(self, hub):
        super().__init__(hub)
        self.forge_enabled = False
        self.auto_phase = False
        self.phase_idx = 0
        self.debug = False
        self._auto_sell_overlays = []

    def init(self):
        """Register components and forge-specific features."""
        # Components
        self.autoclicker = self.use_component(
            AutoclickerComponent, interval=0.1)
        self.sprint = self.use_component(SprintComponent)
        self.hold_left = self.use_component(
            HoldKeyComponent,
            scan_code=0x4B, extended=True,
            display_name="Hold Left Arrow")
        self.periodic_attack = self.use_component(
            PeriodicAttackComponent,
            key1='2', key2='1', delay_after_key1=1.0, cycle_period=3.0)
        self.auto_sell = self.use_component(
            AutoSellComponent,
            open_stash_key='t',
            steps=[('sell_items', 'Sell Items'),
                   ('select_all', 'Select All'),
                   ('accept', 'Accept'),
                   ('yes', 'Yes'),
                   ('close', 'X (close)')],
            step_delays={'yes': 4.0},
            default_interval=300)
        self.macro_editor = self.use_component(MacroEditorComponent)

        # Forge-specific features
        self.circle_detector = CircleDetector(self.hub, self)
        self.cursor_jiggle = CursorJiggle(self.hub, self)
        self.bar_game = BarGame(self.hub, self)
        self.go_detector = GoDetector(self.hub, self)

        # Load saved auto-sell data
        as_data = self.hub.config.get('mods', 'forge', 'auto_sell')
        if as_data:
            self.auto_sell.load_positions(as_data)

    def start(self):
        """Start only the GO detector (passive background watcher).

        Components and other detectors are activated by user interaction.
        """
        self.go_detector.start()
        self.macro_editor.start()

    def stop(self):
        """Stop all components and forge threads."""
        super().stop()
        self.circle_detector.stop()
        self.cursor_jiggle.stop()
        self.bar_game.stop()

    def build_gui(self, parent):
        """Create the forge mod window."""
        root_x = parent.winfo_x()
        root_y = parent.winfo_y()

        win = tk.Toplevel(parent)
        win.overrideredirect(True)
        win.geometry(f"350x400+{root_x}+{root_y}")
        win.attributes('-topmost', True)
        win.resizable(False, False)
        win.configure(bg=BG)
        apply_glass(win)
        make_glass_dynamic(win)
        apply_rounded_corners(win)
        self._window = win

        # Window icon (taskbar / Alt+Tab)
        _ico = _ASSETS / 'icon.ico'
        if _ico.exists():
            try:
                win.iconbitmap(str(_ico))
            except Exception:
                pass

        # Force taskbar entry for overrideredirect window (Windows)
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            win.withdraw()
            win.after(10, win.deiconify)
        except Exception:
            pass

        # Dotted background
        W, H = 350, 400
        self._bg_img = make_dotted_bg(W, H)
        tk.Label(win, image=self._bg_img, bd=0).place(
            x=0, y=0, relwidth=1, relheight=1)

        # Title bar
        titlebar = tk.Frame(win, bg=BG, height=30)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        # Logo image (falls back to text if asset missing)
        _logo_file = _ASSETS / 'logo.png'
        if _logo_file.exists():
            try:
                from PIL import Image, ImageEnhance, ImageTk
                _limg = Image.open(str(_logo_file))
                lh = 14
                lw = round(_limg.width * lh / _limg.height)
                _limg = _limg.resize((lw, lh), Image.LANCZOS)
                _limg = ImageEnhance.Brightness(_limg).enhance(0.45)
                self._logo_photo = ImageTk.PhotoImage(_limg)
                tk.Label(titlebar, image=self._logo_photo,
                         bg=BG, bd=0).pack(side=tk.LEFT, padx=(10, 6))
            except Exception:
                tk.Label(titlebar, text="LENK.TOOLS",
                         font=("Consolas", 9, "bold"),
                         fg=DIM, bg=BG).pack(side=tk.LEFT, padx=(10, 6))
        else:
            tk.Label(titlebar, text="LENK.TOOLS",
                     font=("Consolas", 9, "bold"),
                     fg=DIM, bg=BG).pack(side=tk.LEFT, padx=(10, 6))
        tk.Label(titlebar, text=f"v{VERSION}",
                 font=("Consolas", 8), fg='#30363d', bg=BG).pack(side=tk.LEFT)

        # Close button
        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: self.hub._quit())
        close_btn.bind('<Enter>',
                       lambda e: close_btn.config(fg=RED, bg='#1a0000'))
        close_btn.bind('<Leave>',
                       lambda e: close_btn.config(fg=DIM, bg=BG))

        # Minimize button
        min_btn = tk.Label(
            titlebar, text='\u2500', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        min_btn.pack(side=tk.RIGHT, fill='y')
        min_btn.bind('<Button-1>', lambda e: self.hub._minimize())
        min_btn.bind('<Enter>',
                     lambda e: min_btn.config(fg='#c9d1d9', bg=BG2))
        min_btn.bind('<Leave>',
                     lambda e: min_btn.config(fg=DIM, bg=BG))

        # Update button
        self._update_btn = tk.Label(
            titlebar, text='\u21BB', font=('Segoe UI', 11),
            fg=DIM, bg=BG, padx=4, cursor='hand2')
        self._update_btn.pack(side=tk.LEFT)
        self._update_btn.bind('<Button-1>',
                              lambda e: self.hub._run_in_app_update())
        self._update_btn.bind('<Enter>',
            lambda e: self._update_btn.config(fg=ACCENT, bg=BG2))
        self._update_btn.bind('<Leave>',
            lambda e: self._update_btn.config(
                fg=getattr(self._update_btn, '_rest_fg', DIM), bg=BG))
        self._update_btn._rest_fg = DIM

        # Dragging
        def _start_drag(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def _on_drag(event):
            x = win.winfo_x() + event.x - self._drag_x
            y = win.winfo_y() + event.y - self._drag_y
            win.geometry(f"+{x}+{y}")

        titlebar.bind('<Button-1>', _start_drag)
        titlebar.bind('<B1-Motion>', _on_drag)

        # Header bar
        header = tk.Frame(win, bg=BG_DARK)
        header.pack(fill='x')

        self.focus_lbl = tk.Label(
            header, text="\u25CF  ROBLOX: --",
            font=("Consolas", 10, "bold"), fg="#888888", bg=BG_DARK)
        self.focus_lbl.pack(pady=(6, 0))

        self.game_lbl = tk.Label(
            header, text="\u25CB  Game: --",
            font=("Consolas", 9), fg="#888888", bg=BG_DARK)
        self.game_lbl.pack(pady=(0, 5))

        # --- Tab bar (Canvas with rounded folder tabs) ---
        _TAB_NAMES = ('Forge', 'Automation', 'QOL', 'Settings')
        _TAB_W, _TAB_H, _TAB_R = 350, 32, 6
        _EACH_W = _TAB_W // len(_TAB_NAMES)

        self._active_tab = 'Forge'
        tab_canvas = tk.Canvas(win, width=_TAB_W, height=_TAB_H, bg=BG_DARK,
                               highlightthickness=0, bd=0, cursor='hand2')
        tab_canvas.pack(fill='x')
        self._tab_canvas = tab_canvas

        def _draw_tab_bar(hovered=None):
            tab_canvas.delete('all')
            for i, name in enumerate(_TAB_NAMES):
                x1 = i * _EACH_W
                x2 = (i + 1) * _EACH_W if i < len(_TAB_NAMES) - 1 else _TAB_W
                is_active = name == self._active_tab
                is_hov = name == hovered and not is_active
                if is_active:
                    fill, ty = BG, 1
                elif is_hov:
                    fill, ty = '#1c2128', 4
                else:
                    fill, ty = BG_DARK, 5
                y1, y2 = ty, _TAB_H
                r = _TAB_R
                # Fill: rounded top corners + body
                tab_canvas.create_arc(x1+1, y1, x1+1+2*r, y1+2*r,
                                      start=90, extent=90, fill=fill, outline=fill)
                tab_canvas.create_arc(x2-1-2*r, y1, x2-1, y1+2*r,
                                      start=0, extent=90, fill=fill, outline=fill)
                tab_canvas.create_rectangle(x1+1+r, y1, x2-1-r, y1+r,
                                            fill=fill, outline='')
                tab_canvas.create_rectangle(x1+1, y1+r, x2-1, y2,
                                            fill=fill, outline='')
                # Border (left, arc-top-left, top, arc-top-right, right)
                tab_canvas.create_line(x1+1, y1+r-1, x1+1, y2, fill=BORDER)
                tab_canvas.create_arc(x1+1, y1, x1+1+2*r, y1+2*r,
                                      start=90, extent=90, style='arc', outline=BORDER)
                tab_canvas.create_line(x1+1+r, y1, x2-1-r, y1, fill=BORDER)
                tab_canvas.create_arc(x2-1-2*r, y1, x2-1, y1+2*r,
                                      start=0, extent=90, style='arc', outline=BORDER)
                tab_canvas.create_line(x2-1, y1+r-1, x2-1, y2, fill=BORDER)
                # Active: cover bottom separator
                if is_active:
                    tab_canvas.create_rectangle(x1+2, y2-1, x2-2, y2,
                                                fill=BG, outline='')
                # Text
                cx, cy = (x1 + x2) // 2, (y1 + y2 + 2) // 2
                fg = TEXT if is_active else (TEXT if is_hov else DIM)
                tab_canvas.create_text(cx, cy, text=name,
                                       font=('Consolas', 9, 'bold'), fill=fg)
            # Bottom separator; broken at active tab
            tab_canvas.create_rectangle(0, _TAB_H-1, _TAB_W, _TAB_H,
                                        fill=BORDER, outline='')
            ai = _TAB_NAMES.index(self._active_tab)
            tab_canvas.create_rectangle(ai * _EACH_W + 2, _TAB_H-1,
                                        ((ai+1)*_EACH_W if ai < len(_TAB_NAMES)-1
                                         else _TAB_W) - 2,
                                        _TAB_H, fill=BG, outline='')

        self._draw_tab_bar = _draw_tab_bar

        def _tab_idx(x):
            return max(0, min(int(x * len(_TAB_NAMES) / _TAB_W),
                              len(_TAB_NAMES) - 1))

        tab_canvas.bind('<Motion>',
                        lambda e: _draw_tab_bar(hovered=_TAB_NAMES[_tab_idx(e.x)]))
        tab_canvas.bind('<Leave>', lambda e: _draw_tab_bar())
        tab_canvas.bind('<Button-1>',
                        lambda e: self._switch_tab(_TAB_NAMES[_tab_idx(e.x)]))
        win.after(1, _draw_tab_bar)

        # Footer (packed before tab container so tkinter allocates bottom space)
        footer_wrap = tk.Frame(win, bg=BG)
        footer_wrap.pack(side=tk.BOTTOM, fill='x')

        # Grey separator line above footer
        tk.Frame(footer_wrap, bg=BORDER, height=1).pack(fill='x')

        bottom_frame = tk.Frame(footer_wrap, bg=BG)
        bottom_frame.pack(fill='x', pady=4)

        _btn_kw = dict(font=('Consolas', 10, 'bold'), bd=0, relief='flat',
                       bg=BG, activebackground=BG2, padx=10, pady=5,
                       cursor='hand2')

        def _hover_btn(btn, fg):
            btn.bind('<Enter>', lambda e: btn.config(bg=BG2))
            btn.bind('<Leave>', lambda e: btn.config(bg=BG))

        def _divider(parent):
            """Short vertical grey divider that doesn't reach top/bottom."""
            d = tk.Frame(parent, bg=BG, width=1)
            d.pack(side=tk.LEFT, fill='y', pady=6)
            tk.Frame(d, bg=BORDER, width=1).pack(fill='both', expand=True)

        self.hotkey_btn = tk.Button(
            bottom_frame, text='Hotkeys: ON',
            fg=GREEN, activeforeground=GREEN, **_btn_kw,
            command=self._toggle_hotkeys)
        self.hotkey_btn.pack(side=tk.LEFT, expand=True)
        _hover_btn(self.hotkey_btn, GREEN)

        _divider(bottom_frame)

        self.macro_btn = tk.Button(
            bottom_frame, text='\u2630 Macro Editor',
            fg='#bd93f9', activeforeground='#bd93f9', **_btn_kw,
            command=lambda: self.macro_editor.toggle_panel(win))
        self.macro_btn.pack(side=tk.LEFT, expand=True)
        _hover_btn(self.macro_btn, '#bd93f9')

        _divider(bottom_frame)

        self.wiki_btn = tk.Button(
            bottom_frame, text='\U0001f4d6 Wiki',
            fg=ACCENT, activeforeground=ACCENT, **_btn_kw,
            command=self.hub._toggle_wiki_panel)
        self.wiki_btn.pack(side=tk.LEFT, expand=True)
        _hover_btn(self.wiki_btn, ACCENT)

        _divider(bottom_frame)

        self.debug_btn = tk.Button(
            bottom_frame, text='\U0001f41b', font=('Segoe UI Emoji', 10),
            fg=DIM, bg=BG, activebackground=BG2,
            activeforeground=RED, bd=0, relief='flat', padx=6, pady=4,
            cursor='hand2', command=self._toggle_debug)
        self.debug_btn.pack(side=tk.LEFT, padx=(0, 4))
        self.debug_btn.bind('<Enter>', lambda e: self.debug_btn.config(bg=BG2))
        self.debug_btn.bind('<Leave>', lambda e: self.debug_btn.config(bg=BG))

        # Tab container
        self._tab_container = tk.Frame(win, bg=BG)
        self._tab_container.pack(fill='both', expand=True)

        self._tab_frames = {}
        for name in ('Forge', 'Automation', 'QOL', 'Settings'):
            frame = tk.Frame(self._tab_container, bg=BG)
            tk.Label(frame, image=self._bg_img, bd=0).place(
                x=0, y=0, relwidth=1, relheight=1)
            self._tab_frames[name] = frame

        # Hotkey UI references (populated by pipeline + controls)
        self._hotkey_ui = {}

        # --- Forge tab ---
        forge_frame = self._tab_frames['Forge']
        self._build_pipeline(forge_frame)

        phase_frame = tk.Frame(forge_frame, bg=BG)
        phase_frame.pack(fill='x', padx=20, pady=(2, 0))
        self._phase_dot, self.phase_lbl, self._phase_hint = self._ctrl_row(
            phase_frame, 'Auto-Phase: OFF', '[U]',
            lambda: self.toggle_auto_phase(force=True))

        # --- Automation tab ---
        auto_frame = self._tab_frames['Automation']
        self._build_auto_sell_section(auto_frame)
        self._build_periodic_attack_section(auto_frame)

        # --- QOL tab ---
        qol_frame = self._tab_frames['QOL']
        ctrl = tk.Frame(qol_frame, bg=BG)
        ctrl.pack(pady=(8, 0), fill='x', padx=20)

        self._autoclick_dot, self.autoclick_lbl, self._autoclick_hint = self._ctrl_row(
            ctrl, 'Autoclick: OFF', '[F5]',
            lambda: self._toggle_autoclicker(force=True))
        self._holdleft_dot, self.holdleft_lbl, self._holdleft_hint = self._ctrl_row(
            ctrl, 'Hold Left: OFF', '[F6]',
            lambda: self._toggle_hold_left(force=True))
        self._sprint_dot, self.sprint_lbl, self._sprint_hint = self._ctrl_row(
            ctrl, 'Sprint: OFF', '[CapsLk]',
            lambda: self._toggle_sprint(force=True))

        # Hotkey rebind click handlers
        for hotkey_name, hint_widget in [
                ('auto_phase', self._phase_hint),
                ('autoclicker', self._autoclick_hint),
                ('hold_left', self._holdleft_hint),
                ('sprint', self._sprint_hint)]:
            hint_widget.config(cursor='hand2')
            hint_widget.bind('<Button-1>',
                             lambda e, n=hotkey_name: self._start_key_rebind(n))
            self._hotkey_ui[hotkey_name] = {
                'type': 'label', 'widget': hint_widget}

        # --- Settings tab ---
        self._build_settings_tab(self._tab_frames['Settings'])

        # Show default tab (Forge)
        self._tab_frames['Forge'].pack(fill='both', expand=True)

        # Overlays for bar game
        self._bar_ov = self._make_arrow_overlay(win, 'BAR')
        self._slit_ov = self._make_arrow_overlay(win, 'SLIT')
        for attr in ('_col_left_ov', '_col_right_ov', '_bot_ov'):
            ov = tk.Toplevel(win)
            ov.overrideredirect(True)
            ov.attributes('-topmost', True)
            ov.configure(bg='#ff2222')
            ov.geometry("2x100+0+0")
            ov.withdraw()
            setattr(self, attr, ov)

        # Ring overlay for circle detection
        ring_d = 85
        self._ring_size = ring_d
        self._ring_ov = tk.Toplevel(win)
        self._ring_ov.overrideredirect(True)
        self._ring_ov.attributes('-topmost', True)
        self._ring_ov.attributes('-transparentcolor', '#000000')
        self._ring_ov.configure(bg='#000000')
        self._ring_ov.geometry(f"{ring_d}x{ring_d}+0+0")
        self._ring_cvs = tk.Canvas(
            self._ring_ov, width=ring_d, height=ring_d,
            bg='#000000', highlightthickness=0)
        self._ring_cvs.pack()
        pad = 3
        self._ring_id = self._ring_cvs.create_oval(
            pad, pad, ring_d - pad, ring_d - pad,
            outline='#ff2222', width=3, fill='#000000')
        self._ring_ov.withdraw()

        self._dtimer_ov = tk.Toplevel(win)
        self._dtimer_ov.overrideredirect(True)
        self._dtimer_ov.attributes('-topmost', True)
        self._dtimer_ov.attributes('-transparentcolor', '#000000')
        self._dtimer_ov.configure(bg='#000000')
        self._dtimer_ov.geometry("100x25+0+0")
        self._dtimer_lbl = tk.Label(
            self._dtimer_ov, text="",
            font=("Consolas", 12, "bold"), fg="#ff2222", bg='#000000')
        self._dtimer_lbl.pack()
        self._dtimer_ov.withdraw()

        # Start focus polling
        self._update_focus_label()

        return win

    # ---- Helper builders ----
    def _ctrl_row(self, parent, text, key_text, command=None):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill='x', pady=2)
        dot = tk.Label(row, text='\u25CF', font=('Segoe UI', 8),
                       fg=RED, bg=BG)
        dot.pack(side=tk.LEFT, padx=(8, 6))
        lbl = tk.Label(row, text=text, font=('Consolas', 11, 'bold'),
                       fg=DIM, bg=BG, anchor='w')
        lbl.pack(side=tk.LEFT, fill='x', expand=True)
        hint = tk.Label(row, text=key_text, font=('Consolas', 9),
                        fg='#30363d', bg=BG, anchor='e')
        hint.pack(side=tk.RIGHT, padx=(0, 8))
        if command:
            for widget in (dot, lbl, row):
                widget.bind('<Button-1>', lambda e, cmd=command: cmd())
                widget.config(cursor='hand2')
        return dot, lbl, hint

    def _build_pipeline(self, parent):
        pipe_w, pipe_h = 340, 82
        self.pipe_canvas = tk.Canvas(
            parent, width=pipe_w, height=pipe_h,
            bg=BG, highlightthickness=0)
        self.pipe_canvas.pack(pady=(6, 0))

        cy = 24
        r = 18
        positions = [38, 118, 208, 298]
        icons = ['\u2195', '\u2261', '\u25C8', '\u25CE']
        labels = ['Smelting', 'Casting', 'Shaping', 'Welding']
        keys = ['I', 'O', '', 'P']

        self._pipe_lines = []
        self._pipe_circles = []
        self._pipe_icons = []
        self._pipe_labels = []
        self._pipe_keys = []

        for i in range(len(positions) - 1):
            line = self.pipe_canvas.create_line(
                positions[i] + r + 3, cy,
                positions[i + 1] - r - 3, cy,
                width=3, fill=BORDER, capstyle='round')
            self._pipe_lines.append(line)

        _pipe_hotkey_names = {0: 'jiggle', 1: 'bar_game', 3: 'circle'}

        for i, (x, icon, label, key) in enumerate(
                zip(positions, icons, labels, keys)):
            glow = self.pipe_canvas.create_oval(
                x - r - 3, cy - r - 3, x + r + 3, cy + r + 3,
                fill='', outline='', width=0)
            circle = self.pipe_canvas.create_oval(
                x - r, cy - r, x + r, cy + r,
                fill=BG2, outline='#30363d', width=2)
            icon_id = self.pipe_canvas.create_text(
                x, cy, text=icon,
                font=('Segoe UI', 14, 'bold'), fill=DIM)
            label_id = self.pipe_canvas.create_text(
                x, cy + r + 12, text=label,
                font=('Consolas', 9), fill=DIM)
            key_id = self.pipe_canvas.create_text(
                x, cy + r + 25, text=f'[{key}]',
                font=('Consolas', 8, 'bold'), fill='#30363d')
            self._pipe_circles.append((glow, circle))
            self._pipe_icons.append(icon_id)
            self._pipe_labels.append(label_id)
            self._pipe_keys.append(key_id)

        for i in range(4):
            tag = f'node_{i}'
            glow_id, circle_id = self._pipe_circles[i]
            for item_id in [glow_id, circle_id, self._pipe_icons[i],
                            self._pipe_labels[i]]:
                self.pipe_canvas.addtag_withtag(tag, item_id)
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
                lambda e, idx=i: self._on_node_click(idx, force=True))
            self.pipe_canvas.tag_bind(
                tag, '<Enter>',
                lambda e: self.pipe_canvas.config(cursor='hand2'))
            self.pipe_canvas.tag_bind(
                tag, '<Leave>',
                lambda e: self.pipe_canvas.config(cursor=''))

        pipe_w_full = 340
        self._forge_off_overlay = self.pipe_canvas.create_text(
            pipe_w_full // 2, cy, text='FORGE OFF',
            font=('Consolas', 18, 'bold'), fill=RED, state='hidden')

    def _build_auto_sell_section(self, parent):
        as_frame = tk.Frame(parent, bg=BG)
        as_frame.pack(fill='x', padx=20, pady=(6, 0))

        as_toggle_row = tk.Frame(as_frame, bg=BG)
        as_toggle_row.pack(fill='x', pady=2)
        self._as_dot = tk.Label(as_toggle_row, text='\u25CF',
                                font=('Segoe UI', 8), fg=RED, bg=BG)
        self._as_dot.pack(side=tk.LEFT, padx=(8, 6))
        self.as_lbl = tk.Label(as_toggle_row, text='Auto Sell: OFF',
                               font=('Consolas', 10, 'bold'), fg=DIM, bg=BG,
                               anchor='w')
        self.as_lbl.pack(side=tk.LEFT, fill='x', expand=True)

        tk.Button(as_toggle_row, text='Setup', font=('Consolas', 9, 'bold'),
                  fg=ACCENT, bg=BG2, activebackground='#30363d',
                  activeforeground=ACCENT, bd=0, relief='flat', cursor='hand2',
                  command=lambda: self.auto_sell.setup(self._window)
                  ).pack(side=tk.RIGHT, padx=(4, 8))

        camlock_color = GREEN if self.auto_sell.camlock else DIM
        self._as_camlock_btn = tk.Button(
            as_toggle_row, text='Camlock', font=('Consolas', 9, 'bold'),
            fg=camlock_color, bg=BG2, activebackground='#30363d',
            activeforeground=camlock_color, bd=0, relief='flat',
            cursor='hand2', command=self._toggle_auto_sell_camlock)
        self._as_camlock_btn.pack(side=tk.RIGHT, padx=(4, 0))

        for w in (self._as_dot, self.as_lbl, as_toggle_row):
            w.bind('<Button-1>', lambda e: self._toggle_auto_sell())
            w.config(cursor='hand2')

        as_slider_row = tk.Frame(as_frame, bg=BG)
        as_slider_row.pack(fill='x', pady=(2, 0), padx=(14, 8))

        self._as_interval_lbl = tk.Label(
            as_slider_row,
            text=AutoSellComponent.fmt_interval(self.auto_sell.interval),
            font=('Consolas', 9), fg='#8b949e', bg=BG, width=7, anchor='w')
        self._as_interval_lbl.pack(side=tk.LEFT)

        self._as_slider = tk.Scale(
            as_slider_row, from_=30, to=1800, orient=tk.HORIZONTAL,
            bg=BG, fg='#8b949e', troughcolor=BG2, highlightthickness=0,
            bd=0, sliderrelief='flat', showvalue=False,
            command=self._on_auto_sell_slider)
        self._as_slider.set(self.auto_sell.interval)
        self._as_slider.pack(side=tk.LEFT, fill='x', expand=True)

    def _build_periodic_attack_section(self, parent):
        pa_frame = tk.Frame(parent, bg=BG)
        pa_frame.pack(fill='x', padx=20, pady=(6, 0))

        pa_toggle_row = tk.Frame(pa_frame, bg=BG)
        pa_toggle_row.pack(fill='x', pady=2)
        self._pa_dot = tk.Label(pa_toggle_row, text='\u25CF',
                                font=('Segoe UI', 8), fg=RED, bg=BG)
        self._pa_dot.pack(side=tk.LEFT, padx=(8, 6))
        self.pa_lbl = tk.Label(pa_toggle_row, text='Periodic Attack: OFF',
                               font=('Consolas', 10, 'bold'), fg=DIM, bg=BG,
                               anchor='w')
        self.pa_lbl.pack(side=tk.LEFT, fill='x', expand=True)
        for w in (self._pa_dot, self.pa_lbl, pa_toggle_row):
            w.bind('<Button-1>', lambda e: self._toggle_periodic_attack())
            w.config(cursor='hand2')

        pa_cols = tk.Frame(pa_frame, bg=BG)
        pa_cols.pack(fill='x', pady=(2, 0), padx=(14, 8))

        # Sword column
        sword_col = tk.Frame(pa_cols, bg=BG)
        sword_col.pack(side=tk.LEFT, expand=True, fill='x')
        sword_top = tk.Frame(sword_col, bg=BG)
        sword_top.pack()
        tk.Label(sword_top, text='\u2694', font=('Segoe UI', 16),
                 fg=RED, bg=BG).pack(side=tk.LEFT)
        self._pa_time1_var = tk.StringVar(value='1.0')
        tk.Entry(sword_top, textvariable=self._pa_time1_var, width=4,
                 font=('Consolas', 10, 'bold'), fg=ACCENT, bg=BG2,
                 insertbackground=ACCENT, bd=1, relief='flat',
                 justify='center').pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(sword_top, text='s', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._pa_key1_var = tk.StringVar(value='2')
        kc1_outer = tk.Frame(sword_col, bg=DIM)
        kc1_outer.pack(pady=(4, 0), anchor='w', padx=(4, 0))
        kc1_inner = tk.Frame(kc1_outer, bg='#30363d')
        kc1_inner.pack(padx=1, pady=(1, 2))
        tk.Entry(kc1_inner, textvariable=self._pa_key1_var, width=2,
                 font=('Consolas', 11, 'bold'), fg='#c9d1d9', bg=BG2,
                 insertbackground=ACCENT, bd=0, relief='flat',
                 justify='center').pack(padx=3, pady=2)

        # Pickaxe column
        pick_col = tk.Frame(pa_cols, bg=BG)
        pick_col.pack(side=tk.LEFT, expand=True, fill='x')
        pick_top = tk.Frame(pick_col, bg=BG)
        pick_top.pack()
        tk.Label(pick_top, text='\u26CF', font=('Segoe UI', 16),
                 fg=GREEN, bg=BG).pack(side=tk.LEFT)
        self._pa_time2_var = tk.StringVar(value='2.0')
        tk.Entry(pick_top, textvariable=self._pa_time2_var, width=4,
                 font=('Consolas', 10, 'bold'), fg=ACCENT, bg=BG2,
                 insertbackground=ACCENT, bd=1, relief='flat',
                 justify='center').pack(side=tk.LEFT, padx=(4, 0))
        tk.Label(pick_top, text='s', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._pa_key2_var = tk.StringVar(value='1')
        kc2_outer = tk.Frame(pick_col, bg=DIM)
        kc2_outer.pack(pady=(4, 0), anchor='w', padx=(4, 0))
        kc2_inner = tk.Frame(kc2_outer, bg='#30363d')
        kc2_inner.pack(padx=1, pady=(1, 2))
        tk.Entry(kc2_inner, textvariable=self._pa_key2_var, width=2,
                 font=('Consolas', 11, 'bold'), fg='#c9d1d9', bg=BG2,
                 insertbackground=ACCENT, bd=0, relief='flat',
                 justify='center').pack(padx=3, pady=2)

        # Sync key/time vars
        def _on_key1_change(*_):
            val = self._pa_key1_var.get()
            if val:
                self.periodic_attack.key1 = val[-1]
                if len(val) > 1:
                    self._pa_key1_var.set(val[-1])

        def _on_key2_change(*_):
            val = self._pa_key2_var.get()
            if val:
                self.periodic_attack.key2 = val[-1]
                if len(val) > 1:
                    self._pa_key2_var.set(val[-1])

        self._pa_key1_var.trace_add('write', _on_key1_change)
        self._pa_key2_var.trace_add('write', _on_key2_change)

        def _sync_times(*_):
            try:
                t1 = float(self._pa_time1_var.get())
                t2 = float(self._pa_time2_var.get())
            except ValueError:
                return
            if t1 < 0.1 or t2 < 0.1:
                return
            self.periodic_attack.delay_after_key1 = t1
            self.periodic_attack.cycle_period = t1 + t2

        self._pa_time1_var.trace_add('write', _sync_times)
        self._pa_time2_var.trace_add('write', _sync_times)

    def _switch_tab(self, name):
        """Switch to the specified tab."""
        if name == self._active_tab:
            return
        self._tab_frames[self._active_tab].pack_forget()
        self._active_tab = name
        self._tab_frames[name].pack(fill='both', expand=True)
        self._draw_tab_bar()

    def _build_settings_tab(self, parent):
        """Build the settings tab with monitor selector and hotkey bindings."""
        mon_frame = tk.Frame(parent, bg=BG)
        mon_frame.pack(pady=(8, 0))

        tk.Button(
            mon_frame, text="\u25C0", font=("Segoe UI", 8),
            fg="#8b949e", bg=BORDER, activebackground='#30363d',
            width=2, bd=0, relief='flat',
            command=lambda: self._cycle_monitor(-1)
        ).pack(side=tk.LEFT, padx=2)

        n = self.hub.monitors.current_index + 1
        total = self.hub.monitors.count
        self.mon_lbl = tk.Label(
            mon_frame, text=f"Monitor {n}/{total}  ({self.hub.monitors.resolution})",
            font=("Consolas", 9), fg=ACCENT, bg=BG)
        self.mon_lbl.pack(side=tk.LEFT, padx=6)

        tk.Button(
            mon_frame, text="\u25B6", font=("Segoe UI", 8),
            fg="#8b949e", bg=BORDER, activebackground='#30363d',
            width=2, bd=0, relief='flat',
            command=lambda: self._cycle_monitor(1)
        ).pack(side=tk.LEFT, padx=2)

        tk.Frame(parent, bg=BORDER, height=1).pack(
            fill='x', padx=16, pady=(10, 6))

        tk.Label(parent, text='Hotkey Bindings', font=('Consolas', 10, 'bold'),
                 fg=DIM, bg=BG).pack(pady=(2, 4), padx=20, anchor='w')

        self._settings_hotkey_ui = {}
        hotkey_list = [
            ('jiggle', 'Smelting'),
            ('bar_game', 'Casting'),
            ('circle', 'Welding'),
            ('auto_phase', 'Auto-Phase'),
            ('autoclicker', 'Autoclick'),
            ('hold_left', 'Hold Left'),
            ('sprint', 'Sprint'),
        ]

        for hotkey_name, display_name in hotkey_list:
            row = tk.Frame(parent, bg=BG)
            row.pack(fill='x', padx=20, pady=1)
            tk.Label(row, text=display_name, font=('Consolas', 10),
                     fg='#8b949e', bg=BG, anchor='w').pack(side=tk.LEFT)

            ui = self._hotkey_ui.get(hotkey_name)
            if ui:
                if ui['type'] == 'canvas':
                    key_text = self.pipe_canvas.itemcget(ui['item_id'], 'text')
                else:
                    key_text = ui['widget'].cget('text')
            else:
                key_text = '[-]'

            key_lbl = tk.Label(row, text=key_text, font=('Consolas', 9, 'bold'),
                               fg='#30363d', bg=BG, anchor='e', cursor='hand2')
            key_lbl.pack(side=tk.RIGHT)
            key_lbl.bind('<Button-1>',
                         lambda e, n=hotkey_name: self._start_key_rebind(n))
            self._settings_hotkey_ui[hotkey_name] = key_lbl

    # ---- Toggle methods ----
    def _toggle_hotkeys(self):
        self.hub.hotkeys.enabled = not self.hub.hotkeys.enabled
        if self.hub.hotkeys.enabled:
            self.hotkey_btn.config(text='Hotkeys: ON', fg=GREEN,
                                   activeforeground=GREEN)
        else:
            self.hotkey_btn.config(text='Hotkeys: OFF', fg=RED,
                                   activeforeground=RED)

    def _toggle_forge(self):
        self.forge_enabled = not self.forge_enabled
        if not self.forge_enabled:
            self.circle_detector.active = False
            self.cursor_jiggle.active = False
            self.bar_game.active = False
            self.bar_game.shaping = False
            self.auto_phase = False
        self._window.after(0, self._refresh_gui)

    def _toggle_debug(self):
        self.debug = not self.debug
        self._window.after(0, self._refresh_gui)

    def _toggle_autoclicker(self, force=False):
        if not force and not self.hub.focus.is_focused():
            return
        self.autoclicker.toggle()
        self._window.after(0, self._refresh_gui)

    def _toggle_hold_left(self, force=False):
        if not force and not self.hub.focus.is_focused():
            return
        self.hold_left.toggle()
        self._window.after(0, self._refresh_gui)

    def _toggle_sprint(self, force=False):
        if not force and not self.hub.focus.is_focused():
            return
        self.sprint.toggle()
        self._window.after(0, self._refresh_gui)

    def _toggle_periodic_attack(self):
        self.periodic_attack.toggle()
        self._window.after(0, self._refresh_gui)

    def _toggle_auto_sell(self):
        self.auto_sell.toggle()
        self._window.after(0, self._refresh_gui)

    def _toggle_auto_sell_camlock(self):
        self.auto_sell.camlock = not self.auto_sell.camlock
        color = GREEN if self.auto_sell.camlock else DIM
        self._as_camlock_btn.config(fg=color, activeforeground=color)
        self._save_auto_sell()

    def _on_auto_sell_slider(self, val):
        new_val = int(val)
        if new_val == self.auto_sell.interval:
            return
        self.auto_sell.interval = new_val
        self._as_interval_lbl.config(
            text=AutoSellComponent.fmt_interval(self.auto_sell.interval))
        self._save_auto_sell()

    def _save_auto_sell(self):
        self.hub.config.set('mods', 'forge', 'auto_sell',
                            self.auto_sell.save_data())
        self.hub.config.save()

    def _on_node_click(self, idx, force=False):
        if not self.forge_enabled:
            return
        if not force and not self.hub.focus.is_focused():
            return
        self.auto_phase = False
        if idx == 0:
            if self.cursor_jiggle.active:
                self.cursor_jiggle.stop()
            else:
                self.circle_detector.stop()
                self.bar_game.stop()
                self.autoclicker.stop()
                self.cursor_jiggle.start()
        elif idx == 1:
            if self.bar_game.active and not self.bar_game.shaping:
                self.bar_game.stop()
            else:
                self.circle_detector.stop()
                self.cursor_jiggle.stop()
                self.autoclicker.stop()
                self.bar_game.shaping = False
                self.bar_game.start()
        elif idx == 2:
            if self.bar_game.shaping:
                self.bar_game.stop()
            else:
                self.circle_detector.stop()
                self.cursor_jiggle.stop()
                self.autoclicker.stop()
                self.bar_game.shaping = True
                self.bar_game.start()
        elif idx == 3:
            if self.circle_detector.active:
                self.circle_detector.stop()
            else:
                self.cursor_jiggle.stop()
                self.bar_game.stop()
                self.autoclicker.stop()
                self.circle_detector.start()
        self._refresh_gui()

    def toggle_auto_phase(self, force=False):
        if not self.forge_enabled:
            return
        if not force and not self.hub.focus.is_focused():
            return
        if self.auto_phase:
            self.auto_phase = False
        else:
            self.auto_phase = True
            self.phase_idx = -1
            self.circle_detector.stop()
            self.bar_game.stop()
            self.cursor_jiggle.stop()
        self._window.after(0, self._refresh_gui)

    def _handle_enter(self):
        """Enter during auto-phase ready: move cursor to middle-bottom and click."""
        if not self.auto_phase or self.phase_idx != -1:
            return
        if not self.hub.focus.is_focused():
            return
        mon = self.hub.monitors.rect
        target_x = mon['left'] + mon['width'] // 2
        target_y = mon['top'] + int(mon['height'] * 0.86)
        inp = self.hub.input
        inp.move_to(target_x, target_y)
        inp.click(target_x, target_y)

    def _advance_phase(self):
        phases = ['jiggle', 'bar_game', 'circle']
        self.phase_idx += 1
        if self.phase_idx >= len(phases):
            self._window.after(0, self._refresh_gui)
            return

        phase = phases[self.phase_idx]
        self.circle_detector.stop()
        self.cursor_jiggle.stop()
        self.bar_game.stop()

        if phase == 'jiggle':
            self.cursor_jiggle.start()
        elif phase == 'bar_game':
            self.bar_game.start()
        elif phase == 'circle':
            self.circle_detector.start()
            self.auto_phase = False
        self._window.after(0, self._refresh_gui)

    def _cycle_monitor(self, delta):
        self.hub.monitors.cycle(delta)
        n = self.hub.monitors.current_index + 1
        total = self.hub.monitors.count
        self.mon_lbl.config(
            text=f"Monitor {n}/{total}  ({self.hub.monitors.resolution})")

    def _start_key_rebind(self, hotkey_name):
        ui = self._hotkey_ui.get(hotkey_name)
        if not ui:
            return
        if ui['type'] == 'label':
            ui['widget'].config(text='Press key...', fg='#f0c674')
        else:
            self.pipe_canvas.itemconfig(
                ui['item_id'], text='Press key...', fill='#f0c674')
        settings_lbl = getattr(self, '_settings_hotkey_ui', {}).get(hotkey_name)
        if settings_lbl:
            settings_lbl.config(text='Press key...', fg='#f0c674')
        self.hub.hotkeys.start_capture(
            hotkey_name,
            lambda name, key: self._window.after(
                0, lambda: self._apply_rebind(name, key)))

    def _apply_rebind(self, name, new_key):
        self.hub.hotkeys.rebind(name, new_key)
        display = new_key.upper()
        ui = self._hotkey_ui.get(name)
        if ui:
            if ui['type'] == 'label':
                ui['widget'].config(text=f'[{display}]', fg='#30363d')
            else:
                self.pipe_canvas.itemconfig(
                    ui['item_id'], text=f'[{display}]', fill='#30363d')
        settings_lbl = getattr(self, '_settings_hotkey_ui', {}).get(name)
        if settings_lbl:
            settings_lbl.config(text=f'[{display}]', fg='#30363d')

    # ---- Overlays ----
    def _make_arrow_overlay(self, parent, label_text):
        ov = tk.Toplevel(parent)
        ov.overrideredirect(True)
        ov.attributes('-topmost', True)
        ov.configure(bg='#1a1a1a')
        ov.geometry("75x24+0+0")
        tk.Label(ov, text=f"{label_text} \u25b6",
                 font=("Consolas", 12, "bold"),
                 fg="#ff2222", bg='#1a1a1a').pack(fill='both', expand=True)
        ov.withdraw()
        return ov

    def _update_ring(self, x, y, text, color='#ff2222'):
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

    def _show_hit(self, x, y):
        hit = tk.Toplevel(self._window)
        hit.overrideredirect(True)
        hit.attributes('-topmost', True)
        hit.attributes('-transparentcolor', '#000000')
        hit.configure(bg='#000000')
        hit.geometry(f"50x25+{x - 25}+{y + 15}")
        tk.Label(hit, text="HIT", font=("Consolas", 14, "bold"),
                 fg="#ff2222", bg='#000000').pack()
        hit.after(300, hit.destroy)

    def _update_bar_overlays(self, scr_x, bar_y, slit_y, width,
                             col_left_scr=None, col_right_scr=None,
                             bot_scr=None):
        try:
            arrow_x = scr_x - 75
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
            mon_h = self.hub.monitors.rect['height']
            if col_left_scr is not None:
                self._col_left_ov.geometry(
                    f"2x{mon_h}+{col_left_scr}+{self.hub.monitors.rect['top']}")
                self._col_left_ov.deiconify()
                self._col_right_ov.geometry(
                    f"2x{mon_h}+{col_right_scr}+{self.hub.monitors.rect['top']}")
                self._col_right_ov.deiconify()
            else:
                self._col_left_ov.withdraw()
                self._col_right_ov.withdraw()
            if bot_scr is not None:
                mon_w = self.hub.monitors.rect['width']
                self._bot_ov.geometry(
                    f"{mon_w}x2+{self.hub.monitors.rect['left']}+{bot_scr}")
                self._bot_ov.deiconify()
            else:
                self._bot_ov.withdraw()
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

    # ---- Focus polling ----
    def _update_focus_label(self):
        if not self._window:
            return
        if self.hub.focus.is_focused():
            self.focus_lbl.config(text="\u25CF  ROBLOX: Focused", fg=GREEN)
            if self.hub.monitors.auto_select():
                n = self.hub.monitors.current_index + 1
                total = self.hub.monitors.count
                self.mon_lbl.config(
                    text=f"Monitor {n}/{total}  ({self.hub.monitors.resolution})")
        else:
            self.focus_lbl.config(
                text="\u25CF  ROBLOX: Not Focused", fg=RED)
        self._window.after(500, self._update_focus_label)
        if self.auto_sell.active:
            self._refresh_gui()
        self._update_game_label()

    def _update_game_label(self):
        def _detect():
            place_id, name = self.hub.focus.detect_game()
            self.hub.focus.update_cache(place_id, name)
            if place_id:
                display = name or f"Place {place_id}"
                if len(display) > 30:
                    display = display[:27] + "..."
                self._window.after(0, lambda: self.game_lbl.config(
                    text=f"\u25CB  Game: {display}", fg=ACCENT))
            else:
                self._window.after(0, lambda: self.game_lbl.config(
                    text="\u25CB  Game: --", fg="#888888"))
        Thread(target=_detect, daemon=True).start()

    # ---- Refresh GUI ----
    def _refresh_gui(self):
        if not self._window:
            return

        states = [
            self.cursor_jiggle.active,
            self.bar_game.active and not self.bar_game.shaping,
            self.bar_game.shaping,
            self.circle_detector.active,
        ]

        if not self.forge_enabled:
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
                    self.pipe_canvas.itemconfig(glow, outline='#9e6a03', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#2d1b00', outline='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#f0c040')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#9e6a03')
                elif is_on and i == 2:
                    self.pipe_canvas.itemconfig(glow, outline='#1f6feb', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#0d1b3d', outline=ACCENT)
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill=ACCENT)
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill=ACCENT)
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#1f6feb')
                elif is_on:
                    self.pipe_canvas.itemconfig(glow, outline='#238636', width=2)
                    self.pipe_canvas.itemconfig(circle, fill='#0d4429', outline=GREEN)
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill=GREEN)
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill='#c9d1d9')
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#238636')
                else:
                    self.pipe_canvas.itemconfig(glow, outline='', width=0)
                    self.pipe_canvas.itemconfig(circle, fill=BG2, outline='#30363d')
                    self.pipe_canvas.itemconfig(self._pipe_icons[i], fill=DIM)
                    self.pipe_canvas.itemconfig(self._pipe_labels[i], fill=DIM)
                    self.pipe_canvas.itemconfig(self._pipe_keys[i], fill='#30363d')

        for line in self._pipe_lines:
            if not self.forge_enabled:
                self.pipe_canvas.itemconfig(line, fill='#2a1515')
            elif self.auto_phase:
                self.pipe_canvas.itemconfig(line, fill='#f0c040')
            else:
                self.pipe_canvas.itemconfig(line, fill=BORDER)

        # Phase label
        if self.auto_phase:
            phases = ['Smelting', 'Casting', 'Welding']
            idx = self.phase_idx
            name = phases[idx] if 0 <= idx < len(phases) else 'Ready'
            self.phase_lbl.config(text=f'Phase: {name}', fg='#f0c040')
            self._phase_dot.config(fg='#f0c040')
        else:
            self.phase_lbl.config(text='Auto-Phase: OFF', fg=DIM)
            self._phase_dot.config(fg=RED)

        # Autoclicker
        if self.autoclicker.active and self.auto_sell.executing:
            self.autoclick_lbl.config(text='Autoclick: PAUSED', fg='#f0c040')
            self._autoclick_dot.config(fg='#f0c040')
        elif self.autoclicker.active:
            self.autoclick_lbl.config(text='Autoclick: ON', fg=GREEN)
            self._autoclick_dot.config(fg=GREEN)
        else:
            self.autoclick_lbl.config(text='Autoclick: OFF', fg=DIM)
            self._autoclick_dot.config(fg=RED)

        if self.hold_left.active:
            self.holdleft_lbl.config(text='Hold Left: ON', fg=GREEN)
            self._holdleft_dot.config(fg=GREEN)
        else:
            self.holdleft_lbl.config(text='Hold Left: OFF', fg=DIM)
            self._holdleft_dot.config(fg=RED)

        if self.sprint.active:
            self.sprint_lbl.config(text='Sprint: ON', fg=GREEN)
            self._sprint_dot.config(fg=GREEN)
        else:
            self.sprint_lbl.config(text='Sprint: OFF', fg=DIM)
            self._sprint_dot.config(fg=RED)

        if self.periodic_attack.active:
            self.pa_lbl.config(text='Periodic Attack: ON', fg='#bd93f9')
            self._pa_dot.config(fg='#bd93f9')
        else:
            self.pa_lbl.config(text='Periodic Attack: OFF', fg=DIM)
            self._pa_dot.config(fg=RED)

        # Auto sell
        import time as _time
        if self.auto_sell.active:
            remaining = self.auto_sell.deadline - _time.time()
            if self.auto_sell.executing:
                self.as_lbl.config(text='Auto Sell: SELLING', fg='#ff79c6')
                self._as_dot.config(fg='#ff79c6')
            elif remaining > 0:
                self.as_lbl.config(
                    text=f'Auto Sell: {AutoSellComponent.fmt_interval(remaining)}',
                    fg=GREEN)
                self._as_dot.config(fg=GREEN)
            else:
                self.as_lbl.config(text='Auto Sell: ON', fg=GREEN)
                self._as_dot.config(fg=GREEN)
        else:
            self.as_lbl.config(text='Auto Sell: OFF', fg=DIM)
            self._as_dot.config(fg=RED)

        # Debug button
        if self.debug:
            self.debug_btn.config(fg=GREEN, activeforeground=GREEN)
        else:
            self.debug_btn.config(fg=DIM, activeforeground=RED)

        # Mini mode
        self.hub.mini_mode.refresh(self.get_active_features())

    def get_active_features(self):
        import time as _time
        features = []
        if not self.forge_enabled:
            features.append(('Forge OFF', RED))
        if self.cursor_jiggle.active:
            features.append(('Smelting', GREEN))
        if self.bar_game.active and not self.bar_game.shaping:
            features.append(('Casting', GREEN))
        if self.bar_game.shaping:
            features.append(('Shaping', ACCENT))
        if self.circle_detector.active:
            features.append(('Welding', GREEN))
        if self.auto_phase:
            features.append(('Auto-Phase', '#f0c040'))
        if self.autoclicker.active:
            features.append(('Autoclick', GREEN))
        if self.hold_left.active:
            features.append(('Hold Left', GREEN))
        if self.sprint.active:
            features.append(('Sprint', GREEN))
        if self.periodic_attack.active:
            features.append(('Periodic', '#bd93f9'))
        if self.auto_sell.active:
            features.append(('AutoSell', '#ff79c6'))
        return features
