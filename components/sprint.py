"""Sprint component — holds LeftShift while WASD is pressed."""

import ctypes
import time
from threading import Thread

from components.base import Component
from core.input import SCAN_LSHIFT, WASD_VK


class SprintComponent(Component):
    """Hold LeftShift while any WASD key is pressed."""

    def __init__(self, hub, mod, **config):
        super().__init__(hub, mod, **config)
        self._shift_scan = config.get('shift_scan', SCAN_LSHIFT)
        self._movement_vks = config.get('movement_vks', WASD_VK)
        self._thread = None

    def start(self):
        self._active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()
        print("[SPRINT] ON")

    def stop(self):
        self._active = False
        self.hub.input.send_key(self._shift_scan, key_up=True)
        print("[SPRINT] OFF")

    def _loop(self):
        GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
        inp = self.hub.input
        shift_held = False
        while self.hub.running:
            if self._active and self.hub.focus.is_focused():
                wasd_pressed = any(
                    GetAsyncKeyState(vk) & 0x8000
                    for vk in self._movement_vks)
                if wasd_pressed and not shift_held:
                    inp.send_key(self._shift_scan, key_up=False)
                    shift_held = True
                elif not wasd_pressed and shift_held:
                    inp.send_key(self._shift_scan, key_up=True)
                    shift_held = False
            else:
                if shift_held:
                    inp.send_key(self._shift_scan, key_up=True)
                    shift_held = False
            time.sleep(0.02)
