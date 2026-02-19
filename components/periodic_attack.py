"""Periodic attack component — press two keys in sequence on a timer."""

import time
from threading import Thread

from components.base import Component


class PeriodicAttackComponent(Component):
    """Periodically press two keys in sequence while active."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self.key1 = config.get('key1', '2')
        self.key2 = config.get('key2', '1')
        self.delay_after_key1 = config.get('delay_after_key1', 1.0)
        self.cycle_period = config.get('cycle_period', 3.0)
        self._requires_autoclicker = config.get('requires_autoclicker', True)
        self._thread = None

    def start(self):
        self._active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()
        print("[PERIODIC] ON")

    def stop(self):
        self._active = False
        print("[PERIODIC] OFF")

    def _should_run(self):
        """Check if conditions are met to run."""
        if not self._active or not self.hub.focus.is_focused():
            return False
        if self._requires_autoclicker:
            ac = getattr(self.mod, 'autoclicker', None)
            if ac and not ac.active:
                return False
        return True

    def _loop(self):
        inp = self.hub.input
        while self.hub.running:
            if not self._should_run():
                time.sleep(0.05)
                continue
            # Press first key
            inp.press_game_key(self.key1)
            # Wait delay
            deadline = time.time() + self.delay_after_key1
            while time.time() < deadline:
                if not self._should_run() or not self.hub.running:
                    break
                time.sleep(0.05)
            if not self._should_run() or not self.hub.running:
                continue
            # Press second key
            inp.press_game_key(self.key2)
            # Wait remaining cycle time
            remaining = self.cycle_period - self.delay_after_key1
            if remaining > 0:
                deadline = time.time() + remaining
                while time.time() < deadline:
                    if not self._should_run() or not self.hub.running:
                        break
                    time.sleep(0.05)
