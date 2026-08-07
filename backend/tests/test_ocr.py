from PIL import Image

import mock_ocr
import ocr


def _img(w=200, h=100, color=(120, 60, 200)):
    return Image.new("RGB", (w, h), color)


def test_mock_read_plate_text_is_deterministic():
    crop = _img()
    first = mock_ocr.read_plate_text(crop)
    second = mock_ocr.read_plate_text(_img())
    assert first == second
    assert len(first) == 1
    assert 0.5 <= first[0]["confidence"] <= 1.0
    assert first[0]["text"]


def test_mock_read_plate_text_varies_by_image_content():
    a = mock_ocr.read_plate_text(_img(color=(10, 10, 10)))
    b = mock_ocr.read_plate_text(_img(color=(250, 250, 250)))
    assert a != b


def test_crop_for_ocr_stays_within_bounds():
    frame = _img(w=100, h=80)
    box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
    crop = ocr.crop_for_ocr(frame, box, pad_frac=0.5)
    assert 0 < crop.width <= frame.width
    assert 0 < crop.height <= frame.height


def test_crop_for_ocr_handles_swapped_coordinates():
    frame = _img(w=100, h=80)
    box = {"x1": 60, "y1": 50, "x2": 20, "y2": 10}
    crop = ocr.crop_for_ocr(frame, box)
    assert crop.width > 0 and crop.height > 0


def test_crop_for_ocr_near_far_edge():
    frame = _img(w=100, h=80)
    box = {"x1": 90, "y1": 70, "x2": 100, "y2": 80}
    crop = ocr.crop_for_ocr(frame, box, pad_frac=0.5)
    assert crop.width > 0 and crop.height > 0
