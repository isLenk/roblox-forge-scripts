"""Shared theme constants and UI helpers."""

import tkinter as tk

# ---- Color palette ----
BG = '#0d1117'
BG2 = '#161b22'
BG_DARK = '#0e1219'   # darkened BG2
BORDER = '#21262d'
DIM = '#484f58'
ACCENT = '#58a6ff'
GREEN = '#50fa7b'
RED = '#ff5555'
TEXT = '#c9d1d9'

DOT_SPACING = 18
DOT_COLOR = '#1a1f27'

# ---- Glass effect ----
GLASS_ALPHA = 0.98
GLASS_TOP = '#0f1520'
GLASS_SHINE = '#141b27'

# Pre-parsed RGB tuples for blending
_BG_RGB = (0x0d, 0x11, 0x17)
_GT_RGB = (0x0f, 0x15, 0x20)


def _blend_row_color(y, height):
    """Return hex color for row y in a top-to-bottom glass gradient."""
    t = y / max(height - 1, 1)
    r = int(_GT_RGB[0] + (_BG_RGB[0] - _GT_RGB[0]) * t)
    g = int(_GT_RGB[1] + (_BG_RGB[1] - _GT_RGB[1]) * t)
    b = int(_GT_RGB[2] + (_BG_RGB[2] - _GT_RGB[2]) * t)
    return f'#{r:02x}{g:02x}{b:02x}'


def make_dotted_bg(width, height):
    """Create a PhotoImage with a glass gradient and dotted overlay."""
    img = tk.PhotoImage(width=width, height=height)
    # Glass gradient (lighter at top → BG at bottom)
    for y in range(0, height, 2):
        color = _blend_row_color(y, height)
        img.put(color, to=(0, y, width, min(y + 2, height)))
    # Glass shine line at top edge
    img.put(GLASS_SHINE, to=(0, 0, width, 1))
    # Dot pattern overlay
    for y in range(0, height, DOT_SPACING):
        for x in range(0, width, DOT_SPACING):
            img.put(DOT_COLOR, to=(x, y, x + 2, y + 2))
    return img


def apply_rounded_corners(window):
    """Enable Windows 11 rounded corners via DWM."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2
        pref = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


def apply_glass(window):
    """Apply glass transparency to a window."""
    window.attributes('-alpha', GLASS_ALPHA)


def make_glass_dynamic(window):
    """Remove glass when mouse is over the window; restore on leave."""
    def _on_enter(e):
        window.attributes('-alpha', 1.0)

    def _on_leave(e):
        wx = window.winfo_rootx()
        wy = window.winfo_rooty()
        ww = window.winfo_width()
        wh = window.winfo_height()
        if not (wx <= e.x_root < wx + ww and wy <= e.y_root < wy + wh):
            window.attributes('-alpha', GLASS_ALPHA)

    window.bind('<Enter>', _on_enter, add='+')
    window.bind('<Leave>', _on_leave, add='+')


def build_titlebar(parent, title, *, on_close=None, on_minimize=None,
                   extra_widgets=None, bg=BG):
    """Build a custom titlebar frame with title, close, and minimize buttons.

    Returns (titlebar_frame, title_label) so callers can add drag bindings
    and extra widgets.
    """
    titlebar = tk.Frame(parent, bg=bg, height=30)
    titlebar.pack(fill='x')
    titlebar.pack_propagate(False)

    title_lbl = tk.Label(
        titlebar, text=title,
        font=("Consolas", 9, "bold"), fg=DIM, bg=bg)
    title_lbl.pack(side=tk.LEFT, padx=10)

    # Close button
    if on_close:
        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 10),
            fg=DIM, bg=bg, padx=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: on_close())
        close_btn.bind('<Enter>',
                       lambda e: close_btn.config(fg=RED, bg='#1a0000'))
        close_btn.bind('<Leave>',
                       lambda e: close_btn.config(fg=DIM, bg=bg))

    # Minimize button
    if on_minimize:
        min_btn = tk.Label(
            titlebar, text='\u2500', font=('Consolas', 10),
            fg=DIM, bg=bg, padx=10, cursor='hand2')
        min_btn.pack(side=tk.RIGHT, fill='y')
        min_btn.bind('<Button-1>', lambda e: on_minimize())
        min_btn.bind('<Enter>',
                     lambda e: min_btn.config(fg=TEXT, bg=BG2))
        min_btn.bind('<Leave>',
                     lambda e: min_btn.config(fg=DIM, bg=bg))

    return titlebar, title_lbl


def style_flat_treeview(style, prefix, *, heading_bg=None):
    """Configure a flat, modern Treeview + scrollbar style.

    *prefix* — style name prefix (e.g. ``'Macro'``, ``'Wiki'``).
    """
    name = f"{prefix}.Treeview"
    hbg = heading_bg or BORDER

    # Remove the outer border / focus rectangle from the treeview
    style.layout(name, [
        (f'{name}.treearea', {'sticky': 'nswe'}),
    ])

    style.configure(name,
                    background=BG2, foreground=TEXT,
                    fieldbackground=BG2,
                    borderwidth=0, relief='flat',
                    font=('Consolas', 9), rowheight=26)
    style.map(name,
              background=[('selected', '#1f6feb')],
              foreground=[('selected', '#ffffff')])

    # Flat headings — kill every border / separator the clam theme draws
    style.configure(f"{name}.Heading",
                    background=hbg, foreground=ACCENT,
                    font=('Consolas', 9, 'bold'),
                    borderwidth=0, relief='flat',
                    lightcolor=hbg, bordercolor=hbg, darkcolor=hbg,
                    padding=(8, 4))
    style.map(f"{name}.Heading",
              background=[('active', '#30363d')],
              relief=[('!disabled', 'flat')])

    # Flat, thin scrollbars
    for orient in ('Vertical', 'Horizontal'):
        sb = f"{prefix}.{orient}.TScrollbar"
        style.configure(sb,
                        background=BORDER, troughcolor=BG2,
                        borderwidth=0, arrowsize=0,
                        relief='flat', width=8)
        style.map(sb,
                  background=[('active', '#30363d'), ('!active', BORDER)])


def tint_color(hex_color, strength=0.10):
    """Blend *hex_color* into BG at *strength* (0-1)."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    br, bg, bb = _BG_RGB
    nr = int(br + (r - br) * strength)
    ng = int(bg + (g - bg) * strength)
    nb = int(bb + (b - bb) * strength)
    return f'#{nr:02x}{ng:02x}{nb:02x}'


def style_button(btn, fg):
    """Apply a tinted background + hover glow to a flat tk.Button.

    Stores ``_rest_bg`` / ``_hover_bg`` on *btn* so callers can
    update them later (e.g. when toggling ON/OFF state).
    """
    rest = tint_color(fg, 0.10)
    hover = tint_color(fg, 0.20)
    btn._rest_bg = rest
    btn._hover_bg = hover
    btn.config(bg=rest, activebackground=hover)
    btn.bind('<Enter>', lambda e: btn.config(bg=btn._hover_bg))
    btn.bind('<Leave>', lambda e: btn.config(bg=btn._rest_bg))


def restyle_button(btn, fg):
    """Re-tint an already styled button for a new *fg* color."""
    btn._rest_bg = tint_color(fg, 0.10)
    btn._hover_bg = tint_color(fg, 0.20)
    btn.config(fg=fg, activeforeground=fg,
               bg=btn._rest_bg, activebackground=btn._hover_bg)


def make_draggable(widget, window):
    """Make a widget drag its parent window."""
    def _start_drag(event):
        window._drag_x = event.x
        window._drag_y = event.y

    def _on_drag(event):
        x = window.winfo_x() + event.x - window._drag_x
        y = window.winfo_y() + event.y - window._drag_y
        window.geometry(f"+{x}+{y}")

    widget.bind('<Button-1>', _start_drag)
    widget.bind('<B1-Motion>', _on_drag)
