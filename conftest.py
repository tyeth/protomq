"""
conftest.py
===========
Pytest configuration and fixtures for the video-QR display testing pipeline.

Provides:
- ``video_capture`` — records video for the duration of a test
- ``board_roi`` — locates a board by its QR-code URL
- ``distinct_frames`` — extracts visually-distinct frames from a recording
- ``@pytest.mark.board(url)`` — marker that auto-wires video + frame extraction

The ``board`` marker is the recommended high-level API::

    @pytest.mark.board("https://www.adafruit.com/product/4413")
    def test_display_updates(distinct_frames):
        assert len(distinct_frames) >= 3
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

import pytest

from tools.video_capture import VideoRecorder
from tools.qr_locator import BoundingBox, locate_board_roi
from tools.frame_extractor import extract_distinct_frames, Frame
from tools.display_comparator import generate_report


# ---------------------------------------------------------------------------
# CLI options (merged with those from video_capture plugin)
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("video_capture", "Video capture options")
    group.addoption("--video-device", type=int, default=None,
                    help="OpenCV camera device index (default 0)")
    group.addoption("--video-fps", type=float, default=None,
                    help="Recording FPS (default 30)")
    group.addoption("--video-width", type=int, default=None,
                    help="Frame width (default 1280)")
    group.addoption("--video-height", type=int, default=None,
                    help="Frame height (default 720)")
    group.addoption("--artifacts-dir", type=str, default=None,
                    help="Root artifacts directory (default: artifacts/)")


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "board(url): associate a test with a specific board identified by its QR-code URL",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _opt(config, cli_name: str, env_name: str, ini_name: str, default):
    """Resolve option from CLI → env var → ini → default."""
    val = config.getoption(cli_name, default=None)
    if val is not None:
        return val
    env_val = os.environ.get(env_name)
    if env_val is not None:
        return type(default)(env_val)
    ini_val = config.getini(ini_name)
    if ini_val:
        return type(default)(ini_val)
    return default


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def video_capture(request: pytest.FixtureRequest) -> Generator[Path, None, None]:
    """
    Record video for the lifetime of the test.

    Yields the Path to the recorded MP4 file.
    The recording is stopped when the test finishes (pass, fail, or error).
    """
    cfg = request.config

    device = int(_opt(cfg, "--video-device", "VIDEO_DEVICE", "video_device", 0))
    fps = float(_opt(cfg, "--video-fps", "VIDEO_FPS", "video_fps", 30.0))
    width = int(_opt(cfg, "--video-width", "VIDEO_WIDTH", "video_width", 1280))
    height = int(_opt(cfg, "--video-height", "VIDEO_HEIGHT", "video_height", 720))
    artifacts_dir = Path(
        _opt(cfg, "--artifacts-dir", "ARTIFACTS_DIR", "artifacts_dir", "artifacts")
    )

    videos_dir = artifacts_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    # Sanitise test name for filesystem use
    test_name = request.node.nodeid.replace("/", "_").replace("::", "__").replace(" ", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = videos_dir / f"{test_name}_{timestamp}.mp4"

    recorder = VideoRecorder(
        output_path=output_path,
        device=device,
        fps=fps,
        width=width,
        height=height,
    )

    try:
        recorder.start()
    except Exception as exc:
        pytest.skip(f"video_capture: could not start recording — {exc}")

    try:
        yield output_path
    finally:
        recorder.stop()


@pytest.fixture
def board_roi(request: pytest.FixtureRequest, video_capture: Path) -> Optional[BoundingBox]:
    """
    Locate a board's ROI by scanning the recorded video for a QR code.

    The QR identifier is taken from the ``@pytest.mark.board(url)`` marker.
    """
    marker = request.node.get_closest_marker("board")
    if marker is None:
        return None

    qr_url = marker.args[0] if marker.args else None
    if not qr_url:
        return None

    return locate_board_roi(str(video_capture), qr_url)


@pytest.fixture
def distinct_frames(
    request: pytest.FixtureRequest,
    video_capture: Path,
    board_roi: Optional[BoundingBox],
) -> list[Frame]:
    """
    Extract visually-distinct frames from the recorded video.

    If a ``board`` marker is present, the ROI is automatically applied.
    An HTML report is generated after extraction.
    """
    frames = extract_distinct_frames(
        video_path=str(video_capture),
        roi=board_roi,
    )

    # Generate HTML report as a side-effect
    test_name = request.node.nodeid
    try:
        generate_report(frames, test_name)
    except Exception:
        pass  # Don't fail the test if report generation fails

    return frames
