"""GUI preview — renders the full mod window with mock services.

Usage:
    python preview.py              # preview the Forge mod (default)
    python preview.py macro        # preview the Macro Editor panel

Edit the source files, close the window, re-run to see changes.
"""

import ctypes
import sys
import tkinter as tk

# Fix DPI scaling so the preview matches the real app
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Lightweight stubs for hub services so the GUI renders without real hardware
# ---------------------------------------------------------------------------

class _Stub:
    """Generic stub that returns itself or no-ops for any attribute/call."""
    def __getattr__(self, name):
        return _Stub()
    def __call__(self, *a, **kw):
        return self
    def __bool__(self):
        return False
    def __iter__(self):
        return iter([])


class StubConfig:
    def get(self, *keys, default=None):
        return default
    def set(self, *args):
        pass
    def save(self):
        pass


class StubMonitors:
    current_index = 0
    count = 1
    resolution = "1920x1080"
    rect = {'left': 0, 'top': 0, 'width': 1920, 'height': 1080}
    def auto_select(self):
        return False
    def cycle(self, delta):
        pass


class StubFocus:
    def is_focused(self):
        return False
    def detect_game(self):
        return (None, None)
    def update_cache(self, *a):
        pass


class StubHotkeys:
    enabled = True
    def register(self, *a, **kw):
        pass
    def start_capture(self, *a, **kw):
        pass
    def rebind(self, *a, **kw):
        pass
    def cleanup(self):
        pass


class StubMiniMode:
    is_active = False
    def refresh(self, *a):
        pass
    def show(self, *a):
        pass
    def hide(self):
        pass


class StubInput:
    def send_mouse(self, *a):
        pass
    def send_key(self, *a, **kw):
        pass
    def press_game_key(self, *a):
        pass
    def click_at_screen(self, *a):
        pass
    def get_abs_coords(self):
        return (0, 0, 0, 0)
    def screen_to_abs(self, x, y):
        return (0, 0)
    def move_to(self, *a):
        pass
    def click(self, *a):
        pass


class MockHub:
    """Minimal hub that satisfies ForgeMod.build_gui() without real services."""
    def __init__(self, root):
        self.root = root
        self.running = True
        self.input = StubInput()
        self.focus = StubFocus()
        self.monitors = StubMonitors()
        self.config = StubConfig()
        self.hotkeys = StubHotkeys()
        self.mini_mode = StubMiniMode()
        self.radial = None
        self._active_mod = None
        self._wiki_panel = None
        self._wiki_search = None

    def _quit(self):
        self.running = False
        self.root.destroy()

    def _minimize(self):
        pass

    def _toggle_wiki_panel(self):
        pass

    def _run_in_app_update(self):
        pass


# ---------------------------------------------------------------------------
# Preview runners
# ---------------------------------------------------------------------------

def preview_forge():
    """Show the full Forge mod window."""
    root = tk.Tk()
    root.withdraw()

    hub = MockHub(root)

    from mods.forge.mod import ForgeMod
    mod = ForgeMod(hub)
    mod.init()
    win = mod.build_gui(root)

    # Keep the window alive even though focus polling would normally schedule
    # the next check — just let it error silently on stubs.
    print("[preview] Forge mod window open. Close the window or Ctrl+C to exit.")
    root.mainloop()


def preview_macro():
    """Show the Macro Editor panel standalone."""
    root = tk.Tk()
    root.withdraw()

    hub = MockHub(root)

    # We need a minimal mod stub
    from components.macro_editor import MacroEditorComponent
    mod = _Stub()
    comp = MacroEditorComponent(hub, mod)
    comp.start = lambda: None  # don't register real hotkeys
    comp._active = True

    # Build the panel anchored at (100, 100)
    dummy = tk.Toplevel(root)
    dummy.geometry("1x1+100+100")
    dummy.withdraw()
    # Simulate root positioning for panel placement
    comp.toggle_panel(dummy)

    print("[preview] Macro Editor panel open. Close the window or Ctrl+C to exit.")
    root.mainloop()


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'forge'
    if target == 'macro':
        preview_macro()
    else:
        preview_forge()
