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

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

import pytest

from tools.video_capture import VideoRecorder
from tools.qr_locator import BoundingBox, locate_board_roi
from tools.frame_extractor import extract_distinct_frames, Frame
from tools.display_comparator import generate_report

from hil_exceptions import (
    HILFailure,
    TargetFailure,
    RigFailure,
    InfraFailure,
    unknown_target,
    unsupported_target,
    unavailable_target,
    no_camera,
    frame_not_including_qr,
    unknown_camera_failure,
    unsupported_feature,
)
from runner_config import RunnerConfig

logger = logging.getLogger(__name__)


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
    group.addoption("--runner-config", type=str, default=None,
                    help="Path to runner capability JSON file")

    # Register ini values so pytest doesn't warn about them
    parser.addini("video_device", "OpenCV camera device index", default="0")
    parser.addini("video_fps", "Recording FPS", default="30")
    parser.addini("video_width", "Frame width", default="1280")
    parser.addini("video_height", "Frame height", default="720")
    parser.addini("artifacts_dir", "Root artifacts directory", default="artifacts")
    parser.addini("runner_config", "Path to runner capability JSON file", default="")


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "board(url): associate a test with a specific board identified by its QR-code URL",
    )
    config.addinivalue_line(
        "markers",
        "requires_feature(name): skip test if runner lacks the named feature (e.g. ppk2, camera)",
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
# Runner config (session-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def runner_config(request: pytest.FixtureRequest) -> RunnerConfig:
    """Load runner capability config (boards, features, status)."""
    cfg_path = _opt(request.config, "--runner-config", "RUNNER_CONFIG",
                    "runner_config", "")
    return RunnerConfig.load(cfg_path or None)


# ---------------------------------------------------------------------------
# Collection-time filtering — skip early, before camera starts
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    cfg_path = _opt(config, "--runner-config", "RUNNER_CONFIG",
                    "runner_config", "")
    runner_cfg = RunnerConfig.load(cfg_path or None)

    for item in items:
        # Check @pytest.mark.board(url) against runner capability
        board_marker = item.get_closest_marker("board")
        if board_marker and board_marker.args:
            board_url = board_marker.args[0]
            status = runner_cfg.board_status(board_url)
            if status == "unknown":
                exc = unknown_target(board_url)
                item.add_marker(pytest.mark.skip(reason=str(exc)))
            elif status == "unsupported":
                exc = unsupported_target(board_url, runner_cfg.runner_id)
                item.add_marker(pytest.mark.skip(reason=str(exc)))
            elif status in ("offline", "busy", "retired"):
                reason = "temporarily_offline" if status == "offline" else status
                exc = unavailable_target(board_url, reason)
                item.add_marker(pytest.mark.skip(reason=str(exc)))

        # Check @pytest.mark.requires_feature(name)
        for marker in item.iter_markers("requires_feature"):
            feature_name = marker.args[0]
            if not runner_cfg.has_feature(feature_name):
                exc = unsupported_feature(feature_name, "n/a")
                item.add_marker(pytest.mark.skip(reason=str(exc)))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def video_capture(request: pytest.FixtureRequest, runner_config: RunnerConfig) -> Generator[Path, None, None]:
    """
    Record video for the lifetime of the test.

    Yields the Path to the recorded MP4 file.
    The recording is stopped when the test finishes (pass, fail, or error).
    """
    cfg = request.config

    # Check runner declares camera support
    if not runner_config.has_feature("camera"):
        device = int(_opt(cfg, "--video-device", "VIDEO_DEVICE", "video_device", 0))
        raise no_camera(device)

    device = int(_opt(cfg, "--video-device", "VIDEO_DEVICE", "video_device",
                       runner_config.camera_device()))
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
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
        err_msg = str(exc).lower()
        if "cannot open" in err_msg or "did not open" in err_msg:
            raise no_camera(device) from exc
        raise unknown_camera_failure(device, str(exc)) from exc

    try:
        yield output_path
    finally:
        recorder.stop()


@pytest.fixture
def board_roi(
    request: pytest.FixtureRequest,
    video_capture: Path,
    runner_config: RunnerConfig,
) -> Optional[BoundingBox]:
    """
    Locate a board's ROI by scanning the recorded video for a QR code.

    The QR identifier is taken from the ``@pytest.mark.board(url)`` marker.
    Raises structured HIL exceptions when the board can't be found.
    """
    marker = request.node.get_closest_marker("board")
    if marker is None:
        return None

    qr_url = marker.args[0] if marker.args else None
    if not qr_url:
        return None

    # Runner-level board check (redundant with collection-time filter, but
    # catches dynamic cases where the fixture is used without the marker
    # being filtered)
    status = runner_config.board_status(qr_url)
    if status == "unknown":
        raise unknown_target(qr_url)
    elif status == "unsupported":
        raise unsupported_target(qr_url, runner_config.runner_id)
    elif status in ("offline", "busy", "retired"):
        reason = "temporarily_offline" if status == "offline" else status
        raise unavailable_target(qr_url, reason)

    max_frames = 30
    roi = locate_board_roi(str(video_capture), qr_url, max_frames=max_frames)
    if roi is None:
        raise frame_not_including_qr(qr_url, frames_scanned=max_frames)
    return roi


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


# ---------------------------------------------------------------------------
# Report hook — translate HILFailure to pytest outcomes + JSONL summary
# ---------------------------------------------------------------------------

@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()

    if call.excinfo is None or not call.excinfo.errisinstance(HILFailure):
        return

    exc: HILFailure = call.excinfo.value

    # Accumulate structured data for the session summary
    if not hasattr(item.config, "_hil_failures"):
        item.config._hil_failures = []
    item.config._hil_failures.append({
        "nodeid": item.nodeid,
        "phase": report.when,
        **exc.to_dict(),
    })

    # Map exception category to pytest outcome
    if isinstance(exc, TargetFailure) or (
        isinstance(exc, RigFailure) and exc.code == "no_camera"
    ):
        report.outcome = "skipped"
        report.longrepr = (str(item.fspath), None, str(exc))
    else:
        # Other RigFailure and InfraFailure → real failures
        report.outcome = "failed"
        report.longrepr = str(exc)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write hil_failures.jsonl if any structured failures were recorded."""
    failures = getattr(session.config, "_hil_failures", [])
    if not failures:
        return
    artifacts_dir = Path(
        _opt(session.config, "--artifacts-dir", "ARTIFACTS_DIR",
             "artifacts_dir", "artifacts")
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    summary_path = artifacts_dir / "hil_failures.jsonl"
    with open(summary_path, "w") as f:
        for entry in failures:
            f.write(json.dumps(entry) + "\n")
    logger.info("Wrote %d HIL failure(s) to %s", len(failures), summary_path)
