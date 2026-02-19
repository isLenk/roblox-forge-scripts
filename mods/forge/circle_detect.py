"""Circle detection for Forge welding minigame."""

import cv2
import numpy as np
import time
import mss
from threading import Thread


class CircleDetector:
    """Detects OSU-style shrinking circles and clicks when they turn green."""

    def __init__(self, hub, mod):
        self.hub = hub
        self.mod = mod
        self.active = False

        # Tunable parameters
        self.scan_scale = 0.5
        self.min_area = 40

        # Green/lime ring HSV range
        self.green_lo = np.array([28, 55, 65])
        self.green_hi = np.array([75, 255, 255])

        # White ring HSV range
        self.white_lo = np.array([0, 0, 210])
        self.white_hi = np.array([180, 40, 255])

        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self._thread = None

    def start(self):
        self.active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.active = False

    def _find_targets(self, hsv, lo, hi):
        """Return list of (cx, cy, area) for circular color-matched regions."""
        h_frame, w_frame = hsv.shape[:2]
        margin_x = int(w_frame * 0.20)
        margin_y = int(h_frame * 0.10)

        mask = cv2.inRange(hsv, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        targets = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue
            x_r, y_r, w_r, h_r = cv2.boundingRect(c)
            if w_r == 0 or h_r == 0:
                continue
            aspect = max(w_r, h_r) / min(w_r, h_r)
            if aspect > 2.0:
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(c)
            if radius < 5:
                continue
            circle_area = np.pi * radius * radius
            fill = area / circle_area
            if fill < 0.20:
                continue
            if cx < margin_x or cx > w_frame - margin_x:
                continue
            if cy < margin_y or cy > h_frame - margin_y:
                continue
            targets.append((int(cx), int(cy), area))

        return targets

    def _loop(self):
        sct = mss.mss()
        scale = self.scan_scale
        inv_scale = 1.0 / scale
        inp = self.hub.input

        state = "SCAN"
        cooldown_end = 0
        green_seen_at = 0
        lost_frames = 0
        track_x, track_y = 0, 0
        track_start = 0
        ring_shown = False

        while self.hub.running:
            mon = self.hub.monitors.rect

            if not self.active or not self.hub.focus.is_focused():
                state = "SCAN"
                if ring_shown:
                    self.hub.root.after(0, self.mod._hide_ring)
                    ring_shown = False
                time.sleep(0.05)
                continue

            green_delay = 0.02 * (mon['height'] / 1080)

            shot = sct.grab(mon)
            frame = np.array(shot)[:, :, :3]
            small = cv2.resize(frame, None, fx=scale, fy=scale,
                               interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

            if state == "SCAN":
                whites = self._find_targets(hsv, self.white_lo, self.white_hi)
                if whites:
                    whites.sort(key=lambda t: t[2], reverse=True)
                    sx, sy = whites[0][0], whites[0][1]
                    track_x = int(sx * inv_scale) + mon["left"]
                    track_y = int(sy * inv_scale) + mon["top"]
                    inp.move_to(track_x, track_y)
                    track_start = time.time()
                    state = "TRACK"
                    lost_frames = 0

            elif state == "TRACK":
                greens = self._find_targets(hsv, self.green_lo, self.green_hi)
                nearby = []
                for gx, gy, ga in greens:
                    rx = int(gx * inv_scale) + mon["left"]
                    ry = int(gy * inv_scale) + mon["top"]
                    dist = ((rx - track_x)**2 + (ry - track_y)**2) ** 0.5
                    if dist < 150:
                        nearby.append((gx, gy, ga))
                if nearby:
                    green_seen_at = time.time()
                    state = "READY"
                else:
                    whites = self._find_targets(
                        hsv, self.white_lo, self.white_hi)
                    if whites:
                        lost_frames = 0
                    else:
                        lost_frames += 1
                        if lost_frames > 15:
                            state = "SCAN"

            elif state == "READY":
                if time.time() - green_seen_at >= green_delay:
                    px, py = inp.click(track_x, track_y)
                    self.hub.root.after(
                        0, lambda x=px, y=py: self.mod._show_hit(x, y))
                    state = "COOLDOWN"
                    cooldown_end = time.time() + 0.4

            elif state == "COOLDOWN":
                if time.time() >= cooldown_end:
                    state = "SCAN"

            # Update targeting ring
            if state == "TRACK":
                elapsed = time.time() - track_start
                self.hub.root.after(
                    0, lambda tx=track_x, ty=track_y, e=elapsed:
                    self.mod._update_ring(tx, ty, f"{e:.1f}s"))
                ring_shown = True
            elif state == "READY":
                remaining = max(
                    0, green_delay - (time.time() - green_seen_at))
                self.hub.root.after(
                    0, lambda tx=track_x, ty=track_y, r=remaining:
                    self.mod._update_ring(
                        tx, ty, f"{r*1000:.0f}ms", '#ffaa00'))
                ring_shown = True
            elif ring_shown:
                self.hub.root.after(0, self.mod._hide_ring)
                ring_shown = False

            time.sleep(0.003)
