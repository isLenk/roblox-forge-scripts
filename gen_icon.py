"""
Regenerate assets/logo.png and assets/icon.ico from assets/logo.svg.

logo.png : rendered at high-res then cropped/resized to 160×63
icon.ico : each size rendered natively by Chrome via an HTML wrapper
           → logo fills 92% of icon width, centred, transparent background
"""
import subprocess, tempfile
from pathlib import Path
from PIL import Image
import numpy as np

ASSETS = Path(__file__).resolve().parent / 'assets'
SVG    = ASSETS / 'logo.svg'
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# ── low-level: render an HTML file with Chrome ───────────────────────────────
def _chrome_render(html: str, out_png: Path, w: int, h: int,
                   bg: str = '00000000') -> None:
    tmp = Path(tempfile.mktemp(suffix='.html'))
    tmp.write_text(html, encoding='utf-8')
    try:
        subprocess.run([
            CHROME, '--headless=new',
            f'--screenshot={out_png}',
            f'--default-background-color={bg}',
            f'--window-size={w},{h}',
            '--hide-scrollbars',
            '--force-device-scale-factor=1',
            tmp.as_uri(),
        ], check=True, capture_output=True)
    finally:
        tmp.unlink(missing_ok=True)


def _load_rgba(path: Path) -> Image.Image:
    return Image.open(str(path)).convert('RGBA')


# ── crop to non-transparent content (ignores near-zero alpha noise) ──────────
def _crop(img: Image.Image, threshold: int = 8) -> Image.Image:
    arr = np.array(img)
    a = arr[:, :, 3]
    rows = np.where(np.any(a > threshold, axis=1))[0]
    cols = np.where(np.any(a > threshold, axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        return img
    return img.crop((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))


# ── attempt a transparent render; fallback to BG-keying ──────────────────────
def _render_transparent(html: str, w: int, h: int) -> Image.Image:
    out = Path(tempfile.mktemp(suffix='.png'))
    try:
        _chrome_render(html, out, w, h, bg='00000000')
        img = _load_rgba(out)
        arr = np.array(img)
        if arr[:, :, 3].min() < 200:          # real alpha → great
            return img
        # Chrome gave us a solid background; re-render with a known dark BG
        # and key it out.
        html_dark = html.replace('background: transparent', 'background: #0d1117')
        _chrome_render(html_dark, out, w, h, bg='0d1117ff')
        img = _load_rgba(out)
        arr = np.array(img)
        bg_col = np.array([0x0d, 0x11, 0x17], dtype=float)
        dist = np.sqrt(((arr[:, :, :3].astype(float) - bg_col) ** 2).sum(axis=2))
        arr[dist < 35, 3] = 0
        return Image.fromarray(arr, 'RGBA')
    finally:
        out.unlink(missing_ok=True)


SVG_URI = SVG.as_uri()

def _logo_html(canvas_w: int, canvas_h: int, logo_w_px: int) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  html, body {{
    margin:0; padding:0;
    width:{canvas_w}px; height:{canvas_h}px;
    overflow:hidden;
    background:transparent;
    display:flex; align-items:center; justify-content:center;
  }}
  img {{ width:{logo_w_px}px; height:auto; display:block; }}
</style>
</head>
<body><img src="{SVG_URI}"></body>
</html>"""


# ══ 1. logo.png ══════════════════════════════════════════════════════════════
# Render at 3× native SVG resolution (SVG is ~577×227), crop, resize to 160×63
print("Rendering logo.png (high-res)…")
LR_W, LR_H = 1734, 760
html_lr = _logo_html(LR_W, LR_H, LR_W)
img_lr  = _render_transparent(html_lr, LR_W, LR_H)
img_lr  = _crop(img_lr)
# Resize proportionally to target height, then add a transparent margin
# so edge pixels aren't clipped by the widget renderer
target_h = 55
target_w = round(img_lr.width * target_h / img_lr.height)
resized = img_lr.resize((target_w, target_h), Image.LANCZOS)
PAD_TOP, PAD_BOT, PAD_H = 0, 16, 6
logo_save = Image.new('RGBA', (target_w + PAD_H*2, target_h + PAD_TOP + PAD_BOT), (0,0,0,0))
logo_save.paste(resized, (PAD_H, PAD_TOP), resized)
logo_save.save(str(ASSETS / 'logo.png'))
print(f"  saved logo.png  {logo_save.size}")


# ══ 2. icon.ico ══════════════════════════════════════════════════════════════
# Render each size natively so Chrome handles SVG scaling — no PIL downscaling
sizes  = [256, 128, 64, 48, 32, 16]
frames: list[Image.Image] = []

for s in sizes:
    fill = round(s * 0.92)
    print(f"  rendering {s}×{s} (logo {fill}px wide)…", end=' ', flush=True)
    html = _logo_html(s, s, fill)
    frame = _render_transparent(html, s, s)
    frames.append(frame)
    print("ok")

ico_path = ASSETS / 'icon.ico'
frames[0].save(str(ico_path), format='ICO', append_images=frames[1:])
print(f"Saved icon.ico  ({', '.join(str(s) for s in sizes)} px)")
print("Done.")
