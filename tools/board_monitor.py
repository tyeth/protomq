"""
board_monitor.py — Per-board ROI monitoring for the WipperSnapper test bench.

Usage:
    # Monitor all boards via USB camera, save crops every 2s
    monitor = BoardMonitor(camera_index=0)
    monitor.start()

    # Get a single board's current crop
    crop = monitor.get_crop("https://adafru.it/4868")

    # Or use standalone:
    python -m tools.board_monitor --camera 0 --output /tmp/board_crops/

    # Or from a video file:
    python -m tools.board_monitor --video test_run.mp4

Board crops are saved to:
    <output_dir>/<qr_id>_latest.jpg    — most recent frame
    <output_dir>/<qr_id>_<ts>.jpg      — timestamped snapshot (if --archive)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from tools.calibration_data import (
    QR_CENTRES,
    compute_scale,
    transform_roi,
)
from tools.qr_locator import locate_all_boards, scan_qr_codes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference ROIs (board bounding boxes in reference image coords)
# These were established from the annotated reference image.
# Format: {url: (x, y, w, h)}  — x,y = top-left, w,h = size
# ---------------------------------------------------------------------------
REFERENCE_ROIS: Dict[str, Tuple[int, int, int, int]] = {
    "https://adafru.it/398":  ( 730,  300, 260, 230),
    "https://adafru.it/1028": (1820, 1590, 340, 240),
    "https://adafru.it/2900": ( 820, 1410, 280, 230),
    "https://adafru.it/3129": (1230,  950, 280, 240),
    "https://adafru.it/4116": ( 230,  930, 280, 250),
    "https://adafru.it/4313": (1700,  340, 300, 240),
    "https://adafru.it/4440": (1230, 1700, 340, 240),
    "https://adafru.it/4650": ( 820,  870, 280, 230),
    "https://adafru.it/4777": (1740,  880, 290, 240),
    "https://adafru.it/4868": ( 170, 1630, 340, 240),
    "https://adafru.it/5300": (1240,  230, 310, 230),
    "https://adafru.it/5483": (1230,  590, 280, 230),
    "https://adafru.it/5691": ( 770, 1760, 300, 230),
}


class BoardMonitor:
    """
    Continuously captures frames from a camera or video, detects QR codes
    to calibrate scale/position, and maintains per-board cropped snapshots.

    Thread-safe: get_crop() can be called from any thread.
    """

    def __init__(
        self,
        camera_index: int = 0,
        video_path: Optional[str] = None,
        output_dir: str = "/tmp/board_crops",
        capture_interval: float = 1.0,
        scale_update_interval: float = 10.0,
        archive: bool = False,
    ):
        self.camera_index = camera_index
        self.video_path = video_path
        self.output_dir = Path(output_dir)
        self.capture_interval = capture_interval
        self.scale_update_interval = scale_update_interval
        self.archive = archive

        self.output_dir.mkdir(parents=True, exist_ok=True)

        # State
        self._lock = threading.RLock()
        self._crops: Dict[str, np.ndarray] = {}        # url → latest crop
        self._scale: float = 1.0
        self._offset: Tuple[float, float] = (0.0, 0.0)
        self._detected_qrs: Dict[str, Tuple[int, int]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

        # Computed ROIs in current image space
        self._current_rois: Dict[str, Tuple[int, int, int, int]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("BoardMonitor started (interval=%.1fs)", self.capture_interval)

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()
        logger.info("BoardMonitor stopped")

    def get_crop(self, url: str) -> Optional[np.ndarray]:
        """
        Get the latest crop for a board by its QR URL.
        Returns None if the board hasn't been seen yet.
        """
        with self._lock:
            return self._crops.get(url)

    def get_crop_by_id(self, qr_id: str) -> Optional[np.ndarray]:
        """Get crop by short ID (e.g. '4868' instead of full URL)."""
        url = f"https://adafru.it/{qr_id}"
        return self.get_crop(url)

    def available_boards(self) -> list:
        """Return list of URLs for boards currently being monitored."""
        with self._lock:
            return list(self._crops.keys())

    def get_roi(self, url: str) -> Optional[Tuple[int, int, int, int]]:
        """Return the current (scaled) ROI for a board."""
        with self._lock:
            return self._current_rois.get(url)

    def save_snapshots(self, suffix: str = "") -> Dict[str, str]:
        """Save current crops to output_dir. Returns {url: path}."""
        saved = {}
        with self._lock:
            crops_copy = dict(self._crops)
        for url, crop in crops_copy.items():
            qid = url.split("/")[-1]
            fname = f"{qid}{suffix}.jpg"
            path = self.output_dir / fname
            cv2.imwrite(str(path), crop)
            saved[url] = str(path)
        return saved

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_capture(self) -> cv2.VideoCapture:
        if self.video_path:
            cap = cv2.VideoCapture(self.video_path)
        else:
            cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {'video: ' + self.video_path if self.video_path else f'camera {self.camera_index}'}")
        return cap

    def _update_scale(self, frame: np.ndarray) -> None:
        """Re-detect QR codes and update scale/offset."""
        # Scan at 2x for better detection
        h, w = frame.shape[:2]
        large = cv2.resize(frame, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        codes = scan_qr_codes(large)

        # Map back to original coords
        detected = {}
        for url, bbox in codes.items():
            cx = (bbox.x + bbox.w // 2) // 2
            cy = (bbox.y + bbox.h // 2) // 2
            detected[url] = (cx, cy)

        if not detected:
            logger.debug("No QR codes found — using previous scale")
            return

        with self._lock:
            self._detected_qrs = detected
            self._scale = compute_scale(detected, "diagonal")
            if self._scale == 1.0:
                self._scale = compute_scale(detected, "horizontal")

            # Compute ROIs for all known boards
            self._current_rois.clear()
            for url, ref_roi in REFERENCE_ROIS.items():
                roi = transform_roi(ref_roi, detected)
                self._current_rois[url] = roi

        logger.debug("Scale updated: %.3f, %d QRs detected, %d ROIs computed",
                     self._scale, len(detected), len(self._current_rois))

    def _crop_boards(self, frame: np.ndarray) -> None:
        """Crop each board from the frame using current ROIs."""
        fh, fw = frame.shape[:2]
        ts = time.strftime("%Y%m%dT%H%M%S")

        with self._lock:
            rois = dict(self._current_rois)

        for url, (x, y, w, h) in rois.items():
            # Clamp to frame
            x1 = max(0, x); y1 = max(0, y)
            x2 = min(fw, x + w); y2 = min(fh, y + h)
            if x2 <= x1 or y2 <= y1:
                continue

            crop = frame[y1:y2, x1:x2].copy()
            if crop.size == 0:
                continue

            qid = url.split("/")[-1]

            with self._lock:
                self._crops[url] = crop

            # Save latest
            cv2.imwrite(str(self.output_dir / f"{qid}_latest.jpg"), crop)

            # Archive if requested
            if self.archive:
                cv2.imwrite(str(self.output_dir / f"{qid}_{ts}.jpg"), crop)

    def _loop(self) -> None:
        """Main monitoring loop."""
        self._cap = self._open_capture()
        last_scale_update = 0.0
        last_capture = 0.0

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                if self.video_path:
                    # Loop video
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                logger.warning("Failed to read frame")
                time.sleep(0.1)
                continue

            now = time.monotonic()

            # Periodically re-detect QR codes to update scale
            if now - last_scale_update >= self.scale_update_interval:
                self._update_scale(frame)
                last_scale_update = now

            # Crop boards at the capture interval
            if now - last_capture >= self.capture_interval:
                if self._current_rois:
                    self._crop_boards(frame)
                last_capture = now

            time.sleep(0.02)

        self._cap.release()
        self._cap = None


# ---------------------------------------------------------------------------
# Convenience: get ROI for any board in a single image
# ---------------------------------------------------------------------------

def get_board_roi(
    url: str,
    image: np.ndarray,
    use_segmentation: bool = True,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Get the bounding box ROI for a specific board in an image.

    Strategy:
    1. Try to detect the QR code directly in the image (segmentation)
    2. If found, use GrabCut segmentation for tight ROI
    3. If QR not found, use calibration + scale transform from any detected QRs
    4. Last resort: return reference ROI scaled by image size ratio

    Parameters
    ----------
    url : str
        Board QR URL e.g. "https://adafru.it/4868"
    image : np.ndarray
        BGR image
    use_segmentation : bool
        If True, use GrabCut segmentation when QR is directly detected

    Returns
    -------
    (x, y, w, h) or None
    """
    h, w = image.shape[:2]

    # 1. Scan for QR codes in this image
    large = cv2.resize(image, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    all_qrs = scan_qr_codes(large)

    # Map to original coords
    detected = {}
    for u, bbox in all_qrs.items():
        cx = (bbox.x + bbox.w // 2) // 2
        cy = (bbox.y + bbox.h // 2) // 2
        detected[u] = (cx, cy)

    # 2. If target board's QR is directly visible, segment it
    if url in all_qrs and use_segmentation:
        from tools.qr_locator import segment_board_roi, BoundingBox
        qb = all_qrs[url]
        # Map to original coords
        orig_bbox = BoundingBox(
            x=qb.x // 2, y=qb.y // 2,
            w=qb.w // 2, h=qb.h // 2
        )
        roi = segment_board_roi(image, orig_bbox)
        logger.info("Direct QR segmentation for %s: %s", url.split("/")[-1], roi)
        return (roi.x, roi.y, roi.w, roi.h)

    # 3. Use calibration transform from any detected QRs
    if url in REFERENCE_ROIS and detected:
        ref_roi = REFERENCE_ROIS[url]
        transformed = transform_roi(ref_roi, detected)
        logger.info("Calibration transform for %s: %s", url.split("/")[-1], transformed)
        return transformed

    # 4. Pure scale fallback (assume same aspect ratio, no position data)
    if url in REFERENCE_ROIS:
        ref_w, ref_h = 2560, 2092
        sx = w / ref_w; sy = h / ref_h
        rx, ry, rw, rh = REFERENCE_ROIS[url]
        logger.warning("Pure scale fallback for %s", url.split("/")[-1])
        return (int(rx*sx), int(ry*sy), int(rw*sx), int(rh*sy))

    logger.error("Unknown board URL: %s", url)
    return None


def list_available_boards() -> list:
    """Return list of all known board URLs."""
    return list(REFERENCE_ROIS.keys())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, signal, sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    p = argparse.ArgumentParser(description="Monitor WipperSnapper test bench boards")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--video", type=str, default=None)
    p.add_argument("--output", type=str, default="/tmp/board_crops")
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--archive", action="store_true")
    p.add_argument("--board", type=str, default=None,
                   help="Monitor only this board (short ID e.g. 4868)")
    p.add_argument("--show", action="store_true",
                   help="Display crops in a window")
    args = p.parse_args()

    monitor = BoardMonitor(
        camera_index=args.camera,
        video_path=args.video,
        output_dir=args.output,
        capture_interval=args.interval,
        archive=args.archive,
    )

    def _shutdown(sig, frame):
        print("\nShutting down...")
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    monitor.start()

    print(f"Monitoring {len(REFERENCE_ROIS)} boards → {args.output}")
    print("Crops saved as <board_id>_latest.jpg")
    print("Ctrl-C to stop")

    try:
        while True:
            if args.show:
                boards = monitor.available_boards()
                if boards:
                    # Show a 2x3 grid of crops
                    crops = [monitor.get_crop(u) for u in boards[:6]]
                    crops = [cv2.resize(c, (320, 240)) if c is not None
                             else np.zeros((240,320,3),np.uint8)
                             for c in crops]
                    while len(crops) < 6:
                        crops.append(np.zeros((240,320,3),np.uint8))
                    row1 = np.hstack(crops[:3])
                    row2 = np.hstack(crops[3:6])
                    grid = np.vstack([row1, row2])
                    cv2.imshow("Board Monitor", grid)
                    if cv2.waitKey(100) & 0xFF == ord('q'):
                        break
                else:
                    time.sleep(0.5)
            else:
                time.sleep(2)
                avail = monitor.available_boards()
                print(f"  Active boards: {len(avail)}/{len(REFERENCE_ROIS)}", end="\r")
    finally:
        monitor.stop()
        cv2.destroyAllWindows()
