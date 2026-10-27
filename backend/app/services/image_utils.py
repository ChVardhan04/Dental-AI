"""Shared image helpers: safe decoding, sanitisation and colour-space tissue masks."""
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard
WORKING_MAX_SIDE = 1024

MAGIC = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/webp": [b"RIFF"],
}


def sniff_mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ImageDecodeError(ValueError):
    pass


def decode_and_sanitize(data: bytes) -> tuple[np.ndarray, bytes, dict]:
    """Decode, apply EXIF orientation, drop ALL metadata and re-encode as PNG.

    Returns (rgb array, sanitised PNG bytes, info). Re-encoding neutralises payloads hidden in
    metadata/trailing bytes.
    """
    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()
        with Image.open(BytesIO(data)) as img:
            had_exif = bool(img.info.get("exif")) or bool(getattr(img, "getexif", lambda: {})())
            frames = getattr(img, "n_frames", 1)
            orientation_fixed = False
            try:
                exif = img.getexif()
                orientation_fixed = exif.get(0x0112, 1) not in (1, None)
            except Exception:
                pass
            img = ImageOps.exif_transpose(img)
            rgb = img.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ImageDecodeError("Image dimensions are too large to process safely.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ImageDecodeError("The file could not be decoded as an image.") from exc
    out = BytesIO()
    rgb.save(out, format="PNG", optimize=True)
    return np.array(rgb), out.getvalue(), {"metadata_removed": had_exif, "orientation_corrected": orientation_fixed, "frames": frames}


def load_rgb(data: bytes) -> np.ndarray:
    with Image.open(BytesIO(data)) as img:
        return np.array(img.convert("RGB"))


def working_copy(rgb: np.ndarray, max_side: int = WORKING_MAX_SIDE) -> tuple[np.ndarray, float]:
    h, w = rgb.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return rgb, scale


def tooth_mask(rgb: np.ndarray) -> np.ndarray:
    """Enamel-like pixels: bright, low-to-moderate saturation, warm-white hue."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (v > 120) & (s < 95) & ((h <= 35) | (h >= 160) | (s < 40))
    mask = mask.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return mask


def soft_tissue_mask(rgb: np.ndarray) -> np.ndarray:
    """Gingiva / lip / mucosa: red-pink hues with meaningful saturation."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = (((h <= 12) | (h >= 160)) & (s > 70) & (v > 50)).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def is_grayscale(rgb: np.ndarray) -> bool:
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    return float((np.abs(r - g) + np.abs(g - b)).mean()) < 6.0


def largest_component_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, _ = stats[i]
    return int(x), int(y), int(w), int(h)


def tooth_row_bbox(tmask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box of the visible tooth row (individual teeth merged across interproximal gaps)."""
    h, w = tmask.shape[:2]
    kx = max(3, int(w * 0.05)) | 1
    merged = cv2.morphologyEx(tmask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, max(3, int(h * 0.02)) | 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats((merged > 0).astype(np.uint8), 8)
    if n <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = stats[1:][areas >= 0.25 * areas.max()]
    x0, y0 = int(big[:, 0].min()), int(big[:, 1].min())
    x1 = int((big[:, 0] + big[:, 2]).max())
    y1 = int((big[:, 1] + big[:, 3]).max())
    return x0, y0, x1 - x0, y1 - y0


def fill_holes(mask: np.ndarray, k: int = 15) -> np.ndarray:
    """Close small gaps, then fill every region fully enclosed by the mask (e.g. stains inside a tooth)."""
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    contours, _ = cv2.findContours((closed > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(closed)
    cv2.drawContours(filled, contours, -1, 255, -1)
    return filled


def encode_png(rgb: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise ValueError("Unable to encode image")
    return buf.tobytes()
