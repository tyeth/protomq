"""Minimal tests to verify HIL infrastructure (collection-time filtering, structured failures)."""
from pathlib import Path

import pytest

BOARD_URL = "https://adafru.it/4868"


@pytest.mark.board(BOARD_URL)
def test_board_skipped_by_config():
    """Should be skipped when board not in runner config."""
    pass


@pytest.mark.requires_feature("ppk2")
def test_feature_skipped():
    """Should be skipped when ppk2 feature not available."""
    pass


def test_always_passes():
    """Sanity check."""
    assert True


@pytest.mark.board(BOARD_URL)
def test_board_needs_camera(video_capture: Path):
    """Uses video_capture fixture — should skip/fail if no camera."""
    assert video_capture.suffix == ".mp4"
