# WipperSnapper Display Test Session — Architecture Plan

## Goal
Full automated test session for validating WipperSnapper display/LED output across 13 boards,
with complete audit trail correlating visual events to serial logs and MQTT traffic.

## Per-Board Monitoring

### Visual event detection (OpenCV)
- **Continuous frame capture** from Pi Camera V3 via `BoardMonitor` (board_monitor.py)
- Each board has a dedicated ROI crop (calibrated via homography from yellow-box reference)
- **Frame diff detection** on each crop:
  - Display update: grayscale absdiff > threshold across display region
  - LED flash: bright blob appears/disappears in non-display area
  - Screen blank/unblank: mean luminance crosses threshold
- **Event types**: `display_update`, `led_flash`, `screen_on`, `screen_off`, `no_change`
- Each event logged with: `{timestamp_iso, board_url, event_type, frame_path, diff_score}`

### Audit log format (`artifacts/session_<ts>/events.jsonl`)
```json
{"ts": "2026-04-08T14:22:01.123Z", "board": "https://adafru.it/5483", "event": "display_update", "frame": "frames/5483_001234.jpg", "diff": 0.142}
{"ts": "2026-04-08T14:22:01.456Z", "board": "https://adafru.it/398",  "event": "led_flash",      "frame": "frames/398_001235.jpg",  "diff": 0.821}
```

### Serial log correlation
- Each board's `/dev/ttyACM*` captured continuously during test session
- Lines tagged with `{board_url, timestamp, line}` 
- MQTT debug mode: serial output includes MQTT publish/subscribe events
- Post-session: correlate visual event timestamps with serial log lines (±500ms window)

### MQTT correlation  
- Subscribe to all `tyeth/feeds/+` during test via Adafruit IO MQTT
- Log each message: `{ts, feed_key, value}`
- Cross-reference: display_update events should follow MQTT publish within ~poll_interval

## Video recording
- Full session video at 1080p from Pi Camera V3 (picamera2 continuous capture)
- Saved as `artifacts/session_<ts>/video.mp4`  
- Frame numbers embedded in event log for direct video seek
- Overlay option: draw board ROI boxes + event annotations on video

## Test session flow
1. `BoardMonitor.start()` — begin continuous frame capture for all 13 boards
2. `VideoRecorder.start()` — begin full-bench video
3. For each test:
   a. Power board ON via solenoid driver
   b. Monitor serial for WipperSnapper boot sequence
   c. Detect first display update event (board ready)
   d. Publish test values via Adafruit IO API
   e. Wait for display_update event (confirms board received + rendered)
   f. Capture still of board crop as test evidence
   g. Power board OFF
4. `VideoRecorder.stop()` + `BoardMonitor.stop()`
5. Generate HTML report with:
   - Per-board: first display frame, test frames, event timeline
   - Session timeline: all events across all boards
   - MQTT/serial correlation table

## Files
- `tools/board_monitor.py` — ROI crop + visual event detection
- `tools/video_capture.py` — full session video
- `tools/frame_extractor.py` — distinct frame extraction + LED detection
- `tools/solenoid_hub_control.py` — USB hub power control
- `tools/calibration_data.py` — QR positions + yellow-box ROIs + homography
- `conftest.py` — pytest fixtures wiring all the above
- `docs/test_session_plan.md` — this document

## Open items
- [ ] Implement `serial_monitor.py` — per-board serial capture + tagging
- [ ] Implement MQTT subscriber for test session correlation
- [ ] Add event overlay to video output
- [ ] pytest marker `@pytest.mark.board(url)` auto-starts monitor for that board
- [ ] Handle boards with no USB (WiFi-only) — detect via MQTT only
