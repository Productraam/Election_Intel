"""Generate simple PWA icons using PIL."""
import os
from PIL import Image, ImageDraw, ImageFont

def make_icon(size, path):
    img = Image.new('RGBA', (size, size), (15, 17, 23, 255))
    draw = ImageDraw.Draw(img)
    # Orange circle
    cx, cy, r = size//2, size//2, int(size*0.38)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(249, 115, 22, 255))
    # EI text
    fs = int(size * 0.32)
    try:
        font = ImageFont.truetype("arial.ttf", fs)
    except Exception:
        font = ImageFont.load_default()
    draw.text((cx, cy), "EI", fill=(255,255,255,255), font=font, anchor="mm")
    img.save(path, 'PNG')
    print(f'  Created {path} ({size}x{size})')

icons_dir = os.path.join(os.path.dirname(__file__), 'static', 'icons')
os.makedirs(icons_dir, exist_ok=True)
make_icon(192, os.path.join(icons_dir, 'icon-192.png'))
make_icon(512, os.path.join(icons_dir, 'icon-512.png'))
print('Done')
