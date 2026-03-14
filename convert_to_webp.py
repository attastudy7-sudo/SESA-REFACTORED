"""Convert all PNG/JPG images in app/static/images to WebP (80% quality)."""
import subprocess
import sys
from pathlib import Path

images_dir = Path("app/static/images")

# Try using Pillow first (pip install Pillow)
try:
    from PIL import Image
    converted = 0
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for img_path in images_dir.glob(ext):
            webp_path = img_path.with_suffix(".webp")
            if webp_path.exists():
                print(f"  SKIP (exists): {webp_path.name}")
                continue
            with Image.open(img_path) as img:
                img.save(webp_path, "WEBP", quality=80)
            original_kb = img_path.stat().st_size // 1024
            new_kb = webp_path.stat().st_size // 1024
            print(f"  ✓ {img_path.name} → {webp_path.name}  ({original_kb}KB → {new_kb}KB)")
            converted += 1
    print(f"\nDone. {converted} file(s) converted.")
except ImportError:
    print("Pillow not installed. Run:  pip install Pillow")
    sys.exit(1)
