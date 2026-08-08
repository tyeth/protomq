"""
hil_exceptions.py
=================
Structured failure taxonomy for hardware-in-the-loop testing.

Three categories:
  A. TargetFailure  — the runner cannot serve a specific board/target
  B. RigFailure     — physical test equipment problem
  C. InfraFailure   — infrastructure / environment issue

Each exception carries machine-parseable fields (category, code, message,
runner_id, details) so pytest hooks can translate them into the right
outcome (skip vs fail) and write structured JSONL summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class HILFailure(Exception):
    """Base for all structured HIL failures."""

    category: str
    code: str
    message: str
    runner_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.category}/{self.code}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "runner_id": self.runner_id,
            "details": self.details,
        }


# ── A. Target / runner failures ──────────────────────────────────────────────


class TargetFailure(HILFailure):
    """Board/target cannot be tested on this runner."""

    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(category="target", code=code, message=message, **kwargs)


def unknown_target(board_url: str) -> TargetFailure:
    return TargetFailure(
        "unknown_target",
        f"Board URL not recognized: {board_url}",
        details={"board_url": board_url},
    )


def unsupported_target(board_url: str, runner_id: str) -> TargetFailure:
    return TargetFailure(
        "unsupported_target",
        f"Runner '{runner_id}' does not support board: {board_url}",
        runner_id=runner_id,
        details={"board_url": board_url},
    )


def unavailable_target(board_url: str, reason: str) -> TargetFailure:
    """reason: 'temporarily_offline' | 'busy' | 'retired'"""
    return TargetFailure(
        f"unavailable_target_{reason}",
        f"Board {board_url} unavailable: {reason}",
        details={"board_url": board_url, "reason": reason},
    )


# ── B. Rig hardware failures ────────────────────────────────────────────────


class RigFailure(HILFailure):
    """Physical test equipment problem."""

    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(category="rig", code=code, message=message, **kwargs)


def no_camera(device: int) -> RigFailure:
    return RigFailure(
        "no_camera",
        f"No camera available at device index {device}",
        details={"device": device},
    )


def camera_setup(device: int, detail: str) -> RigFailure:
    return RigFailure(
        "camera_setup",
        f"Camera {device} opened but setup failed: {detail}",
        details={"device": device, "detail": detail},
    )


def frame_not_including_qr(board_url: str, frames_scanned: int) -> RigFailure:
    return RigFailure(
        "frame_not_including_qr",
        f"QR for {board_url} not found in {frames_scanned} frames",
        details={"board_url": board_url, "frames_scanned": frames_scanned},
    )


def unknown_camera_failure(device: int, detail: str) -> RigFailure:
    return RigFailure(
        "unknown_camera_capture_failure",
        f"Camera {device} capture problem: {detail}",
        details={"device": device, "detail": detail},
    )


def unsupported_feature(feature: str, board_url: str) -> RigFailure:
    return RigFailure(
        "unsupported_feature_requested",
        f"Feature '{feature}' not available for board {board_url}",
        details={"feature": feature, "board_url": board_url},
    )


# ── C. Infrastructure failures ──────────────────────────────────────────────


class InfraFailure(HILFailure):
    """Infrastructure problem unrelated to the device under test."""

    def __init__(self, code: str, message: str, **kwargs: Any) -> None:
        super().__init__(category="infra", code=code, message=message, **kwargs)


def network_error(detail: str) -> InfraFailure:
    return InfraFailure("network", f"Network problem: {detail}")


def artifact_storage_error(detail: str) -> InfraFailure:
    return InfraFailure("artifact_storage", f"Artifact storage problem: {detail}")


def dependency_error(detail: str) -> InfraFailure:
    return InfraFailure("dependency", f"Dependency problem: {detail}")
