"""Radial (pie) menu triggered by middle-click."""

import ctypes
import ctypes.wintypes
import math
import tkinter as tk


class RadialMenu:
    """Middle-click radial pie menu."""

    def __init__(self, root, items):
        """
        Args:
            root: Tk root window
            items: List of dicts with keys:
                label, icon, toggle (callable), state (callable -> bool)
        """
        self.root = root
        self.items = items
        self._menu = None
        self._data = None

    def poll_middle_click(self):
        """Poll for middle mouse button press. Call from root.after loop."""
        VK_MBUTTON = 0x04
        state = ctypes.windll.user32.GetAsyncKeyState(VK_MBUTTON)
        if state & 0x0001:
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            try:
                self._open(pt.x, pt.y)
            except Exception:
                import traceback
                traceback.print_exc()

    def _open(self, mx, my):
        if self._menu is not None:
            self._close()
            return

        TRANS = '#010101'
        BG_RING = '#161b22'
        BORDER = '#21262d'

        outer_r = 80
        inner_r = 30
        hover_pad = 15
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

        n = len(self.items)
        seg = 360.0 / n

        HOVER_ZONE = '#020202'
        hr = outer_r + hover_pad
        canvas.create_oval(
            c - hr, c - hr, c + hr, c + hr,
            fill=HOVER_ZONE, outline='', width=0)

        arc_ids = []
        for i in range(n):
            ext = max(-seg, -359.99)
            arc = canvas.create_arc(
                c - outer_r, c - outer_r, c + outer_r, c + outer_r,
                start=90 - i * seg, extent=ext,
                fill=BG_RING, outline=BORDER, width=2, style='pieslice')
            arc_ids.append(arc)

        canvas.create_oval(
            c - inner_r, c - inner_r, c + inner_r, c + inner_r,
            fill=HOVER_ZONE, outline=BORDER, width=2)

        icon_ids = []
        for i, item in enumerate(self.items):
            theta = math.radians((i + 0.5) * seg)
            r_mid = (outer_r + inner_r) / 2
            ix = c + r_mid * math.sin(theta)
            iy = c - r_mid * math.cos(theta)
            state_fn = item.get('state')
            if state_fn is None:
                color = '#c9d1d9'
            else:
                color = '#50fa7b' if state_fn() else '#ff5555'
            icon_id = canvas.create_text(
                ix, iy, text=item['icon'],
                font=('Segoe UI Symbol', 20),
                fill=color)
            icon_ids.append(icon_id)

        center_lbl = canvas.create_text(
            c, c, text='', font=('Consolas', 10, 'bold'), fill='#8b949e')

        self._menu = menu
        self._data = {
            'canvas': canvas, 'arc_ids': arc_ids, 'icon_ids': icon_ids,
            'center_lbl': center_lbl, 'c': c,
            'outer_r': outer_r + hover_pad,
            'inner_r': max(inner_r - hover_pad, 5),
            'seg': seg, 'hovered': -1,
            'menu_x': mx - c, 'menu_y': my - c,
        }

        canvas.bind('<Motion>', self._on_motion)
        canvas.bind('<B2-Motion>', self._on_motion)
        canvas.bind('<Leave>', self._on_leave)
        canvas.bind('<Button-1>', self._on_click)
        menu.bind('<Escape>', lambda e: self._close())
        menu.bind('<FocusOut>',
                  lambda e: self.root.after(50, self._close))
        menu.focus_force()
        self.root.after(30, self._poll_release)

    def _segment_at(self, x, y):
        d = self._data
        dx = x - d['c']
        dy = y - d['c']
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < d['inner_r'] or dist > d['outer_r']:
            return -1
        angle = math.degrees(math.atan2(dx, -dy)) % 360
        return min(int(angle / d['seg']), len(self.items) - 1)

    def _poll_release(self):
        if self._menu is None:
            return
        d = self._data
        if d is None:
            return

        pt = ctypes.wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        cx = pt.x - d['menu_x']
        cy = pt.y - d['menu_y']

        idx = self._segment_at(cx, cy)
        if idx != d['hovered']:
            canvas = d['canvas']
            if d['hovered'] >= 0:
                canvas.itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
            if idx >= 0:
                canvas.itemconfig(d['arc_ids'][idx], fill='#30363d')
                canvas.itemconfig(d['center_lbl'],
                                  text=self.items[idx]['label'])
            else:
                canvas.itemconfig(d['center_lbl'], text='')
            d['hovered'] = idx

        VK_MBUTTON = 0x04
        state = ctypes.windll.user32.GetAsyncKeyState(VK_MBUTTON)
        if not (state & 0x8000):
            if d['hovered'] >= 0:
                sel = d['hovered']
                self._close()
                self.items[sel]['toggle']()
            return
        self.root.after(30, self._poll_release)

    def _on_motion(self, event):
        if self._menu is None:
            return
        d = self._data
        idx = self._segment_at(event.x, event.y)
        if idx == d['hovered']:
            return
        canvas = d['canvas']
        if d['hovered'] >= 0:
            canvas.itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
        if idx >= 0:
            canvas.itemconfig(d['arc_ids'][idx], fill='#30363d')
            canvas.itemconfig(d['center_lbl'],
                              text=self.items[idx]['label'])
        else:
            canvas.itemconfig(d['center_lbl'], text='')
        d['hovered'] = idx

    def _on_leave(self, event):
        if self._menu is None:
            return
        d = self._data
        if d['hovered'] >= 0:
            d['canvas'].itemconfig(d['arc_ids'][d['hovered']], fill='#161b22')
            d['canvas'].itemconfig(d['center_lbl'], text='')
            d['hovered'] = -1

    def _on_click(self, event):
        if self._menu is None:
            return
        idx = self._segment_at(event.x, event.y)
        self._close()
        if 0 <= idx < len(self.items):
            self.items[idx]['toggle']()

    def _close(self):
        if self._menu is None:
            return
        try:
            self._menu.destroy()
        except tk.TclError:
            pass
        self._menu = None
        self._data = None
