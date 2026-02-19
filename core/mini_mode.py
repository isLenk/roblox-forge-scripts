"""Mini mode overlay — compact floating indicator."""

import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageDraw, ImageTk

from core.theme import GLASS_TOP, BG

_ASSETS = (Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS')
           else Path(__file__).resolve().parent.parent / 'assets')

_LABEL_ROW_H = 20   # px per label row
_LABEL_VPAD  = 6    # top + bottom inner padding
_LABEL_HPAD  = 10   # left + right inner padding


class MiniMode:
    """Compact floating overlay showing active features."""

    CIRCLE_SIZE = 44
    ICON_PAD    = 8        # padding shrinks the logo inside the circle
    TRANSPARENT = '#010101'

    def __init__(self, root, on_restore):
        """
        Args:
            root: Tk root window
            on_restore: Callback to restore full GUI on double-click
        """
        self.root = root
        self._on_restore = on_restore
        self._win = None
        self._lbl_cvs = None
        self._cvs = None
        self._last_keys = None

    @property
    def is_active(self):
        return self._win is not None

    def show(self, x, y):
        """Show mini mode at position (x, y)."""
        if self._win:
            return

        win = tk.Toplevel()
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.attributes('-transparentcolor', self.TRANSPARENT)
        win.configure(bg=self.TRANSPARENT)

        sz  = self.CIRCLE_SIZE
        pad = self.ICON_PAD

        # ── Glassy circle icon ────────────────────────────────────────
        bg_img = Image.new('RGBA', (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(bg_img)
        gt = tuple(int(GLASS_TOP[i:i+2], 16) for i in (1, 3, 5))
        bb = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
        for row in range(sz):
            t = row / max(sz - 1, 1)
            c = tuple(int(gt[i] + (bb[i] - gt[i]) * t) for i in range(3))
            draw.line([(0, row), (sz - 1, row)], fill=(*c, 230))
        mask = Image.new('L', (sz, sz), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, sz - 1, sz - 1), fill=255)
        bg_img.putalpha(mask)
        shine = Image.new('RGBA', (sz, 1), (255, 255, 255, 18))
        bg_img.paste(shine, (4, 1), shine)

        inner = sz - pad * 2
        logo = Image.open(_ASSETS / 'logo.png').convert('RGBA')
        logo.thumbnail((inner, inner), Image.LANCZOS)
        lx = pad + (inner - logo.width) // 2
        ly = pad + (inner - logo.height) // 2
        bg_img.paste(logo, (lx, ly), logo)
        self._icon_photo = ImageTk.PhotoImage(bg_img)

        cvs = tk.Canvas(win, width=sz, height=sz,
                        bg=self.TRANSPARENT, highlightthickness=0)
        cvs.pack(side=tk.LEFT)
        cvs.create_image(sz // 2, sz // 2, image=self._icon_photo)

        # ── Label canvas (pill drawn per refresh) ─────────────────────
        lbl_cvs = tk.Canvas(win, bg=self.TRANSPARENT, highlightthickness=0,
                            width=0, height=0)
        lbl_cvs.pack(side=tk.LEFT, padx=(6, 0))

        self._win = win
        self._cvs = cvs
        self._lbl_cvs = lbl_cvs
        self._last_keys = None

        # Dragging
        def _start_drag(event):
            self._drag_x = event.x_root - win.winfo_x()
            self._drag_y = event.y_root - win.winfo_y()

        def _on_drag(event):
            nx = event.x_root - self._drag_x
            ny = event.y_root - self._drag_y
            win.geometry(f"+{nx}+{ny}")

        cvs.bind('<Button-1>', _start_drag)
        cvs.bind('<B1-Motion>', _on_drag)
        cvs.bind('<Double-Button-1>', lambda e: self._on_restore())

        win.geometry(f"+{x}+{y}")

    def hide(self):
        """Hide mini mode."""
        if self._win:
            self._win.destroy()
            self._win = None
            self._last_keys = None

    def refresh(self, features):
        """Update displayed features.

        Args:
            features: List of (name, color) tuples for active features.
        """
        if not self._win:
            return

        active_keys = tuple(features)
        if self._last_keys == active_keys:
            return
        self._last_keys = active_keys

        lbl_cvs = self._lbl_cvs
        lbl_cvs.delete('all')

        sz = self.CIRCLE_SIZE

        if not features:
            lbl_cvs.config(width=0, height=0)
            x, y = self._win.winfo_x(), self._win.winfo_y()
            self._win.geometry(f"{sz}x{sz}+{x}+{y}")
            return

        # Measure text width (Consolas is monospaced — font.measure is exact)
        f = tkfont.Font(family='Consolas', size=9, weight='bold')
        max_tw = max(f.measure(name) for name, _ in features)

        pill_w = max_tw + _LABEL_HPAD * 2
        pill_h = len(features) * _LABEL_ROW_H + _LABEL_VPAD * 2

        # ── Glassy pill background ─────────────────────────────────────
        gt = tuple(int(GLASS_TOP[i:i+2], 16) for i in (1, 3, 5))
        bb = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
        img = Image.new('RGBA', (pill_w, pill_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for row in range(pill_h):
            t = row / max(pill_h - 1, 1)
            c = tuple(int(gt[i] + (bb[i] - gt[i]) * t) for i in range(3))
            draw.line([(0, row), (pill_w - 1, row)], fill=(*c, 220))
        mask = Image.new('L', (pill_w, pill_h), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, pill_w - 1, pill_h - 1),
            radius=pill_h // 2, fill=255)
        img.putalpha(mask)
        shine_w = max(1, pill_w - 8)
        shine = Image.new('RGBA', (shine_w, 1), (255, 255, 255, 18))
        img.paste(shine, (4, 1), shine)

        self._pill_photo = ImageTk.PhotoImage(img)
        lbl_cvs.config(width=pill_w, height=pill_h)
        lbl_cvs.create_image(0, 0, anchor='nw', image=self._pill_photo)

        for i, (name, color) in enumerate(features):
            cy = _LABEL_VPAD + i * _LABEL_ROW_H + _LABEL_ROW_H // 2
            lbl_cvs.create_text(
                _LABEL_HPAD, cy, anchor='w', text=name,
                font=('Consolas', 9, 'bold'), fill=color)

        total_w = sz + 6 + pill_w
        total_h = max(sz, pill_h)
        x, y = self._win.winfo_x(), self._win.winfo_y()
        self._win.geometry(f"{total_w}x{total_h}+{x}+{y}")
