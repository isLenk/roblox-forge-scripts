"""Hold key component — holds a key while active and Roblox is focused."""

import time
from threading import Thread

from components.base import Component


class HoldKeyComponent(Component):
    """Hold a specific key while active and Roblox is focused."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self.scan_code = config.get('scan_code', 0x4B)  # default: left arrow
        self.extended = config.get('extended', True)
        self.display_name = config.get('display_name', 'Hold Key')
        self._thread = None

    def start(self):
        self._active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()
        print(f"[{self.display_name.upper()}] ON")

    def stop(self):
        self._active = False
        self.hub.input.send_key(
            self.scan_code, key_up=True, extended=self.extended)
        print(f"[{self.display_name.upper()}] OFF")

    def _loop(self):
        inp = self.hub.input
        was_holding = False
        while self.hub.running:
            if self._active and self.hub.focus.is_focused():
                inp.send_key(
                    self.scan_code, key_up=False, extended=self.extended)
                was_holding = True
                time.sleep(0.05)
            else:
                if was_holding:
                    inp.send_key(
                        self.scan_code, key_up=True, extended=self.extended)
                    was_holding = False
                time.sleep(0.05)
