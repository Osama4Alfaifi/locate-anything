"""License-plate OCR: crop a candidate box and read the text with EasyOCR.

Real reads need `easyocr` (heavy, GPU-capable) — imported lazily inside
`read_plate_text`, mirroring how worker.py lazy-imports torch/transformers,
so this module stays importable without it (mock mode uses mock_ocr.py
instead and never touches this file's heavy path).
"""

from __future__ import annotations

from PIL import Image

_reader = None  # lazy singleton, built on first real call


def crop_for_ocr(frame: Image.Image, box: dict, pad_frac: float = 0.15) -> Image.Image:
    """Crop `box` out of `frame` with `pad_frac` padding on each side (plates
    are often tightly boxed; a little margin helps OCR), clamped to bounds."""
    x1, y1 = min(box["x1"], box["x2"]), min(box["y1"], box["y2"])
    x2, y2 = max(box["x1"], box["x2"]), max(box["y1"], box["y2"])
    pad_x = (x2 - x1) * pad_frac
    pad_y = (y2 - y1) * pad_frac
    left = max(0, round(x1 - pad_x))
    top = max(0, round(y1 - pad_y))
    right = min(frame.width, round(x2 + pad_x))
    bottom = min(frame.height, round(y2 + pad_y))
    if right <= left:
        right = min(frame.width, left + 1)
    if bottom <= top:
        bottom = min(frame.height, top + 1)
    return frame.crop((left, top, right, bottom))


def read_plate_text(crop: Image.Image) -> list[dict]:
    """Run OCR on a cropped region. Returns text fragments ordered
    left-to-right (handles multi-part plates): [{"text", "confidence"}, ...]."""
    global _reader
    import numpy as np

    if _reader is None:
        import easyocr
        import torch

        _reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available())

    arr = np.array(crop.convert("RGB"))
    results = _reader.readtext(arr)  # [(bbox, text, confidence), ...]
    results.sort(key=lambda r: min(pt[0] for pt in r[0]))
    return [{"text": text, "confidence": float(conf)} for _bbox, text, conf in results]
