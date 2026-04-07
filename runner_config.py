"""
runner_config.py
================
Declares the capabilities of a self-hosted test runner (which boards are
connected, what hardware features are available).

Configuration is loaded from a JSON file.  Search order:
  1. Explicit path (``--runner-config`` CLI / ``RUNNER_CONFIG`` env)
  2. ``runner.json`` in the repo root
  3. Permissive defaults (all boards assumed online, all features enabled)

The permissive default preserves backward compatibility: running locally
without a config file behaves exactly as before.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Boards recognised by the test bench (from calibration_data / board_monitor).
# Used to distinguish "unsupported" (not in runner config) from "unknown"
# (not in this list at all).
KNOWN_BOARD_URLS = {
    "https://adafru.it/398",
    "https://adafru.it/1028",
    "https://adafru.it/2900",
    "https://adafru.it/3129",
    "https://adafru.it/4116",
    "https://adafru.it/4313",
    "https://adafru.it/4440",
    "https://adafru.it/4650",
    "https://adafru.it/4777",
    "https://adafru.it/4868",
    "https://adafru.it/5300",
    "https://adafru.it/5483",
    "https://adafru.it/5691",
}


@dataclass
class RunnerConfig:
    runner_id: str = "local"
    boards: Dict[str, str] = field(default_factory=dict)  # {url: status}
    features: Dict[str, Any] = field(default_factory=dict)
    _permissive: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # Loader
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Optional[str] = None) -> RunnerConfig:
        """Load config from JSON, falling back to permissive defaults."""
        # 1. Explicit path
        if path and Path(path).is_file():
            return cls._from_file(path)

        # 2. Environment variable
        env_path = os.environ.get("RUNNER_CONFIG")
        if env_path and Path(env_path).is_file():
            return cls._from_file(env_path)

        # 3. repo-root runner.json
        repo_root = Path(__file__).resolve().parent / "runner.json"
        if repo_root.is_file():
            return cls._from_file(str(repo_root))

        # 4. Permissive defaults
        logger.info("No runner config found — using permissive defaults")
        return cls(_permissive=True)

    @classmethod
    def _from_file(cls, path: str) -> RunnerConfig:
        with open(path) as f:
            data = json.load(f)
        boards = {}
        for entry in data.get("boards", []):
            boards[entry["url"]] = entry.get("status", "online")
        cfg = cls(
            runner_id=data.get("runner_id", "unknown"),
            boards=boards,
            features=data.get("features", {}),
        )
        logger.info("Loaded runner config '%s' from %s (%d boards, %d features)",
                     cfg.runner_id, path, len(cfg.boards), len(cfg.features))
        return cfg

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def board_status(self, url: str) -> str:
        """
        Returns the status of a board on this runner.

        Possible values:
          - "online"                 — board is connected and ready
          - "offline"                — board is known but currently disconnected
          - "busy"                   — board is in use by another session
          - "retired"                — board has been decommissioned
          - "unsupported"            — runner doesn't list this board
          - "unknown"                — board URL not recognised at all

        In permissive mode (no config file), all known boards return "online"
        and unknown URLs return "unknown".
        """
        if self._permissive:
            return "online" if url in KNOWN_BOARD_URLS else "unknown"
        if url in self.boards:
            return self.boards[url]
        if url in KNOWN_BOARD_URLS:
            return "unsupported"
        return "unknown"

    def has_feature(self, name: str) -> bool:
        """Check whether a hardware feature is available on this runner.

        In permissive mode, all features are assumed available.
        """
        if self._permissive:
            return True
        return bool(self.features.get(name, False))

    def camera_device(self) -> int:
        """Return the configured camera device index (default 0)."""
        return int(self.features.get("camera_device", 0))
