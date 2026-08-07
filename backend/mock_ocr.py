"""Mock plate OCR — deterministic fake text, no GPU/easyocr needed.

Active when LA_MOCK=1, mirroring mock_engine.py's MockEngine: same
`read_plate_text(crop) -> list[dict]` shape as ocr.py's real implementation,
so clips.py can pick between them without branching on shape.
"""

from __future__ import annotations

import hashlib

from PIL import Image


def read_plate_text(crop: Image.Image) -> list[dict]:
    seed_bytes = crop.resize((8, 8)).convert("L").tobytes()
    seed = int(hashlib.sha256(seed_bytes).hexdigest(), 16)
    letters = "".join(chr(65 + (seed >> (i * 5)) % 26) for i in range(3))
    digits = seed % 9000 + 1000
    confidence = 0.5 + (seed % 50) / 100
    return [{"text": f"{letters} {digits}", "confidence": confidence}]
