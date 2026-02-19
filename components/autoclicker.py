"""Autoclicker component — clicks at cursor position at a fixed interval."""

import time
from threading import Thread

from components.base import Component


class AutoclickerComponent(Component):
    """Clicks at cursor position every `interval` seconds while active."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self.interval = config.get('interval', 0.1)
        self._thread = None
        self._paused = False  # external pause (e.g. during auto-sell)

    @property
    def paused(self):
        return self._paused

    @paused.setter
    def paused(self, value):
        self._paused = value

    def start(self):
        self._active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()
        print(f"[AUTOCLICK] ON")

    def stop(self):
        self._active = False
        print(f"[AUTOCLICK] OFF")

    def _loop(self):
        inp = self.hub.input
        while self.hub.running:
            if not self._active or not self.hub.focus.is_focused() or self._paused:
                time.sleep(0.05)
                continue
            abs_x, abs_y, _, _ = inp.get_abs_coords()
            inp.send_mouse(0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
            time.sleep(0.03)
            inp.send_mouse(0x8000 | 0x4000 | 0x0004, abs_x, abs_y)
            time.sleep(max(0.01, self.interval - 0.03))
