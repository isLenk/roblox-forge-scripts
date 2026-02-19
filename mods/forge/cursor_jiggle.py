"""Cursor jiggle for Forge smelting minigame."""

import time
from threading import Thread


class CursorJiggle:
    """Moves cursor up and down for the smelting minigame."""

    def __init__(self, hub, mod):
        self.hub = hub
        self.mod = mod
        self.active = False
        self.period = 0.1
        self._thread = None

    def start(self):
        self.active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.active = False

    def _loop(self):
        import ctypes
        import ctypes.wintypes
        inp = self.hub.input
        steps = 30
        going_up = True

        while self.hub.running:
            if not self.active or not self.hub.focus.is_focused():
                time.sleep(0.05)
                going_up = True
                continue

            mon = self.hub.monitors.rect
            mon_top = mon['top']
            jiggle_top = int(mon['height'] * 0.20)
            jiggle_bottom = int(mon['height'] * 0.80)

            step_delay = self.period / steps

            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            cur_y = pt.y

            if going_up:
                target_y = mon_top + jiggle_top
            else:
                target_y = mon_top + jiggle_bottom

            total_dy = target_y - cur_y
            for i in range(steps):
                if not self.active:
                    break
                dy = (int(total_dy * (i + 1) / steps)
                      - int(total_dy * i / steps))
                inp.send_relative_move(0, dy)
                time.sleep(step_delay)

            going_up = not going_up
