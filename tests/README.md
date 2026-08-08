# Testing

Hardware-in-the-loop (HIL) test suite for the WipperSnapper display test bench.
Tests run via **pytest** against physical boards using a camera for visual
verification.

## Quick start

```bash
# Install dependencies
pip install -r requirements-test.txt

# Run all tests (permissive mode — no runner config needed)
pytest tests/ -v

# Run with a runner config
pytest tests/ -v --runner-config runner.json
```

## Runner configuration

Each self-hosted runner declares its capabilities in a `runner.json` file
(see `runner.json.example`). When no config is present, all boards and
features are assumed available (permissive mode).

```json
{
  "runner_id": "bench-alpha",
  "boards": [
    {"url": "https://adafru.it/4868", "status": "online", "revision": "2024-02"},
    {"url": "https://adafru.it/5300", "status": "online", "revision": "latest"}
  ],
  "features": {
    "camera": true,
    "camera_device": 0,
    "ppk2": false,
    "oscilloscope": false,
    "logic_analyser": false
  }
}
```

### Board status values

| Status    | Meaning                                |
|-----------|----------------------------------------|
| `online`  | Connected and ready for testing        |
| `offline` | Known but currently disconnected       |
| `busy`    | In use by another test session         |
| `retired` | Decommissioned, no longer on the bench |

### Features

| Feature           | Description                              |
|-------------------|------------------------------------------|
| `camera`          | USB camera for visual capture            |
| `camera_device`   | OpenCV device index (default `0`)        |
| `ppk2`            | Nordic Power Profiler Kit II (future)    |
| `oscilloscope`    | Muxed oscilloscope (future)              |
| `logic_analyser`  | Muxed logic analyser (future)            |

## Board revision matching

Tests and runner configs can specify board revisions. Matching is
**case-insensitive** and **generous** — it accepts many equivalent formats
for the same revision.

### Accepted formats

All of the following are equivalent ways to refer to the same revision:

| Format         | Example             | Notes                                |
|----------------|---------------------|--------------------------------------|
| Date (YYYY-MM) | `2024-05`          | Preferred canonical form             |
| Year only      | `2024`             | Matches any revision from that year  |
| Letter         | `A`, `B`, `C`      | 1st, 2nd, 3rd known revision         |
| Rev + letter   | `Rev A`, `RevA`    | With or without space                |
| `latest`       | `latest`           | Always matches the newest revision   |
| Current year   | `2026`             | Equivalent to `latest` for the newest revision |

Parsing rules:

- **Case-insensitive**: `rev a`, `Rev A`, `REVA`, `a` all normalise the same way.
- **"Rev" prefix is optional**: `Rev B` and `B` are identical.
- **Spaces are ignored** around the prefix: `Rev  C` and `RevC` and `C` all match.
- **"Revision" also works**: `Revision B` normalises to `b`.
- **Year-only matches year-month**: requesting `2024` matches a board at `2024-05`.
- **Month can be omitted**: `2024` in a runner config is valid (means "some 2024 revision").
- **`latest` is always generous**: on either the runner or test side, it matches anything.
- **Synthetic letters** are assigned from the known revision history (oldest = A).
  Products with no documented revisions treat their only revision as `A`.

### Examples

Given a board (PID 1028) with three known revisions:
- A = `2022-11` (UC8151D chipset)
- B = `2024-05` (EYESPI connector)
- C = `2025-06` (SSD1680 chipset, **breaking**)

| Runner has | Test requests | Match? | Why                              |
|------------|---------------|--------|----------------------------------|
| `2025-06`  | `C`           | Yes    | 3rd revision = letter C          |
| `2025-06`  | `Rev C`       | Yes    | "Rev" prefix stripped            |
| `2025-06`  | `2025`        | Yes    | Year-only matches 2025-06        |
| `2025-06`  | `latest`      | Yes    | Latest always matches            |
| `2025-06`  | `B`           | No     | Runner has C, test wants B       |
| `2024-05`  | `B`           | Yes    | 2nd revision = letter B          |
| `latest`   | `Rev C`       | Yes    | Runner "latest" resolves to C    |
| `latest`   | `A`           | Yes    | "latest" on runner side is generous |

### Breaking revisions

Some revisions require firmware or driver changes (marked `"breaking": true`
in `BOARD_REVISIONS`). The current breaking revisions are:

| PID  | Product                            | Date    | Change                              |
|------|------------------------------------|---------|-------------------------------------|
| 1028 | 2.9" eInk Display Breakout         | 2025-06 | SSD1680 chipset                     |
| 4777 | 2.9" Grayscale eInk FeatherWing    | 2025-07 | SSD1680 replaces ILI0373            |
| 5300 | ESP32-S2 TFT Feather               | 2023-05 | MAX17048 replaces LC709203          |
| 5483 | ESP32-S3 TFT Feather               | 2023-03 | MAX17048 replaces LC709203          |

## Markers

### `@pytest.mark.board(url)`

Associates a test with a physical board by its QR-code URL. Triggers video
capture and ROI detection automatically.

```python
@pytest.mark.board("https://www.adafruit.com/product/4413")
def test_display_updates(distinct_frames):
    assert len(distinct_frames) >= 3
```

### `@pytest.mark.requires_feature(name)`

Skips the test if the runner lacks a hardware feature.

```python
@pytest.mark.requires_feature("ppk2")
def test_power_profile(video_capture):
    ...
```

## Structured failure categories

When tests fail or skip due to hardware issues, failures are categorised
for CI reporting. The categories are written to `artifacts/hil_failures.jsonl`.

### Target failures (test is skipped)

| Code                                  | Meaning                          |
|---------------------------------------|----------------------------------|
| `unknown_target`                      | Board URL not in known set       |
| `unsupported_target`                  | Runner doesn't list this board   |
| `unavailable_target_temporarily_offline` | Board is offline              |
| `unavailable_target_busy`             | Board in use by another session  |
| `unavailable_target_retired`          | Board decommissioned             |

### Rig failures (test fails, except `no_camera` which skips)

| Code                           | Meaning                                    |
|--------------------------------|--------------------------------------------|
| `no_camera`                    | No camera device available                 |
| `camera_setup`                 | Camera opened but config failed            |
| `frame_not_including_qr`       | QR code not detected in video frames       |
| `unknown_camera_capture_failure` | Camera capture problem                   |
| `unsupported_feature_requested` | Feature not available for this board       |

### Infrastructure failures (test fails)

| Code               | Meaning                     |
|--------------------|-----------------------------|
| `network`          | Network connectivity issue  |
| `artifact_storage` | Can't write artifacts       |
| `dependency`       | Missing dependency          |

## CLI options

| Option             | Env var          | Default      | Description                    |
|--------------------|------------------|--------------|--------------------------------|
| `--video-device`   | `VIDEO_DEVICE`   | `0`          | OpenCV camera index            |
| `--video-fps`      | `VIDEO_FPS`      | `30`         | Recording FPS                  |
| `--video-width`    | `VIDEO_WIDTH`    | `1280`       | Frame width                    |
| `--video-height`   | `VIDEO_HEIGHT`   | `720`        | Frame height                   |
| `--artifacts-dir`  | `ARTIFACTS_DIR`  | `artifacts`  | Root directory for artifacts   |
| `--runner-config`  | `RUNNER_CONFIG`  | *(none)*     | Path to runner JSON config     |

Options resolve in order: CLI flag > environment variable > `pytest.ini` value > default.

## CI

The GitHub Actions workflow (`.github/workflows/hil-tests.yml`) runs on
self-hosted runners labelled `[self-hosted, hil-bench]`. It uploads test
artifacts, JUnit XML results, and writes a structured failure summary to
the GitHub Actions job summary.
