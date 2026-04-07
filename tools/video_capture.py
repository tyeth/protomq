"""
tools/video_capture.py
======================
VideoRecorder class — wraps OpenCV VideoCapture + VideoWriter in a background
thread for recording a camera feed during tests.

The pytest fixture and CLI options are defined in conftest.py.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import cv2


class VideoRecorder:
    """Wraps OpenCV VideoCapture + VideoWriter in a background thread."""

    def __init__(
        self,
        output_path: Path,
        device: int = 0,
        fps: float = 30.0,
        width: int = 1280,
        height: int = 720,
    ) -> None:
        self.output_path = output_path
        self.device = device
        self.fps = fps
        self.width = width
        self.height = height

        self._cap: Optional[cv2.VideoCapture] = None
        self._writer: Optional[cv2.VideoWriter] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = threading.Event()
        self._error: Optional[Exception] = None

    def start(self) -> None:
        """Begin recording in a background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        # Wait until the capture device is actually open (or failed)
        if not self._started.wait(timeout=10):
            raise RuntimeError(
                f"Camera device {self.device} did not open within 10 seconds"
            )
        if self._error:
            raise self._error

    def stop(self) -> Path:
        """Stop recording and return the output path."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15)
        return self.output_path

    def _record_loop(self) -> None:
        try:
            self._cap = cv2.VideoCapture(self.device)
            if not self._cap.isOpened():
                raise RuntimeError(f"Cannot open camera device {self.device}")

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.fps)

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                str(self.output_path),
                fourcc,
                self.fps,
                (self.width, self.height),
            )
            if not self._writer.isOpened():
                raise RuntimeError(
                    f"Cannot open VideoWriter for {self.output_path}"
                )

            self._started.set()

            while not self._stop_event.is_set():
                ret, frame = self._cap.read()
                if not ret:
                    time.sleep(0.01)
                    continue
                # Resize if the camera returned a different resolution
                h, w = frame.shape[:2]
                if w != self.width or h != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                self._writer.write(frame)

        except Exception as exc:
            self._error = exc
            self._started.set()  # unblock .start()
        finally:
            if self._cap:
                self._cap.release()
            if self._writer:
                self._writer.release()
