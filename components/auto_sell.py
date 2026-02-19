"""Auto sell component — automated sell sequence on a timer."""

import time
import tkinter as tk
import keyboard
from threading import Thread

from components.base import Component
from core.input import SCAN_LCTRL

try:
    import mouse as mouse_module
except ImportError:
    mouse_module = None


class AutoSellComponent(Component):
    """Automated sell sequence with configurable steps and timer."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self.open_stash_key = config.get('open_stash_key', 't')
        self.steps = config.get('steps', [
            ('sell_items', 'Sell Items'),
            ('select_all', 'Select All'),
            ('accept', 'Accept'),
            ('yes', 'Yes'),
            ('close', 'X (close)'),
        ])
        self.step_delays = config.get('step_delays', {'yes': 4.0})
        self.default_delay = config.get('default_delay', 2.0)
        self.default_interval = config.get('default_interval', 300)
        self.camlock_key_scan = config.get('camlock_key_scan', SCAN_LCTRL)

        # State
        self.positions = {}
        self.interval = self.default_interval
        self.camlock = False
        self._executing = False
        self._stop_flag = False
        self._overlays = []
        self._deadline = 0
        self._thread = None

    @property
    def executing(self):
        return self._executing

    @property
    def deadline(self):
        return self._deadline

    def load_positions(self, data):
        """Load saved positions from config data."""
        if not data:
            return
        self.positions = {
            k: tuple(v) for k, v in data.get('positions', {}).items()
        }
        self.interval = data.get('interval', self.default_interval)
        self.camlock = data.get('camlock', False)

    def save_data(self):
        """Return dict for config persistence."""
        return {
            'positions': self.positions,
            'interval': self.interval,
            'camlock': self.camlock,
        }

    def start(self):
        if not self.positions:
            print("[AUTO-SELL] No positions configured. Run Setup first.")
            return
        self._active = True
        self._stop_flag = False
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()
        print("[AUTO-SELL] ON")

    def stop(self):
        self._active = False
        self._stop_flag = True
        print("[AUTO-SELL] OFF")

    def setup(self, root):
        """Run the interactive setup wizard in a background thread."""
        Thread(target=lambda: self._setup_wizard(root), daemon=True).start()

    def _setup_wizard(self, root):
        """Wizard to capture button positions."""
        import ctypes.wintypes
        positions = {}

        TRANS = '#010101'
        tip = [None, None]

        def _create_tip(text):
            w = tk.Toplevel(root)
            w.overrideredirect(True)
            w.attributes('-topmost', True)
            w.attributes('-transparentcolor', TRANS)
            w.configure(bg=TRANS)
            lbl = tk.Label(w, text=text,
                           font=('Consolas', 11, 'bold'),
                           fg='#ff79c6', bg='#0d1117', padx=6, pady=2)
            lbl.pack()
            tip[0] = w
            tip[1] = lbl

        def _update_tip_pos():
            w = tip[0]
            if w is None:
                return
            try:
                import ctypes.wintypes
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

        root.after(0, lambda: _create_tip(
            'Focus Roblox, then click [ESC cancel]'))
        root.after(0, _update_tip_pos)
        pos = self._wait_for_click_or_esc()
        if pos is None:
            root.after(0, _destroy_tip)
            print("[AUTO-SELL] Setup cancelled.")
            return

        root.after(0, lambda: _set_tip_text('Opening stash...'))
        self.hub.input.press_game_key(self.open_stash_key)
        time.sleep(2.0)

        for key, label_text in self.steps:
            root.after(0, lambda t=label_text: _set_tip_text(
                f'Click: {t}  [ESC cancel]'))
            time.sleep(0.3)
            pos = self._wait_for_click_or_esc()
            if pos is None:
                root.after(0, _destroy_tip)
                print("[AUTO-SELL] Setup cancelled.")
                return
            positions[key] = pos
            print(f"[AUTO-SELL] Captured {key}: {pos}")

        root.after(0, _destroy_tip)
        self.positions = positions
        print("[AUTO-SELL] Setup complete.")

    def _wait_for_click_or_esc(self):
        """Block until left-click or Escape. Returns (x,y) or None."""
        import threading
        import ctypes.wintypes
        result = [None]
        cancelled = [False]
        evt = threading.Event()

        def on_esc(_):
            cancelled[0] = True
            evt.set()

        esc_hook = keyboard.on_press_key('escape', on_esc)

        if mouse_module:
            def on_click():
                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                result[0] = (pt.x, pt.y)
                evt.set()
            mouse_hook = mouse_module.on_click(on_click)
            evt.wait()
            mouse_module.unhook(mouse_hook)
        else:
            import ctypes
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

    def _execute_sequence(self):
        """Perform the sell sequence."""
        self._executing = True
        inp = self.hub.input
        try:
            if self.camlock:
                inp.send_key(self.camlock_key_scan, key_up=False)
                time.sleep(0.05)
                inp.send_key(self.camlock_key_scan, key_up=True)
                time.sleep(0.3)

            # Press stash key
            inp.press_game_key(self.open_stash_key)
            delay = self.step_delays.get('open_stash', self.default_delay)
            if not self._wait_delay(delay):
                return

            # Click each step
            for step_id, _label in self.steps:
                if self._stop_flag or not self._active:
                    return
                pos = self.positions.get(step_id)
                if pos:
                    inp.click_at_screen(pos[0], pos[1])
                delay = self.step_delays.get(step_id, self.default_delay)
                if not self._wait_delay(delay):
                    return
        finally:
            if self.camlock:
                inp.send_key(self.camlock_key_scan, key_up=False)
                time.sleep(0.05)
                inp.send_key(self.camlock_key_scan, key_up=True)
            self._executing = False

    def _wait_delay(self, delay):
        """Wait for delay seconds, checking stop conditions."""
        deadline = time.time() + delay
        while time.time() < deadline:
            if self._stop_flag or not self._active or not self.hub.running:
                return False
            time.sleep(0.05)
        return True

    def _loop(self):
        while self.hub.running:
            if not self._active or not self.hub.focus.is_focused():
                time.sleep(0.1)
                continue
            if not self.positions:
                time.sleep(0.1)
                continue

            self._execute_sequence()

            self._deadline = time.time() + self.interval
            while time.time() < self._deadline:
                if self._stop_flag or not self._active or not self.hub.running:
                    break
                time.sleep(0.1)
            self._deadline = 0

    @staticmethod
    def fmt_interval(seconds):
        """Format seconds as human-readable e.g. '5m 0s'."""
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
