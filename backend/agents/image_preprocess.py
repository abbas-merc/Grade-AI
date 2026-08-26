"""
image_preprocess.py — Image enhancement applied before an answer photo is sent
to the AI model, to improve handwriting recognition accuracy.

The enhancement pipeline (in this exact order) is:
    1. convert to grayscale
    2. ImageFilter.SHARPEN applied twice
    3. contrast x1.5  (ImageEnhance.Contrast)
    4. sharpness x2.0 (ImageEnhance.Sharpness)

The result is re-encoded as a high-quality JPEG (quality 95). Resolution is
never reduced — no resizing or downscaling is performed.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageEnhance, ImageFilter

# Quality for the re-encoded JPEG. Must stay >= 95 (high quality).
JPEG_QUALITY = 95

# Decompression-bomb guard: a small crafted file can claim enormous pixel
# dimensions and blow up memory when decoded. Cap the pixel count Pillow will
# accept; a genuine phone photo (even 50 MP) is far below this. Pillow raises
# Image.DecompressionBombError past the cap, which enhance_image_base64 catches
# and turns into "return the original bytes" (grading is never blocked, and the
# oversized image simply isn't decoded server-side).
Image.MAX_IMAGE_PIXELS = 60_000_000  # ~60 MP


def enhance_image_base64(image_base64: str) -> str:
    """
    Enhance a raw (prefix-stripped) base64 image for handwriting OCR.

    Args:
        image_base64: Raw base64 image data with no data-URI prefix.

    Returns:
        Raw base64 of the enhanced image, JPEG-encoded at quality >= 95.
        Resolution is preserved. On any failure the original input is returned
        unchanged so grading is never blocked by a preprocessing error.
    """
    try:
        raw = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(raw))

        # 1. Grayscale.
        img = img.convert("L")
        # 2. Sharpen twice.
        img = img.filter(ImageFilter.SHARPEN)
        img = img.filter(ImageFilter.SHARPEN)
        # 3. Contrast x1.5.
        img = ImageEnhance.Contrast(img).enhance(1.5)
        # 4. Sharpness x2.0.
        img = ImageEnhance.Sharpness(img).enhance(2.0)

        # Re-encode as high-quality JPEG without resizing/downscaling.
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        print(f"[preprocess] image enhancement failed, using original: {exc}")
        return image_base64
