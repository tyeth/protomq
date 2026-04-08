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
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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

# Known product revisions — sourced from Adafruit product pages.
# Each entry lists revisions oldest-first; the last entry is the current one.
# Revisions with "breaking: True" require firmware/driver changes.
BOARD_REVISIONS: Dict[str, list] = {
    "https://adafru.it/398": [
        # RGB backlight positive LCD 16x2
        {"date": "2016-05", "note": "Mounting holes changed from 3mm to 3.2mm"},
        {"date": "2026-01", "note": "New AIP31066LC chip (code-compatible)"},
    ],
    "https://adafru.it/1028": [
        # 2.9" Red/Black/White eInk Display Breakout
        {"date": "2022-11", "note": "Updated to UC8151D chipset"},
        {"date": "2024-05", "note": "EYESPI connector + Pinguin silkscreen"},
        {"date": "2025-06", "note": "SSD1680 chipset", "breaking": True},
    ],
    "https://adafru.it/2900": [
        # FeatherWing OLED 128x32
        {"date": "2024-03", "note": "Pinguin silkscreen (functionally identical)"},
    ],
    "https://adafru.it/3129": [
        # 0.54" Quad Alphanumeric FeatherWing (Green)
        {"date": "2023-05", "note": "Added STEMMA QT connector + Pinguin silkscreen"},
    ],
    "https://adafru.it/4116": [
        # PyPortal
        # No documented revisions; cosmetic branding variants only.
    ],
    "https://adafru.it/4313": [
        # 1.3" 240x240 TFT LCD (ST7789)
        {"date": "2022-12", "note": "Added EYESPI connector"},
    ],
    "https://adafru.it/4440": [
        # Monochrome 0.91" 128x32 I2C OLED (STEMMA QT)
        {"date": "2024-06", "note": "Pinguin silkscreen (functionally identical)"},
    ],
    "https://adafru.it/4650": [
        # FeatherWing OLED 128x64 (STEMMA QT)
        {"date": "2024-06", "note": "Pinguin silkscreen (functionally identical)"},
    ],
    "https://adafru.it/4777": [
        # 2.9" Grayscale eInk FeatherWing
        {"date": "2025-07", "note": "SSD1680 chip replaces discontinued ILI0373",
         "breaking": True},
    ],
    "https://adafru.it/4868": [
        # 1.54" Tri-Color eInk 200x200 (SSD1681 + EYESPI)
        {"date": "2024-02", "note": "EYESPI connector + Pinguin silkscreen"},
    ],
    "https://adafru.it/5300": [
        # ESP32-S2 TFT Feather
        {"date": "2022-07", "note": "Alternative regulator (parts shortage)"},
        {"date": "2023-05", "note": "MAX17048 replaces discontinued LC709203 battery monitor + Pinguin",
         "breaking": True},
    ],
    "https://adafru.it/5483": [
        # ESP32-S3 TFT Feather
        {"date": "2023-03", "note": "MAX17048 replaces discontinued LC709203 battery monitor + Pinguin",
         "breaking": True},
    ],
    "https://adafru.it/5691": [
        # ESP32-S3 Reverse TFT Feather
        # No documented revisions.
    ],
}


# ---------------------------------------------------------------------------
# Revision parsing and matching
# ---------------------------------------------------------------------------

def _normalize_rev(raw: str) -> str:
    """Normalize a revision string for comparison.

    Strips "rev"/"revision" prefix, spaces, and lowercases.
      "Rev A" → "a",  "RevB" → "b",  "  C " → "c"
      "2024-05" → "2024-05",  "2024" → "2024"
      "latest" → "latest"
    """
    s = raw.strip().lower()
    # Strip leading "rev" / "revision" (with optional trailing space/dot)
    s = re.sub(r"^rev(?:ision)?\s*\.?\s*", "", s)
    return s


def _rev_index_to_letter(index: int) -> str:
    """0 → 'a', 1 → 'b', etc."""
    return chr(ord("a") + index)


def _revision_aliases(url: str, revision: str) -> Set[str]:
    """Build the set of normalised strings that a given revision matches.

    For a board with BOARD_REVISIONS = [rev0, rev1, rev2] and
    revision="2023-05" (which is rev1), the aliases are:
      {"2023-05", "2023", "b", "rev b", "revb"}
    Plus "latest" / current-year if it's the newest revision.
    """
    aliases: Set[str] = set()
    norm = _normalize_rev(revision)

    # "latest" is resolved to the actual latest known revision
    revs = BOARD_REVISIONS.get(url, [])
    if norm == "latest" and revs:
        norm = revs[-1]["date"]

    aliases.add(norm)

    # If it looks like a date, add the year-only form
    date_m = re.match(r"^(\d{4})(?:-(\d{2}))?$", norm)
    if date_m:
        aliases.add(date_m.group(1))  # year only

    # Find the index in the known revision list → synthetic letter
    for i, rev in enumerate(revs):
        if rev["date"] == norm:
            letter = _rev_index_to_letter(i)
            aliases.add(letter)
            # Also accept the prefixed forms
            aliases.add(f"rev {letter}")
            aliases.add(f"rev{letter}")
            # Is this the latest?
            if i == len(revs) - 1:
                aliases.add("latest")
                # Current year alias
                aliases.add(str(datetime.now().year))
            break

    # Products with no revision history: only revision is "latest" / "a"
    if not revs:
        aliases.update({"latest", "a", "rev a", "reva", str(datetime.now().year)})

    return aliases


def revision_matches(have: str, want: str, url: str) -> bool:
    """Check whether a runner's revision satisfies a requested revision.

    Both sides are parsed generously:
      - Case-insensitive
      - "Rev A" / "RevA" / "A" / "a" all match
      - "2024" matches "2024-05"
      - "latest" matches the most recent known revision (or current year)

    Parameters
    ----------
    have : str
        The revision the runner actually has (from runner.json).
    want : str
        The revision a test is requesting.
    url : str
        Board URL — used to look up BOARD_REVISIONS for letter mapping.

    Returns True if compatible.
    """
    have_norm = _normalize_rev(have)
    want_norm = _normalize_rev(want)

    # Trivial matches
    if have_norm == want_norm:
        return True
    if want_norm == "latest" or have_norm == "latest":
        # "latest" on either side is always generous
        return True

    # Build alias sets and check overlap
    have_aliases = _revision_aliases(url, have)
    want_aliases = _revision_aliases(url, want)
    return bool(have_aliases & want_aliases)


@dataclass
class BoardInfo:
    """Per-board metadata on a runner."""
    status: str = "online"          # online | offline | busy | retired
    revision: str = "latest"        # "latest", "Rev A", "Rev C", "2024", etc.


@dataclass
class RunnerConfig:
    runner_id: str = "local"
    boards: Dict[str, BoardInfo] = field(default_factory=dict)  # {url: BoardInfo}
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
            boards[entry["url"]] = BoardInfo(
                status=entry.get("status", "online"),
                revision=entry.get("revision", "latest"),
            )
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
            return self.boards[url].status
        if url in KNOWN_BOARD_URLS:
            return "unsupported"
        return "unknown"

    def board_revision(self, url: str) -> str:
        """Return the product revision for a board ('latest' if unspecified)."""
        if self._permissive or url not in self.boards:
            return "latest"
        return self.boards[url].revision

    def board_info(self, url: str) -> Optional[BoardInfo]:
        """Return full BoardInfo, or None if the board isn't on this runner."""
        return self.boards.get(url)

    def board_matches_revision(self, url: str, wanted: str) -> bool:
        """Check whether this runner's board satisfies a requested revision."""
        have = self.board_revision(url)
        return revision_matches(have, wanted, url)

    @staticmethod
    def known_revisions(url: str) -> list:
        """Return the known revision history for a product (oldest first)."""
        return BOARD_REVISIONS.get(url, [])

    @staticmethod
    def latest_known_revision(url: str) -> Optional[str]:
        """Return the date string of the latest known revision, or None."""
        revs = BOARD_REVISIONS.get(url, [])
        return revs[-1]["date"] if revs else None

    @staticmethod
    def has_breaking_revision(url: str) -> bool:
        """True if any revision for this product is a breaking change."""
        return any(r.get("breaking") for r in BOARD_REVISIONS.get(url, []))

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
