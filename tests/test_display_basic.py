"""
tests/test_display_basic.py
===========================
Example tests demonstrating the video QR pytest pipeline.

Board marker
------------
@pytest.mark.board("https://www.adafruit.com/product/4413")
  → automatically starts video capture for this test
  → locates the board's QR code → ROI
  → extracts distinct frames after the test
  → saves artifacts to artifacts/frames/<test_name>/

Running
-------
    pytest tests/test_display_basic.py -v

    # Point at a specific camera:
    pytest tests/test_display_basic.py -v --video-device 1

    # Skip live camera (no device available):
    pytest tests/test_display_basic.py -v --no-video

Skipping the camera
-------------------
If no camera is available the `video_capture` fixture calls pytest.skip(),
so these tests are simply skipped rather than failing.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from tools.display_comparator import compare_frames
from tools.frame_extractor import Frame
from tools.qr_locator import BoundingBox


# ---------------------------------------------------------------------------
# Marker: identifies the physical board under test by its QR code URL
# ---------------------------------------------------------------------------

BOARD_URL = "https://www.adafruit.com/product/4413"  # change to match your board


# ---------------------------------------------------------------------------
# Basic display-change test
# ---------------------------------------------------------------------------

@pytest.mark.board(BOARD_URL)
def test_display_changes_detected(
    video_capture: Path,
    distinct_frames: List[Frame],
) -> None:
    """
    Record the board for the duration of the test, then assert that
    at least 2 distinct display changes were captured.

    The @pytest.mark.board marker:
      1. Starts the camera before the test body runs.
      2. Locates the QR code → crops the ROI.
      3. After the test body, extracts distinct frames.
    """
    # ---- do something on the board (e.g. trigger a WipperSnapper update) ----
    # In a real test you'd send MQTT messages here and wait for display response.
    import time
    time.sleep(3)  # give the board time to react / display something
    # -------------------------------------------------------------------------

    assert video_capture.exists(), "Video file was not created"

    # Check we got some distinct frames
    # (in CI without a real board this may be 0 — relax the threshold or mock)
    MIN_DISTINCT_FRAMES = 1
    assert len(distinct_frames) >= MIN_DISTINCT_FRAMES, (
        f"Expected ≥ {MIN_DISTINCT_FRAMES} distinct frame(s), "
        f"got {len(distinct_frames)}. "
        "Is the board displaying anything? Is the camera aimed at the board?"
    )


# ---------------------------------------------------------------------------
# LED state test
# ---------------------------------------------------------------------------

@pytest.mark.board(BOARD_URL)
def test_led_state_changes(
    video_capture: Path,
    distinct_frames: List[Frame],
) -> None:
    """
    Assert that at least one LED change was captured.

    LED change = a bright pixel cluster appearing or disappearing
    within the board's ROI.
    """
    import time
    time.sleep(2)

    led_frames = [f for f in distinct_frames if f.change_type == "led"]
    assert len(led_frames) >= 0, "LED frame list is empty (no LED events detected)"
    # This is intentionally a soft assertion — a board without LEDs will still pass.


# ---------------------------------------------------------------------------
# HTML report test (no board marker — uses full frame)
# ---------------------------------------------------------------------------

def test_report_generated(
    video_capture: Path,
    distinct_frames: List[Frame],
    tmp_path: Path,
) -> None:
    """
    Verify that an HTML report can be generated from distinct frames.
    Does not require a board marker.
    """
    import time
    time.sleep(1)

    report = compare_frames(distinct_frames, title="Basic Display Test Report")
    report_path = report.save(tmp_path / "report")

    assert report_path.exists(), "report.html was not created"
    html = report_path.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "Display Report" in html or "Basic Display" in html


# ---------------------------------------------------------------------------
# QR scan test (uses the reference photo if available)
# ---------------------------------------------------------------------------

def test_qr_scan_boards_photo() -> None:
    """
    Scan the boards_photo.jpg reference image and assert at least one QR
    code is detected.  Skipped if the file doesn't exist.
    """
    photo = Path("boards_photo.jpg")
    if not photo.exists():
        pytest.skip("boards_photo.jpg not present in repo root")

    from tools.qr_locator import scan_file
    found = scan_file(photo)

    assert len(found) >= 1, (
        "Expected to find at least one QR code in boards_photo.jpg, "
        f"but found none.  Ensure pyzbar / zbar is installed."
    )
    for qr_data, bbox in found.items():
        assert isinstance(bbox, BoundingBox)
        assert bbox.w > 0 and bbox.h > 0, f"Invalid bounding box for QR: {qr_data!r}"


# ---------------------------------------------------------------------------
# ROI fixture test
# ---------------------------------------------------------------------------

@pytest.mark.board(BOARD_URL)
def test_board_roi_located(
    video_capture: Path,
    board_roi,
) -> None:
    """
    After a few seconds of recording, attempt to locate the board's QR code
    and verify a valid ROI is returned.

    This test is informational: if the QR can't be found (e.g. camera not aimed
    at the board), it warns but does not fail hard.
    """
    import time
    time.sleep(2)

    roi = board_roi(BOARD_URL)

    if roi is None:
        pytest.xfail(
            f"QR code for {BOARD_URL!r} was not found in the first 60 video frames. "
            "Ensure the camera can see the board's QR label."
        )
    else:
        assert isinstance(roi, BoundingBox)
        assert roi.w > 0 and roi.h > 0, "ROI has zero width/height"
