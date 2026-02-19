"""Bar game auto-player for Forge casting/shaping minigames."""

import cv2
import numpy as np
import time
import random
import mss
from threading import Thread


class BarGame:
    """Auto-play the yellow bar minigame: hold click to rise, release to fall."""

    def __init__(self, hub, mod):
        self.hub = hub
        self.mod = mod
        self.active = False
        self.shaping = False
        self._thread = None

    def start(self):
        self.active = True
        if not self._thread or not self._thread.is_alive():
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.active = False
        self.shaping = False

    def _loop(self):
        sct = mss.mss()
        inp = self.hub.input
        clicking = False

        bar_yellow_lo = np.array([18, 25, 30])
        bar_yellow_hi = np.array([50, 255, 200])

        crop_region = None
        crop_ox = 0

        white_lo = np.array([0, 0, 170])
        white_hi = np.array([180, 60, 255])
        yellow_gone_since = 0
        last_shape_click = 0

        while self.hub.running:
            if not self.active or not self.hub.focus.is_focused():
                if clicking:
                    inp.send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                crop_region = None
                yellow_gone_since = 0
                self.hub.root.after(0, self.mod._hide_bar_overlays)
                if self.shaping:
                    self.shaping = False
                    self.hub.root.after(0, self.mod._refresh_gui)
                time.sleep(0.05)
                continue

            mon = self.hub.monitors.rect

            if crop_region is None or crop_region.get('_mon') != mon:
                crop_ox = mon['width'] * 3 // 4
                crop_h = int(mon['height'] * 0.85)
                crop_region = {
                    'left': mon['left'] + crop_ox,
                    'top': mon['top'],
                    'width': mon['width'] - crop_ox,
                    'height': crop_h,
                    '_mon': mon,
                }
                top_margin = int(crop_h * 0.10)

            frame = np.array(sct.grab(crop_region))[:, :, :3]
            frame = cv2.resize(frame, None, fx=0.5, fy=0.5,
                               interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            yellow_mask = cv2.inRange(hsv, bar_yellow_lo, bar_yellow_hi)
            yellow_coords = np.where(yellow_mask > 0)
            yellow_ys = yellow_coords[0]
            yellow_xs = yellow_coords[1]

            if self.shaping:
                if clicking:
                    inp.send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                self.hub.root.after(0, self.mod._hide_bar_overlays)
                now = time.time()
                if now - last_shape_click >= 0.15:
                    jx = random.randint(-15, 15)
                    jy = random.randint(-15, 15)
                    cx = mon['left'] + int(mon['width'] * 0.6) + jx
                    cy = mon['top'] + int(mon['height'] * 0.5) + jy
                    abs_x, abs_y = inp.screen_to_abs(cx, cy)
                    inp.send_mouse(
                        0x8000 | 0x4000 | 0x0001 | 0x0002, abs_x, abs_y)
                    time.sleep(0.03)
                    inp.send_mouse(
                        0x8000 | 0x4000 | 0x0001 | 0x0004, abs_x, abs_y)
                    last_shape_click = now
                continue

            if len(yellow_ys) < 20:
                if clicking:
                    inp.send_mouse(0x8000 | 0x4000 | 0x0004)
                    clicking = False
                self.hub.root.after(0, self.mod._hide_bar_overlays)
                if yellow_gone_since == 0:
                    yellow_gone_since = time.time()
                elif time.time() - yellow_gone_since >= 1.0:
                    self.shaping = True
                    last_shape_click = 0
                    self.hub.root.after(0, self.mod._refresh_gui)
                continue

            yellow_gone_since = 0

            y_min = int(np.percentile(yellow_ys, 5))
            y_max = int(np.percentile(yellow_ys, 95))
            x_min = int(np.percentile(yellow_xs, 5))
            x_max = int(np.percentile(yellow_xs, 95))
            yellow_cy = y_min + int((y_max - y_min) * 0.625)
            bar_width = x_max - x_min

            white_mask = cv2.inRange(hsv, white_lo, white_hi)
            white_mask[:top_margin, :] = 0

            white_ys = np.where(white_mask > 0)[0]
            white_count = len(white_ys)
            white_cy = int(np.median(white_ys)) if white_count > 5 else None

            bar_scr_x = mon['left'] + crop_ox + x_min * 2
            bar_scr_y = mon['top'] + yellow_cy * 2
            bar_scr_w = max(bar_width * 2, 20)
            slit_scr_y = (
                (mon['top'] + white_cy * 2) if white_cy is not None else None)
            col_l_scr = mon['left'] + crop_ox
            col_r_scr = mon['left'] + mon['width']
            bot_scr = mon['top'] + crop_region['height']

            self.hub.root.after(
                0, lambda bx=bar_scr_x, by=bar_scr_y, sy=slit_scr_y,
                bw=bar_scr_w, cl=col_l_scr, cr=col_r_scr, bs=bot_scr:
                self.mod._update_bar_overlays(bx, by, sy, bw, cl, cr, bs))

            if white_cy is None:
                continue

            abs_x, abs_y, _, _ = inp.get_abs_coords()

            bar_half = max((y_max - y_min) // 2, 1)
            deadband = max(5, bar_half // 4)

            if white_cy > yellow_cy + deadband:
                if not clicking:
                    inp.send_mouse(
                        0x8000 | 0x4000 | 0x0002, abs_x, abs_y)
                    clicking = True
            elif white_cy < yellow_cy - deadband:
                if clicking:
                    inp.send_mouse(
                        0x8000 | 0x4000 | 0x0004, abs_x, abs_y)
                    clicking = False
