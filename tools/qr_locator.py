"""
tools/qr_locator.py
====================
QR-code detection and board ROI location via GrabCut segmentation.

Workflow:
  1. pyzbar finds all QR codes in the image/frame
  2. For each QR, GrabCut (seeded from the QR position) segments the board
  3. The tightest bounding rectangle around the foreground mask is the board ROI
  4. Fallback: Otsu thresholding if GrabCut finds no contour at the QR point
  5. Second fallback: 4× QR-size padding if all else fails
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


# ---------------------------------------------------------------------------
# QR scanning
# ---------------------------------------------------------------------------

def scan_qr_codes(image: np.ndarray) -> Dict[str, BoundingBox]:
    """Find all QR codes in a single BGR frame. Returns {qr_data: BoundingBox}."""
    if image is None:
        return {}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    decoded = pyzbar.decode(gray, symbols=[pyzbar.ZBarSymbol.QRCODE])
    results: Dict[str, BoundingBox] = {}
    for obj in decoded:
        data = obj.data.decode("utf-8", errors="replace")
        r = obj.rect
        results[data] = BoundingBox(x=r.left, y=r.top, w=r.width, h=r.height)
    return results


# ---------------------------------------------------------------------------
# Board segmentation
# ---------------------------------------------------------------------------

def _grabcut_board_roi(
    image: np.ndarray,
    qcx: int, qcy: int,
    qw: int, qh: int,
    seed_factor: float = 8.0,
    iterations: int = 3,
) -> Optional[BoundingBox]:
    """
    Use GrabCut seeded from the QR centre to segment the board.
    Returns BoundingBox of the tightest rect containing the board foreground,
    or None if no suitable contour is found at the QR location.
    """
    h, w = image.shape[:2]
    seed = max(qw, qh)
    seed_w = max(150, int(seed * seed_factor))
    seed_h = max(150, int(seed * seed_factor))
    rx = max(1, qcx - seed_w // 2)
    ry = max(1, qcy - seed_h // 2)
    rw = min(w - rx - 2, seed_w)
    rh = min(h - ry - 2, seed_h)

    mask = np.zeros(image.shape[:2], np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(image, mask, (rx, ry, rw, rh), bgd, fgd,
                    iterations, cv2.GC_INIT_WITH_RECT)
    except cv2.error as exc:
        logger.debug("GrabCut cv2 error: %s", exc)
        return None

    fg_mask = np.where((mask == 2) | (mask == 0), 0, 1).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel, iterations=4)
    fg_mask = cv2.dilate(fg_mask, kernel, iterations=2)

    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best_cnt = None
    best_area = 0
    for cnt in contours:
        if cv2.pointPolygonTest(cnt, (float(qcx), float(qcy)), False) >= 0:
            area = cv2.contourArea(cnt)
            if area > best_area:
                best_area = area
                best_cnt = cnt

    if best_cnt is None:
        return None

    bx, by, bw, bh = cv2.boundingRect(best_cnt)
    # Sanity: must be at least 2× the QR size
    if bw < qw * 2 or bh < qh * 2:
        return None

    return BoundingBox(x=bx, y=by, w=bw, h=bh)


def _otsu_board_roi(
    image: np.ndarray,
    qcx: int, qcy: int,
    qw: int, qh: int,
    pad_factor: float = 5.0,
) -> Optional[BoundingBox]:
    """
    Otsu threshold on a local crop around the QR, find the largest contour
    that contains the QR centre. Fallback when GrabCut fails.
    """
    h, w = image.shape[:2]
    pad = max(qw, qh) * int(pad_factor)
    cx1 = max(0, qcx - pad); cy1 = max(0, qcy - pad)
    cx2 = min(w, qcx + pad); cy2 = min(h, qcy + pad)
    crop = image[cy1:cy2, cx1:cx2]

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=4)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    lqx, lqy = qcx - cx1, qcy - cy1
    best = None
    for cnt in contours:
        if cv2.pointPolygonTest(cnt, (float(lqx), float(lqy)), False) >= 0:
            if best is None or cv2.contourArea(cnt) > cv2.contourArea(best):
                best = cnt

    if best is None:
        return None

    bx, by, bw, bh = cv2.boundingRect(best)
    return BoundingBox(x=bx + cx1, y=by + cy1, w=bw, h=bh)


def segment_board_roi(
    image: np.ndarray,
    qr_bbox: BoundingBox,
) -> BoundingBox:
    """
    Given an image and the QR code bounding box, segment the board region.

    Tries in order:
      1. GrabCut seeded from QR position
      2. Otsu threshold on local crop
      3. 4× QR-size padding fallback

    Returns BoundingBox of the board ROI.
    """
    h, w = image.shape[:2]
    qcx = qr_bbox.x + qr_bbox.w // 2
    qcy = qr_bbox.y + qr_bbox.h // 2
    qw, qh = qr_bbox.w, qr_bbox.h

    # 1. GrabCut
    roi = _grabcut_board_roi(image, qcx, qcy, qw, qh)
    if roi:
        logger.debug("GrabCut ROI: %s", roi)
        return roi

    # 2. Otsu
    roi = _otsu_board_roi(image, qcx, qcy, qw, qh)
    if roi:
        logger.debug("Otsu ROI: %s", roi)
        return roi

    # 3. Pure padding fallback
    pad = max(qw, qh) * 4
    bx = max(0, qcx - pad)
    by = max(0, qcy - pad)
    bw = min(w - bx, pad * 2)
    bh = min(h - by, pad * 2)
    logger.debug("Fallback padding ROI")
    return BoundingBox(x=bx, y=by, w=bw, h=bh)


# ---------------------------------------------------------------------------
# Scan all boards in a single image/frame
# ---------------------------------------------------------------------------

def locate_all_boards(image: np.ndarray) -> Dict[str, BoundingBox]:
    """
    Find all QR codes in `image` and segment the board ROI for each.

    Returns dict: {qr_data: BoundingBox}
    """
    qrs = scan_qr_codes(image)
    if not qrs:
        logger.warning("No QR codes found in image")
        return {}

    boards: Dict[str, BoundingBox] = {}
    for qr_data, qr_bbox in qrs.items():
        roi = segment_board_roi(image, qr_bbox)
        boards[qr_data] = roi
        logger.info("Board %s → ROI %s", qr_data, roi)

    return boards


def locate_board_roi(
    video_path: str,
    qr_identifier: str,
    max_frames: int = 30,
) -> Optional[BoundingBox]:
    """
    Search the first `max_frames` frames of `video_path` for a specific
    QR identifier, then segment and return that board's ROI.

    Parameters
    ----------
    video_path : str
        Path to the video file.
    qr_identifier : str
        The QR code data string to look for (e.g. "https://adafru.it/5300").
    max_frames : int
        Maximum frames to scan before giving up.

    Returns
    -------
    BoundingBox or None
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return None

    try:
        for _ in range(max_frames):
            ret, frame = cap.read()
            if not ret:
                break
            qrs = scan_qr_codes(frame)
            if qr_identifier in qrs:
                roi = segment_board_roi(frame, qrs[qr_identifier])
                logger.info("Found %s in video at ROI %s", qr_identifier, roi)
                return roi
    finally:
        cap.release()

    logger.warning("QR %s not found in first %d frames", qr_identifier, max_frames)
    return None
