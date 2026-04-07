"""
tools/qr_locator.py
====================
QR-code detection and board ROI location.

Uses pyzbar to find QR codes in frames, and estimates each board's region
of interest (ROI) as a padded area around the detected QR code.
"""

from __future__ import annotations

import logging
from collections import namedtuple
from typing import Dict, Optional

import cv2
import numpy as np
from pyzbar import pyzbar

logger = logging.getLogger(__name__)

BoundingBox = namedtuple("BoundingBox", ["x", "y", "w", "h"])


def scan_qr_codes(image: np.ndarray) -> Dict[str, BoundingBox]:
    """
    Find all QR codes in a single frame.

    Parameters
    ----------
    image : np.ndarray
        BGR or grayscale image (OpenCV format).

    Returns
    -------
    dict[str, BoundingBox]
        Mapping of decoded QR data (str) → bounding box.
    """
    if image is None:
        return {}

    # pyzbar works on grayscale or RGB; convert from BGR
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    decoded = pyzbar.decode(gray, symbols=[pyzbar.ZBarSymbol.QRCODE])
    results: Dict[str, BoundingBox] = {}
    for obj in decoded:
        data = obj.data.decode("utf-8", errors="replace")
        rect = obj.rect
        results[data] = BoundingBox(x=rect.left, y=rect.top, w=rect.width, h=rect.height)

    return results


def _expand_roi(
    qr_bbox: BoundingBox,
    frame_width: int,
    frame_height: int,
    scale: float = 3.0,
) -> BoundingBox:
    """
    Expand a QR bounding box to estimate the full board ROI.

    Uses *scale* × the QR size, centred on the QR code, clamped to frame bounds.
    """
    qr_cx = qr_bbox.x + qr_bbox.w / 2
    qr_cy = qr_bbox.y + qr_bbox.h / 2

    roi_w = qr_bbox.w * scale
    roi_h = qr_bbox.h * scale

    x = int(max(0, qr_cx - roi_w / 2))
    y = int(max(0, qr_cy - roi_h / 2))
    w = int(min(frame_width - x, roi_w))
    h = int(min(frame_height - y, roi_h))

    return BoundingBox(x=x, y=y, w=w, h=h)


def locate_board_roi(
    video_path: str,
    qr_identifier: str,
    max_frames: int = 30,
    scale: float = 3.0,
) -> Optional[BoundingBox]:
    """
    Search the first *max_frames* frames of a video for a QR code matching
    *qr_identifier* and return a padded ROI around it.

    Parameters
    ----------
    video_path : str
        Path to the video file.
    qr_identifier : str
        The decoded QR data to search for (e.g. a URL).
    max_frames : int
        Maximum number of frames to scan.
    scale : float
        How many times the QR size to use as the board region (default 3×).

    Returns
    -------
    BoundingBox or None
        The estimated board ROI, or None if the QR was not found.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return None

    try:
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        for i in range(max_frames):
            ret, frame = cap.read()
            if not ret:
                break
            codes = scan_qr_codes(frame)
            if qr_identifier in codes:
                qr_bbox = codes[qr_identifier]
                roi = _expand_roi(qr_bbox, frame_w, frame_h, scale=scale)
                logger.info(
                    "Found QR '%s' at frame %d → ROI %s", qr_identifier, i, roi
                )
                return roi

        logger.warning(
            "QR '%s' not found in first %d frames of %s",
            qr_identifier, max_frames, video_path,
        )
        return None
    finally:
        cap.release()
