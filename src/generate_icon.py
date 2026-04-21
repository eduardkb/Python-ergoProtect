"""
generate_icon.py – run once to create assets/icon.ico
Not part of the application itself; used during development.
"""
import os
from PIL import Image, ImageDraw

def make_icon(path: str) -> None:
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Green rounded-rectangle background
    draw.ellipse([4, 4, size - 4, size - 4], fill=(46, 160, 67, 255))

    # White cross
    bar = 40
    arm = 70
    cx, cy = size // 2, size // 2
    draw.rectangle([cx - bar // 2, cy - arm, cx + bar // 2, cy + arm], fill="white")
    draw.rectangle([cx - arm, cy - bar // 2, cx + arm, cy + bar // 2], fill="white")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Save as multi-size ICO (includes 16, 32, 48, 256)
    img_256 = img.resize((256, 256), Image.LANCZOS)
    img_48  = img.resize((48, 48),   Image.LANCZOS)
    img_32  = img.resize((32, 32),   Image.LANCZOS)
    img_16  = img.resize((16, 16),   Image.LANCZOS)
    img_256.save(path, format="ICO", sizes=[(256,256),(48,48),(32,32),(16,16)],
                 append_images=[img_48, img_32, img_16])
    print(f"Icon saved to {path}")

if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    make_icon(os.path.join(root, "assets", "icon.ico"))
