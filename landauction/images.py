"""Validate and normalise uploaded property photos.

Every upload is decoded and re-encoded as JPEG, which rejects non-images,
applies the camera's rotation, caps the size, and drops all metadata
(including GPS coordinates baked into phone photos).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE = 1600
THUMB_SIZE = (360, 240)
Image.MAX_IMAGE_PIXELS = 60_000_000  # refuse decompression bombs


class ImageError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    full: bytes
    thumb: bytes
    width: int
    height: int


def _jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def process(raw: bytes) -> ProcessedImage:
    if not raw:
        raise ImageError("The file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError("Photos must be 10 MB or smaller.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ImageError("That file isn't a valid image. Use JPG, PNG or WebP.") from exc

    full = img.copy()
    full.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    thumb = ImageOps.fit(img, THUMB_SIZE, Image.Resampling.LANCZOS)
    return ProcessedImage(_jpeg(full, 82), _jpeg(thumb, 78), full.width, full.height)
