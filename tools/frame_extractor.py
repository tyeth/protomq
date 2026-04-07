"""
tools/frame_extractor.py
========================
Extract visually distinct frames from a video, optionally cropped to an ROI.

A frame is "distinct" when the percentage of changed pixels (grayscale absdiff)
exceeds a threshold compared to the previous distinct frame.  Change is
classified as:

- **display** — large contiguous region changed (screen update)
- **led** — small isolated bright blob(s) changed (LED on/off)
- **initial** — the very first frame
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from tools.qr_locator import BoundingBox

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    """A single distinct frame extracted from a video."""

    timestamp_s: float
    frame_number: int
    image: np.ndarray = field(repr=False)
    change_type: str = "initial"  # "initial" | "display" | "led"
    path: Optional[str] = None  # filled in after saving


def _crop(frame: np.ndarray, roi: BoundingBox) -> np.ndarray:
    return frame[roi.y : roi.y + roi.h, roi.x : roi.x + roi.w]


def _classify_change(
    diff_mask: np.ndarray,
    frame_bgr: np.ndarray,
    roi_area: int,
    led_area_max_ratio: float = 0.02,
    brightness_thresh: int = 200,
) -> str:
    """
    Decide whether a change is a display update or an LED toggle.

    Heuristic:
    - Find contours of changed pixels.
    - If the total changed area is small AND contains bright pixels → "led"
    - Otherwise → "display"
    """
    contours, _ = cv2.findContours(diff_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return "display"

    total_changed_area = sum(cv2.contourArea(c) for c in contours)
    changed_ratio = total_changed_area / max(roi_area, 1)

    # Check brightness of changed region
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if len(frame_bgr.shape) == 3 else frame_bgr
    bright_in_mask = cv2.bitwise_and(gray, gray, mask=diff_mask)
    bright_pixels = np.count_nonzero(bright_in_mask > brightness_thresh)
    bright_ratio = bright_pixels / max(np.count_nonzero(diff_mask), 1)

    if changed_ratio < led_area_max_ratio and bright_ratio > 0.3:
        return "led"

    return "display"


def extract_distinct_frames(
    video_path: str,
    roi: Optional[BoundingBox] = None,
    threshold: float = 0.03,
    output_dir: Optional[str] = None,
) -> List[Frame]:
    """
    Walk through a video and extract frames where visible content changed.

    Parameters
    ----------
    video_path : str
        Path to the input video.
    roi : BoundingBox, optional
        If provided, only analyse this region of each frame.
    threshold : float
        Fraction of pixels that must differ to count as a change (0–1).
    output_dir : str, optional
        If given, save each distinct frame as a JPEG here.
        Defaults to ``artifacts/frames/{video_stem}/``.

    Returns
    -------
    list[Frame]
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stem = Path(video_path).stem

    if output_dir is None:
        save_dir = Path("artifacts") / "frames" / stem
    else:
        save_dir = Path(output_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    frames: List[Frame] = []
    prev_gray: Optional[np.ndarray] = None
    frame_idx = 0

    try:
        while True:
            ret, raw_frame = cap.read()
            if not ret:
                break

            region = _crop(raw_frame, roi) if roi else raw_frame
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            timestamp = frame_idx / fps

            if prev_gray is None:
                # First frame is always distinct
                f = Frame(
                    timestamp_s=round(timestamp, 3),
                    frame_number=frame_idx,
                    image=region.copy(),
                    change_type="initial",
                )
                frames.append(f)
                prev_gray = gray
                frame_idx += 1
                continue

            # Compute difference
            diff = cv2.absdiff(gray, prev_gray)
            _, diff_mask = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            changed_pixels = np.count_nonzero(diff_mask)
            total_pixels = diff_mask.size
            change_ratio = changed_pixels / total_pixels

            if change_ratio > threshold:
                roi_area = total_pixels
                change_type = _classify_change(diff_mask, region, roi_area)
                f = Frame(
                    timestamp_s=round(timestamp, 3),
                    frame_number=frame_idx,
                    image=region.copy(),
                    change_type=change_type,
                )
                frames.append(f)
                prev_gray = gray

            frame_idx += 1
    finally:
        cap.release()

    # Save frames
    for i, f in enumerate(frames):
        filename = f"frame_{i:04d}_{f.change_type}.jpg"
        fpath = save_dir / filename
        cv2.imwrite(str(fpath), f.image)
        f.path = str(fpath)

    logger.info(
        "Extracted %d distinct frames from %s (threshold=%.3f)",
        len(frames), video_path, threshold,
    )
    return frames
