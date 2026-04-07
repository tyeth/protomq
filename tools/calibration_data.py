"""
calibration_data.py — Reference calibration for the WipperSnapper test bench.

Measured from boards_annotated.jpg (2560x2092px).
Use these to compute scale factors when images are taken at different zoom/angles.

All coordinates are QR code CENTRES in pixels (original image coords).
"""

# Reference image dimensions
REF_WIDTH  = 2560
REF_HEIGHT = 2092

# QR code centre positions {adafru.it/<id>: (cx, cy)}
QR_CENTRES = {
    "https://adafru.it/398":  ( 815,  495),
    "https://adafru.it/1028": (1971, 1795),  # unit A (decoded by pyzbar)
    # NOTE: /1028 appears TWICE on the bench (two identical 2.9" R/B/W eInk boards)
    # Unit B QR was not decodable — position TBD from closer photo
    # "https://adafru.it/1028_b": (TBD, TBD),
    "https://adafru.it/2900": ( 934, 1605),
    "https://adafru.it/3129": (1355, 1152),
    "https://adafru.it/4116": ( 361, 1137),
    "https://adafru.it/4313": (1837,  539),
    "https://adafru.it/4440": (1383, 1901),
    "https://adafru.it/4650": ( 949, 1065),
    "https://adafru.it/4777": (1875, 1084),
    "https://adafru.it/4868": ( 325, 1831),
    "https://adafru.it/5300": (1371,  420),
    "https://adafru.it/5483": (1359,  785),
    "https://adafru.it/5691": ( 877, 1959),
}

# QR code physical size in pixels (reference image)
QR_SIZE_PX = 115  # average measured size

# Key calibration pairs — use these to scale new images
CALIB_PAIRS = {
    # (url_a, url_b): {"dist_px": float, "dx": float, "dy": float, "axis": str}
    "horizontal": {
        "a": "https://adafru.it/4116",
        "b": "https://adafru.it/3129",
        "dist_px": 994.1,
        "dx": 994.0,
        "dy": 15.0,
        "note": "Nearly horizontal — use for X scale",
    },
    "vertical": {
        "a": "https://adafru.it/5300",
        "b": "https://adafru.it/4440",
        "dist_px": 1481.0,
        "dx": 12.0,
        "dy": 1481.0,
        "note": "Nearly vertical — use for Y scale",
    },
    "diagonal": {
        "a": "https://adafru.it/4313",
        "b": "https://adafru.it/4868",
        "dist_px": 1988.8,
        "dx": 1512.0,
        "dy": 1292.0,
        "note": "Diagonal extreme — use for uniform scale",
    },
}


def compute_scale(detected_qrs: dict, axis: str = "diagonal") -> float:
    """
    Given a dict of {url: (cx, cy)} from a new image, compute the scale factor
    relative to the reference image.

    axis: "horizontal" | "vertical" | "diagonal"
    Returns scale (new_pixels / ref_pixels). Multiply ref coords by scale to get new coords.
    """
    import math
    pair = CALIB_PAIRS[axis]
    a_url, b_url = pair["a"], pair["b"]
    if a_url not in detected_qrs or b_url not in detected_qrs:
        # Fall back to any shared pair
        for pname, p in CALIB_PAIRS.items():
            if p["a"] in detected_qrs and p["b"] in detected_qrs:
                pair = p; a_url = p["a"]; b_url = p["b"]
                break
        else:
            return 1.0  # can't compute

    ax, ay = detected_qrs[a_url]
    bx, by = detected_qrs[b_url]
    new_dist = math.hypot(bx - ax, by - ay)
    return new_dist / pair["dist_px"]


def transform_roi(roi_ref, detected_qrs: dict) -> tuple:
    """
    Transform a reference-image ROI (x, y, w, h) to a new image's coordinates.
    Uses the best available calibration pair to estimate scale + offset.
    Returns (x, y, w, h) in new image coords.
    """
    import math

    # Find best common pair for scale
    scale = compute_scale(detected_qrs, "diagonal")
    if scale == 1.0:
        scale = compute_scale(detected_qrs, "horizontal")
    if scale == 1.0:
        scale = compute_scale(detected_qrs, "vertical")

    # Estimate offset: find a common QR and compute translation
    tx, ty = 0.0, 0.0
    common = [(url, pos) for url, pos in detected_qrs.items() if url in QR_CENTRES]
    if common:
        # Average offset across all common QRs
        offsets_x, offsets_y = [], []
        for url, (nx, ny) in common:
            rx, ry = QR_CENTRES[url]
            offsets_x.append(nx - rx * scale)
            offsets_y.append(ny - ry * scale)
        tx = sum(offsets_x) / len(offsets_x)
        ty = sum(offsets_y) / len(offsets_y)

    x, y, w, h = roi_ref
    nx = int(x * scale + tx)
    ny = int(y * scale + ty)
    nw = int(w * scale)
    nh = int(h * scale)
    return (nx, ny, nw, nh)
