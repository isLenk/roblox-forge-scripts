"""GO screen detector for Forge auto-phase advancement."""

import cv2
import numpy as np
import time
import mss
from threading import Thread


class GoDetector:
    """Watch for the large green GO text and advance phase."""

    def __init__(self, hub, mod):
        self.hub = hub
        self.mod = mod
        self._thread = None

    def start(self):
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _loop(self):
        sct = mss.mss()
        cooldown_until = 0

        go_green_lo = np.array([35, 80, 80])
        go_green_hi = np.array([85, 255, 255])

        while self.hub.running:
            if not self.mod.auto_phase or not self.hub.focus.is_focused():
                time.sleep(0.2)
                continue

            if time.time() < cooldown_until:
                time.sleep(0.1)
                continue

            mon = self.hub.monitors.rect
            shot = sct.grab(mon)
            frame = np.array(shot)[:, :, :3]
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            h, w = frame.shape[:2]
            cx1, cx2 = int(w * 0.3), int(w * 0.7)
            cy1, cy2 = int(h * 0.3), int(h * 0.7)
            center_hsv = hsv[cy1:cy2, cx1:cx2]

            go_mask = cv2.inRange(center_hsv, go_green_lo, go_green_hi)
            green_count = int(np.count_nonzero(go_mask))

            if green_count > 5000:
                print(f"[GO] Detected ({green_count} green px) -> advancing")
                self.mod._advance_phase()
                cooldown_until = time.time() + 3.0

            time.sleep(0.15)
