"""
generate_icon.py – run once to create assets/icon.ico
Not part of the application itself; used during development.

Icon style: modern outlined computer mouse (blue→purple gradient) with bold
"EP" letters centred on the body. Transparent background.
"""
import os
from PIL import Image, ImageDraw, ImageFont

_MODULE = "generate_icon"


def make_icon(path: str) -> None:
    try:
        from AppLogging import log_info
        _log = log_info
    except Exception:
        _log = None

    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    BLUE   = (70,  110, 245, 255)
    PURPLE = (160,  60, 245, 255)
    W = 8

    def lerp(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))

    def thick_arc(bbox, start, end, color, width=W):
        for d in range(width):
            off = d - width // 2
            b = [bbox[0]+off, bbox[1]+off, bbox[2]-off, bbox[3]-off]
            draw.arc(b, start, end, fill=color, width=1)

    # ── Mouse body ───────────────────────────────────────────────────────────
    mx0, mx1 = 72, 184
    my_top, my_bot = 48, 210
    mr_top, mr_bot = 56, 22

    c0 = lerp(BLUE, PURPLE, 0.0)
    c1 = lerp(BLUE, PURPLE, 0.5)
    c2 = lerp(BLUE, PURPLE, 1.0)

    thick_arc([mx0, my_top, mx1, my_top + 2*mr_top], 180, 360, c0)
    draw.line([(mx0, my_top + mr_top), (mx0, my_bot - mr_bot)], fill=c1, width=W)
    draw.line([(mx1, my_top + mr_top), (mx1, my_bot - mr_bot)], fill=c1, width=W)
    thick_arc([mx0,        my_bot - 2*mr_bot, mx0 + 2*mr_bot, my_bot],  90, 180, c2)
    thick_arc([mx1 - 2*mr_bot, my_bot - 2*mr_bot, mx1,        my_bot],   0,  90, c2)
    draw.line([(mx0 + mr_bot, my_bot), (mx1 - mr_bot, my_bot)], fill=c2, width=W)

    # ── Centre dividing line (left/right click buttons) ───────────────────────
    cx = (mx0 + mx1) // 2
    div_y_top = my_top + mr_top + 4
    div_y_bot = my_top + mr_top + 52
    draw.line([(cx, div_y_top), (cx, div_y_bot)], fill=lerp(BLUE, PURPLE, 0.15), width=W - 2)

    # ── Scroll wheel ──────────────────────────────────────────────────────────
    wheel_cy = div_y_bot + 20
    draw.rounded_rectangle(
        [cx - 7, wheel_cy - 14, cx + 7, wheel_cy + 14],
        radius=7, outline=lerp(BLUE, PURPLE, 0.25), width=W - 3)

    # ── "EP" text ─────────────────────────────────────────────────────────────
    text = "EP"
    font_size = 72
    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
            break
    if font is None:
        font = ImageFont.load_default()

    tbbox = draw.textbbox((0, 0), text, font=font)
    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]
    tx = (S - tw) // 2 - tbbox[0]
    ty = (S - th) // 2 - tbbox[1] + 18

    # Coloured stroke behind, then white fill on top
    stroke_col = lerp(BLUE, PURPLE, 0.5)
    for dx, dy in [(-3,0),(3,0),(0,-3),(0,3),(-2,-2),(2,-2),(-2,2),(2,2),(-3,-1),(3,-1),(-3,1),(3,1)]:
        draw.text((tx + dx, ty + dy), text, font=font, fill=stroke_col)
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

    # ── Save multi-size ICO ───────────────────────────────────────────────────
    os.makedirs(os.path.dirname(path), exist_ok=True)
    imgs = [img.resize((s, s), Image.LANCZOS) for s in (256, 48, 32, 16)]
    imgs[0].save(path, format="ICO", sizes=[(256,256),(48,48),(32,32),(16,16)],
                 append_images=imgs[1:])

    if _log:
        _log(_MODULE, "Icon saved to %s", path)
    print(f"Icon saved to {path}")


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    make_icon(os.path.join(root, "assets", "icon.ico"))
